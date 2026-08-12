"""ROM platform detection from directory ancestry and unambiguous extensions."""

from pathlib import Path


SYSTEMS = {
    "gba": "GBA", "gbc": "GBC", "gb": "GB", "nds": "NDS", "3ds": "3DS",
    "n64": "N64", "nes": "NES", "fds": "FC", "sfc": "SFC", "smc": "SFC",
    "md": "MD", "gen": "MD", "smd": "MD", "32x": "32X", "gg": "GG",
    "sms": "SMS", "pce": "PCE", "psp": "PSP", "ps1": "PS1", "ps2": "PS2",
    "dc": "DC", "ngc": "NGC", "wii": "Wii", "wiiu": "WiiU",
    "nsp": "Switch", "xci": "Switch",
}

ARCADE_BOARDS = (
    "cps1", "cps2", "cps3", "cps", "neogeo", "naomi", "atomiswave",
    "pgm", "cave", "mame", "arcade", "fba", "fbneo", "capcom",
)

EXTENSION_PLATFORMS = {
    ".gba": "GBA", ".gbc": "GBC", ".gb": "GB", ".nds": "NDS",
    ".3ds": "3DS", ".n64": "N64", ".z64": "N64", ".v64": "N64",
    ".nes": "NES", ".fds": "FC", ".sfc": "SFC", ".smc": "SFC",
    ".smd": "MD", ".md": "MD", ".gen": "MD", ".32x": "32X",
    ".gg": "GG", ".sms": "SMS", ".pce": "PCE", ".wbfs": "Wii",
    ".wad": "Wii", ".nsp": "Switch", ".xci": "Switch", ".nsz": "Switch",
}


def platform_from_dirname(dirname: str) -> str:
    """Return a canonical platform for a directory name, or an empty string."""
    low = dirname.lower().replace(" ", "").replace("-", "").replace("_", "")
    if any(board in low for board in ARCADE_BOARDS):
        return "Arcade"
    # Longest keys first: e.g. ``wiiu`` must not be consumed by ``wii``.
    for key in sorted(SYSTEMS, key=len, reverse=True):
        platform = SYSTEMS[key]
        if key in low:
            return platform
    return ""


def detect_rom_platform(rom_path: str, max_parent_levels: int = 6) -> tuple[str, str]:
    """Detect platform from nearest ancestor, then an unambiguous extension.

    Returns ``(platform, source)``. Both values are empty if the platform is unknown.
    """
    path = Path(rom_path)
    parent = path.parent
    for _ in range(max_parent_levels):
        if not parent.name:
            break
        platform = platform_from_dirname(parent.name)
        if platform:
            return platform, f"目录 {parent.name}"
        next_parent = parent.parent
        if next_parent == parent:
            break
        parent = next_parent

    platform = EXTENSION_PLATFORMS.get(path.suffix.lower(), "")
    if platform:
        return platform, f"扩展名 {path.suffix.lower()}"
    return "", ""
