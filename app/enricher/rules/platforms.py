from __future__ import annotations

# Cada plataforma tiene:
#   nombre    → nombre completo para descripciones
#   abrev     → abreviatura para títulos
#   vinted    → texto exacto que aparece en el dropdown de Vinted
PLATFORMS: dict[str, dict[str, str]] = {
    "ps1":        {"nombre": "PlayStation",       "abrev": "PS1",         "vinted": "PlayStation"},
    "ps2":        {"nombre": "PlayStation 2",     "abrev": "PS2",         "vinted": "PlayStation 2"},
    "ps3":        {"nombre": "PlayStation 3",     "abrev": "PS3",         "vinted": "PlayStation 3"},
    "ps4":        {"nombre": "PlayStation 4",     "abrev": "PS4",         "vinted": "PlayStation 4"},
    "ps5":        {"nombre": "PlayStation 5",     "abrev": "PS5",         "vinted": "PlayStation 5"},
    "psp":        {"nombre": "PSP",               "abrev": "PSP",         "vinted": "PSP"},
    "psvita":     {"nombre": "PS Vita",           "abrev": "PS Vita",     "vinted": "PS Vita"},
    "vita":       {"nombre": "PS Vita",           "abrev": "PS Vita",     "vinted": "PS Vita"},
    "xbox":       {"nombre": "Xbox",              "abrev": "Xbox",        "vinted": "Xbox"},
    "xbox360":    {"nombre": "Xbox 360",          "abrev": "Xbox 360",    "vinted": "Xbox 360"},
    "xboxone":    {"nombre": "Xbox One",          "abrev": "Xbox One",    "vinted": "Xbox One"},
    "xboxseries": {"nombre": "Xbox Series X/S",   "abrev": "Xbox Series", "vinted": "Xbox Series X/S"},
    "switch":     {"nombre": "Nintendo Switch",   "abrev": "Switch",      "vinted": "Nintendo Switch"},
    "wiiu":       {"nombre": "Nintendo Wii U",    "abrev": "Wii U",       "vinted": "Wii U"},
    "wii":        {"nombre": "Nintendo Wii",      "abrev": "Wii",         "vinted": "Wii"},
    "gamecube":   {"nombre": "GameCube",          "abrev": "GameCube",    "vinted": "GameCube"},
    "gc":         {"nombre": "GameCube",          "abrev": "GameCube",    "vinted": "GameCube"},
    "n64":        {"nombre": "Nintendo 64",       "abrev": "N64",         "vinted": "Nintendo 64"},
    "nes":        {"nombre": "NES",               "abrev": "NES",         "vinted": "NES"},
    "snes":       {"nombre": "Super Nintendo",    "abrev": "SNES",        "vinted": "Super Nintendo"},
    "ds":         {"nombre": "Nintendo DS",       "abrev": "DS",          "vinted": "Nintendo DS"},
    "3ds":        {"nombre": "Nintendo 3DS",      "abrev": "3DS",         "vinted": "Nintendo 3DS"},
    "gba":        {"nombre": "Game Boy Advance",  "abrev": "GBA",         "vinted": "Game Boy Advance"},
    "gbc":        {"nombre": "Game Boy Color",    "abrev": "GBC",         "vinted": "Game Boy Color"},
    "gb":         {"nombre": "Game Boy",          "abrev": "GB",          "vinted": "Game Boy"},
    "pc":         {"nombre": "PC",                "abrev": "PC",          "vinted": "PC"},
    "steam":      {"nombre": "PC / Steam",        "abrev": "PC",          "vinted": "PC"},
}

PLATFORM_KEYWORDS: frozenset[str] = frozenset(PLATFORMS.keys())


def detectar_plataforma(tokens: list[str]) -> dict[str, str] | None:
    """Dado el slug tokenizado, devuelve el dict de plataforma o None."""
    for token in tokens:
        if token in PLATFORM_KEYWORDS:
            return PLATFORMS[token]
    return None
