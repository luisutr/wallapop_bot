"""
Auditoría de formularios Wallapop / Vinted.

Guarda en logs/ un JSON por intento de publicación con:
  - snapshot de todos los inputs visibles en cada paso
  - valores que intentamos enviar vs valores reales en el DOM
  - campos obligatorios vacíos o con error de validación
  - verificación post-envío (¿de verdad se publicó?)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from config import LOGS_DIR

# Campos que deben tener valor antes de enviar (selectores CSS / id)
CAMPOS_OBLIGATORIOS: dict[str, list[dict[str, str]]] = {
    "wallapop": [
        {"id": "title", "label": "Título"},
        {"id": "description", "label": "Descripción"},
        {"id": "price_amount", "label": "Precio"},
        {"selector": '[data-testid="condition"]', "label": "Estado"},
        {"selector": 'input[name="category_leaf_id"], #category_leaf_id', "label": "Categoría"},
    ],
    "vinted": [
        {"id": "title", "label": "Título"},
        {"id": "description", "label": "Descripción"},
        {"id": "price", "label": "Precio"},
        {"id": "category", "label": "Categoría"},
        {"id": "condition", "label": "Condición"},
        {"id": "brand", "label": "Marca", "only_if_visible": True},
    ],
}

# JS: extrae estado del formulario en la página actual
_SNAPSHOT_JS = """
() => {
    const fields = [];
    const seen = new Set();

    function addField(el, extra = {}) {
        const key = (el.id || el.name || el.getAttribute('data-testid') || '') + el.type;
        if (seen.has(key)) return;
        seen.add(key);

        let label = '';
        if (el.labels && el.labels[0]) label = el.labels[0].innerText;
        else if (el.getAttribute('aria-label')) label = el.getAttribute('aria-label');
        else if (el.placeholder) label = el.placeholder;
        else {
            const lbl = document.querySelector(`label[for="${el.id}"]`);
            if (lbl) label = lbl.innerText;
        }

        const style = window.getComputedStyle(el);
        const rect = el.getBoundingClientRect();
        const visible = style.display !== 'none' && style.visibility !== 'hidden'
            && rect.width > 0 && rect.height > 0;

        let value = '';
        if (el.type === 'checkbox' || el.type === 'radio') {
            value = el.checked ? 'checked' : 'unchecked';
        } else {
            value = (el.value || '').toString().slice(0, 300);
        }

        fields.push({
            id: el.id || null,
            name: el.name || null,
            testid: el.getAttribute('data-testid') || null,
            type: el.type || el.tagName.toLowerCase(),
            tag: el.tagName.toLowerCase(),
            value,
            label: (label || '').trim().slice(0, 120),
            required: el.required || el.getAttribute('aria-required') === 'true',
            invalid: el.getAttribute('aria-invalid') === 'true',
            disabled: el.disabled,
            visible,
            ...extra,
        });
    }

    document.querySelectorAll(
        'input:not([type="hidden"]), textarea, select, [contenteditable="true"]'
    ).forEach(el => addField(el));

    // Wallapop: dropdowns Stencil (valor en hidden input)
    document.querySelectorAll(
        'input[type="hidden"][name], input.walla-dropdown__inner-input__hidden-input, ' +
        'walla-dropdown[data-testid]'
    ).forEach(el => {
        const aria = el.getAttribute('aria-label') || el.closest('walla-dropdown')?.getAttribute('aria-label');
        addField(el, {
            walla_dropdown: true,
            aria_label: aria || null,
            value: el.value || el.getAttribute('value') || '',
        });
    });

    // Mensajes de error visibles
    const errors = [];
    const errSelectors = [
        '[role="alert"]', '[aria-live="assertive"]', '.error', '[class*="error-message"]',
        '[class*="Error"]', 'walla-text-input[aria-invalid="true"]',
    ];
    errSelectors.forEach(sel => {
        document.querySelectorAll(sel).forEach(el => {
            const t = (el.innerText || el.textContent || '').trim();
            if (t && t.length < 500) errors.push(t);
        });
    });

    // Dropdowns Wallapop con aria-invalid
    document.querySelectorAll('[aria-invalid="true"]').forEach(el => {
        const lbl = el.getAttribute('aria-label') || el.id || 'campo';
        errors.push(`Campo inválido: ${lbl}`);
    });

    // Fotos subidas (contadores / miniaturas)
    const fileInputs = document.querySelectorAll('input[type="file"]');
    let photosCount = 0;
    fileInputs.forEach(inp => {
        if (inp.files) photosCount += inp.files.length;
    });
    const thumbs = document.querySelectorAll(
        '[class*="thumbnail"], [class*="photo"], [data-testid*="photo"]'
    ).length;

    return {
        url: location.href,
        title: document.title,
        fields,
        errors: [...new Set(errors)],
        photos_in_inputs: photosCount,
        photo_thumbnails_dom: thumbs,
        body_snippet: document.body.innerText.slice(0, 800),
    };
}
"""

_VERIFY_JS = """
(plataforma) => {
    const url = location.href;
    const body = document.body.innerText.toLowerCase();

    const successPhrases = [
        'subido', 'publicado', 'en venta', 'listado creado', 'tu producto',
        'artículo publicado', 'item published', 'listing created', '¡listo!',
        'se ha publicado', 'ya está a la venta',
    ];
    const hasSuccessText = successPhrases.some(p => body.includes(p));

    let stillOnForm = false;
    let formSelector = '';

    if (plataforma === 'wallapop') {
        stillOnForm = url.includes('/upload') ||
            !!(document.querySelector('#price_amount') || document.querySelector('#sale_price'));
        formSelector = '#price_amount,#sale_price,#title,#summary';
    } else {
        stillOnForm = url.includes('/items/new') &&
            !!document.querySelector('[data-testid="upload-form-save-button"], #title');
        formSelector = '#title,[data-testid=upload-form-save-button]';
    }

    const invalidFields = [...document.querySelectorAll('[aria-invalid="true"]')].map(el =>
        el.id || el.getAttribute('aria-label') || el.name || '?'
    );

    const submitVisible = !!document.querySelector(
        plataforma === 'wallapop'
            ? 'text=Subir producto, button:has-text("Subir")'
            : '[data-testid="upload-form-save-button"]'
    );

    // Si seguimos en el formulario con errores → fallo
    const likelyFailed = stillOnForm && (invalidFields.length > 0 || body.includes('obligatorio')
        || body.includes('requerido') || body.includes('required'));

    const likelySuccess = hasSuccessText || (!stillOnForm && !submitVisible);

    return {
        url,
        stillOnForm,
        hasSuccessText,
        invalidFields,
        submitStillVisible: submitVisible,
        likelySuccess,
        likelyFailed: likelyFailed || (stillOnForm && invalidFields.length > 0),
    };
}
"""


class PublishAudit:
    """Registra y analiza el estado del formulario en cada paso."""

    def __init__(
        self,
        plataforma: str,
        slug: str,
        producto: dict,
        log_fn: Optional[Callable[[str], None]] = None,
    ):
        self.plataforma = plataforma
        self.slug = slug
        self.producto_intended = {
            k: producto.get(k)
            for k in (
                "slug", "titulo", "descripcion", "precio",
                "estado_texto", "estado_vinted", "categoria_vinted",
                "marca", "tipo", "fotos",
            )
            if producto.get(k) is not None
        }
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = LOGS_DIR / f"{plataforma}_{slug}_{ts}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.steps: list[dict[str, Any]] = []
        self.issues: list[str] = []
        self.log_fn = log_fn
        self._step_n = 0

    def _emit(self, msg: str) -> None:
        line = f"  [audit/{self.plataforma}] {msg}"
        print(line)
        if self.log_fn:
            self.log_fn(f"[audit] {msg}")

    def snapshot(
        self,
        page,
        step_name: str,
        intended: Optional[dict[str, Any]] = None,
        screenshot: bool = True,
    ) -> dict[str, Any]:
        """Captura el estado del formulario y lo guarda."""
        self._step_n += 1
        try:
            data = page.evaluate(_SNAPSHOT_JS)
        except Exception as exc:
            data = {"error": str(exc), "fields": [], "errors": []}

        analysis = self._analyze_snapshot(data, intended)

        entry = {
            "n": self._step_n,
            "step": step_name,
            "timestamp": datetime.now().isoformat(),
            "intended": intended or {},
            "snapshot": data,
            "analysis": analysis,
        }
        self.steps.append(entry)

        if analysis["empty_required"]:
            for f in analysis["empty_required"]:
                self.issues.append(f"Paso '{step_name}': obligatorio vacío — {f}")
        if analysis["missing_expected"]:
            for f in analysis["missing_expected"]:
                self.issues.append(f"Paso '{step_name}': falta campo esperado — {f}")
        if data.get("errors"):
            for e in data["errors"][:5]:
                self.issues.append(f"Paso '{step_name}': error UI — {e[:120]}")

        if screenshot:
            try:
                path = self.run_dir / f"{self._step_n:02d}_{step_name}.png"
                page.screenshot(path=str(path), full_page=True)
                entry["screenshot"] = path.name
            except Exception:
                pass

        self._save_report(partial=True)

        # Resumen en consola
        n_fields = len(data.get("fields", []))
        n_vis = sum(1 for f in data.get("fields", []) if f.get("visible"))
        self._emit(
            f"{step_name}: {n_vis}/{n_fields} campos visibles | "
            f"vacíos oblig: {len(analysis['empty_required'])} | "
            f"faltan: {len(analysis['missing_expected'])} | "
            f"errores UI: {len(data.get('errors', []))}"
        )
        return entry

    def _analyze_snapshot(
        self,
        data: dict,
        intended: Optional[dict],
    ) -> dict[str, Any]:
        fields = data.get("fields", [])
        expected = CAMPOS_OBLIGATORIOS.get(self.plataforma, [])

        def field_value(field_id: str | None, selector: str | None = None) -> str:
            for f in fields:
                if field_id and f.get("id") == field_id:
                    return (f.get("value") or "").strip()
                if selector and f.get("testid") and selector in (f.get("testid") or ""):
                    return (f.get("value") or "").strip()
            return ""

        def has_field(field_id: str | None, selector: str | None = None) -> bool:
            for f in fields:
                if not f.get("visible") and not f.get("walla_dropdown"):
                    continue
                if field_id and f.get("id") == field_id:
                    return True
                if selector:
                    # hidden category_leaf_id etc.
                    if field_id and f.get("id") == field_id.replace("#", ""):
                        return True
            if field_id:
                for f in fields:
                    if f.get("id") == field_id:
                        return True
            return False

        empty_required: list[str] = []
        missing_expected: list[str] = []

        for exp in expected:
            fid = exp.get("id")
            label = exp.get("label", fid or "?")
            only_if_visible = exp.get("only_if_visible", False)

            found_visible = False
            val = ""
            for f in fields:
                if f.get("id") != fid:
                    continue
                if f.get("visible") or fid in ("category", "condition"):
                    found_visible = True
                    val = (f.get("value") or "").strip()
                    if f.get("type") in ("checkbox", "radio"):
                        val = f.get("value", "")

            if only_if_visible and not found_visible:
                continue
            if found_visible and not val and fid not in ("category",):
                # category en Vinted puede ser input readonly con valor interno
                if fid == "category" and val == "":
                    # comprobar si hay texto en el input aunque value vacío
                    pass
                else:
                    empty_required.append(label)

        # Comparar intended vs DOM (solo en paso detalles)
        mismatches: list[str] = []
        if intended:
            if intended.get("titulo") and field_value("title"):
                t_int = str(intended["titulo"])[:50]
                t_dom = field_value("title")[:50]
                if t_int and t_dom and t_int not in t_dom and t_dom not in t_int:
                    mismatches.append(f"título: enviado '{t_int}' vs DOM '{t_dom}'")
            if self.plataforma == "wallapop":
                p_dom = (
                    field_value("price_amount") or field_value("sale_price")
                ).replace(",", ".")
            else:
                p_dom = field_value("price").replace(",", ".")
            if intended.get("precio") is not None:
                p_int = str(round(float(intended["precio"]), 2))
                if p_dom and p_int not in p_dom:
                    mismatches.append(f"precio: enviado {p_int} vs DOM '{p_dom}'")

        return {
            "empty_required": empty_required,
            "missing_expected": missing_expected,
            "mismatches": mismatches,
            "field_count": len(fields),
        }

    def check_before_submit(self, page) -> dict[str, Any]:
        """Análisis final inmediatamente antes de pulsar Publicar."""
        entry = self.snapshot(page, "pre_submit", intended=self.producto_intended)
        analysis = entry["analysis"]
        ok = (
            not analysis["empty_required"]
            and not entry["snapshot"].get("errors")
        )
        if not ok:
            self._emit("⚠ Formulario incompleto antes de enviar — ver logs/")
        return {"ok": ok, **analysis, "snapshot": entry["snapshot"]}

    def verify_after_submit(self, page, wait_ms: int = 8000) -> dict[str, Any]:
        """Espera y comprueba si la publicación fue real."""
        page.wait_for_timeout(wait_ms)
        try:
            result = page.evaluate(_VERIFY_JS, self.plataforma)
        except Exception as exc:
            result = {"error": str(exc), "likelySuccess": False, "likelyFailed": True}

        self.snapshot(page, "post_submit", screenshot=True)

        success = bool(result.get("likelySuccess")) and not bool(result.get("likelyFailed"))

        if not success:
            if result.get("stillOnForm"):
                self.issues.append("Post-envío: sigue en la página del formulario")
            if result.get("invalidFields"):
                self.issues.append(
                    f"Post-envío: campos inválidos: {', '.join(result['invalidFields'])}"
                )
            if not result.get("hasSuccessText"):
                self.issues.append("Post-envío: no se detectó mensaje de éxito")

        self._emit(
            f"Verificación: éxito={success} | en_formulario={result.get('stillOnForm')} | "
            f"texto_éxito={result.get('hasSuccessText')}"
        )

        return {"success": success, "details": result}

    def finalize(
        self,
        claimed_success: bool,
        exception: Optional[str] = None,
        verify: Optional[dict] = None,
    ) -> Path:
        """Cierra el informe y devuelve la ruta del JSON."""
        verified = verify.get("success", False) if verify else None
        if verified is not None:
            real_success = claimed_success and not exception and verified
        else:
            real_success = claimed_success and not self.issues and not exception

        report = {
            "plataforma": self.plataforma,
            "slug": self.slug,
            "started": self.steps[0]["timestamp"] if self.steps else None,
            "finished": datetime.now().isoformat(),
            "producto_intended": self.producto_intended,
            "claimed_success": claimed_success,
            "verify_result": verify,
            "real_success": real_success,
            "exception": exception,
            "issues": self.issues,
            "steps": self.steps,
            "recommendation": self._recommendation(),
        }

        path = self.run_dir / "report.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        status = "✓ REAL" if real_success else "✗ FALLO/APARENTE"
        self._emit(f"Informe {status} → {path}")

        # Resumen legible
        summary_path = self.run_dir / "resumen.txt"
        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(f"Plataforma: {self.plataforma}\n")
            f.write(f"Producto: {self.slug}\n")
            f.write(f"Éxito real: {real_success}\n")
            f.write(f"Éxito declarado por código: {claimed_success}\n\n")
            if exception:
                f.write(f"Excepción: {exception}\n\n")
            if self.issues:
                f.write("Problemas detectados:\n")
                for i, issue in enumerate(self.issues, 1):
                    f.write(f"  {i}. {issue}\n")
            f.write(f"\nRecomendación:\n{report['recommendation']}\n")

        return path

    def _recommendation(self) -> str:
        if not self.issues:
            return "Publicación verificada correctamente."
        lines = []
        text = " ".join(self.issues).lower()
        if "estado" in text or "condition" in text:
            lines.append("- Revisar selección de Estado/Condición (dropdown no aplicó el valor).")
        if "categor" in text:
            lines.append("- Revisar Categoría (Wallapop: primera sugerencia; Vinted: texto del dropdown).")
        if "marca" in text or "brand" in text:
            lines.append("- Vinted suele exigir Marca: añadir marca en meta.json o mejorar detección.")
        if "precio" in text or "price" in text:
            lines.append("- El precio no quedó en el campo: disparar Tab/blur tras rellenar.")
        if "sigue en la página del formulario" in text or "post-envío" in text:
            lines.append(
                "- El clic en Publicar NO completó el envío: hay validación pendiente. "
                "Revisa report.json paso 'pre_submit'."
            )
        if "fotos" in text or "photo" in text:
            lines.append("- Problema con fotos: esperar más tiempo antes de Continuar.")
        if not lines:
            lines.append("- Ver capturas PNG y report.json en la carpeta de logs.")
        return "\n".join(lines)

    def _save_report(self, partial: bool = False) -> None:
        path = self.run_dir / ("report_partial.json" if partial else "report.json")
        data = {
            "plataforma": self.plataforma,
            "slug": self.slug,
            "issues": self.issues,
            "steps": self.steps,
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)


def raise_if_not_verified(audit: PublishAudit, verify: dict[str, Any]) -> None:
    """Lanza error si la verificación post-envío falló."""
    if not verify.get("success"):
        details = verify.get("details", {})
        invalid = details.get("invalidFields", [])
        msg = (
            f"La publicación en {audit.plataforma} NO se completó "
            f"(el formulario sigue activo o hay errores de validación)."
        )
        if invalid:
            msg += f" Campos inválidos: {', '.join(invalid)}."
        msg += f" Ver: {audit.run_dir}"
        raise RuntimeError(msg)
