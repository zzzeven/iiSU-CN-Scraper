#!/usr/bin/env python3
"""iiSU-CN-Scraper — Android APK (Flet / Flutter)

Material Design 3 暗色主题，圆形扫描按钮，设置页，刮削页。
"""

import json, os, subprocess, sys, threading, time
from pathlib import Path
from urllib.parse import unquote
sys.path.insert(0, str(Path(__file__).resolve().parent))

import flet as ft

from openai import OpenAI
from modules.llm_normalizer import normalize_rom_name
from modules.bangumi_fetcher import BangumiFetcher
from modules.tgdb_fetcher import TGDBFetcher
from modules.gamegear_fetcher import GameGearFetcher
from modules.platform_detector import detect_rom_platform
from modules.llm_normalizer import translate_desc
from modules.xml_builder import (
    load_existing_gamelist, build_game_element, write_gamelist,
)

# ======================================================================
# iiSU 配色 — 暗底蓝紫
# ======================================================================
BG         = "#0b0b16"
SURFACE    = "#151527"
CARD_BG    = "#1c1c32"
ACCENT     = "#8b5cf6"
ACCENT2    = "#6366f1"
TEXT       = "#e4e4ee"
TEXT_DIM   = "#9292a8"

# ======================================================================
# ROM 检测
# ======================================================================
if sys.platform == "win32":
    ROM_ROOTS = [
        os.path.expanduser("~/ROMs"),
        os.path.expanduser("~/Documents/ROMs"),
        os.path.expanduser("~/Desktop/ROMs"),
        os.path.expanduser("~/Documents/RetroArch/roms"),
        os.path.expanduser("~/Documents/Dolphin Emulator/Games"),
        os.path.expanduser("~/Documents/PCSX2/roms"),
        "D:\\ROMs", "D:\\Games", "D:\\Emulation\\roms",
    ]
elif sys.platform == "darwin":
    ROM_ROOTS = [
        os.path.expanduser("~/ROMs"),
        os.path.expanduser("~/Documents/ROMs"),
        os.path.expanduser("~/Desktop/ROMs"),
        os.path.expanduser("~/Documents/RetroArch/roms"),
        os.path.expanduser("~/Documents/Dolphin Emulator/Games"),
        os.path.expanduser("~/Library/Application Support/RetroArch/roms"),
        os.path.expanduser("~/Library/Application Support/OpenEmu/ROMs"),
        os.path.expanduser("~/Library/Application Support/RetroArch/system"),
        os.path.expanduser("~/Games"),
        os.path.expanduser("~/Emulation/roms"),
    ]
else:
    # Android / Linux
    ROM_ROOTS = [
        "/storage/emulated/0/ROMs", "/storage/emulated/0/roms",
        "/sdcard/ROMs", "/sdcard/roms",
        "/storage/emulated/0/Emulation/roms",
        "/storage/emulated/0/Games",
        "/storage/emulated/0/Download",
        "/storage/0000-0000/ROMs", "/storage/0000-0000/roms",
        "/storage/emulated/0/RetroArch/roms",
        "/storage/emulated/0/Documents/ROMs",
        "/storage/emulated/0/Documents/roms",
        "/storage/emulated/0/Documents/Games",
    ]
ROM_EXTS = {
    ".gba", ".gbc", ".gb", ".nds", ".3ds", ".n64", ".z64", ".v64",
    ".nes", ".fds", ".sfc", ".smc", ".smd", ".md", ".gen", ".32x",
    ".gg", ".sms", ".pce", ".cue", ".bin", ".iso", ".cso", ".chd",
    ".pbp", ".wbfs", ".wad", ".nsp", ".xci", ".nsz", ".zip", ".7z",
}
SYSTEMS = {
    "gba":"GBA","gbc":"GBC","gb":"GB","nds":"NDS","3ds":"3DS",
    "n64":"N64","nes":"NES","fds":"FC","sfc":"SFC","smc":"SFC",
    "md":"MD","gen":"MD","smd":"MD","32x":"32X","gg":"GG","sms":"SMS",
    "pce":"PCE","psp":"PSP","ps1":"PS1","ps2":"PS2","dc":"DC",
    "ngc":"NGC","wii":"Wii","wiiu":"WiiU","nsp":"Switch","xci":"Switch",
}

# 街机基板目录名 → Arcade（必须在 SYSTEMS 之前匹配，避免 cps2 误命中 ps2）
ARCADE_BOARDS = ("cps1", "cps2", "cps3", "cps", "neogeo", "naomi", "atomiswave",
                 "pgm", "cave", "mame", "arcade", "fba", "fbneo", "capcom")

def _sys(dirname):
    low = dirname.lower().replace(" ","").replace("-","").replace("_","")
    # 街机基板优先：CPS1/CPS2/CPS3/NeoGeo 等 → Arcade
    if any(b in low for b in ARCADE_BOARDS):
        return "Arcade"
    for k,v in SYSTEMS.items():
        if k in low: return v
    return dirname[:12]

# 通用扫描时跳过的目录名（系统/应用/媒体目录）
SKIP_DIRS = {"Android", "DCIM", "Pictures", "Music", "Movies", "Download",
             "Documents", "Alarms", "Audiobooks", "Notifications", "Podcasts",
             "Ringtones", "LOST.DIR", "data", "obb", "cache", "temp",
             ".thumbnails", ".Trash", "Pendownload", "Tencent", "backups",
             "Recordings", "SpeedSoftware", "TitaniumBackup", "MIUI",
             "ColorOS", "Snapdrop", "Edit", "Fonts", "Notifications",
             "Sounds", "Ringtones", "Pictures", "Movies", "Podcasts",
             "Recordings", "tbs", "tp", "talkingdata", "bugly", "umeng",
             # Windows 用户目录复数名（避免全盘扫描浪费时间）
             "Downloads", "Videos", "OneDrive", "node_modules", "WindowsApps",
             "ProgramData", "$Recycle.Bin", "System Volume Information"}

# 桌面端系统目录 — 避免递归扫描浪费在系统文件上
if sys.platform == "win32":
    SKIP_DIRS |= {
        "Windows", "Program Files", "Program Files (x86)",
        "ProgramData", "$Recycle.Bin", "System Volume Information",
        "Recovery", "Config.Msi", "MSOCache", "PerfLogs",
        "WindowsApps", "AppData", "Application Data",
        "Local Settings", "NetHood", "PrintHood", "Recent",
        "SendTo", "Start Menu", "Templates", "Cookies",
        "Intel", "AMD", "NVIDIA", "Drivers",
    }
elif sys.platform == "darwin":
    SKIP_DIRS |= {
        "Applications", "Library", "System", "opt", "private",
        "usr", "bin", "sbin", "etc", "var", "tmp", "cores",
        "dev", "home", "net",
        ".Spotlight-V100", ".Trashes", ".fseventsd",
        ".DocumentRevisions-V100", ".TemporaryItems",
    }
SKIP_PREFIXES = ("com.", "org.", "net.", "io.", "cn.", "de.")

if sys.platform == "win32":
    ROM_SEARCH_ROOTS = [
        os.path.expanduser("~"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
    ]
elif sys.platform == "darwin":
    ROM_SEARCH_ROOTS = [
        os.path.expanduser("~"),
        os.path.expanduser("~/Documents"),
        os.path.expanduser("~/Desktop"),
        "/Volumes",
    ]
else:
    # Android
    ROM_SEARCH_ROOTS = [
        "/storage/emulated/0",
        "/sdcard",
    ]

def _detect_device_vendor() -> str:
    """Detect device manufacturer for vendor-specific permission intents."""
    for prop in ['ro.product.manufacturer', 'ro.product.brand']:
        try:
            result = subprocess.run(['getprop', prop], capture_output=True, text=True, timeout=1)
            v = result.stdout.strip().lower()
            if v:
                return v
        except Exception:
            continue
    return "unknown"


def _am_start(*args):
    """Try /system/bin/am first, then am (some devices only have one)."""
    for am in ['/system/bin/am', 'am']:
        try:
            subprocess.run([am, 'start'] + list(args), timeout=3, check=False)
            return True
        except Exception:
            continue
    return False


def _open_app_settings():
    """Open the app's own system settings page where all permissions can be toggled."""
    if sys.platform in ("win32", "darwin"):
        return False
    for action in [
        '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS',
        '-d', 'package:com.kiloiam.iisu_cn_scraper',
    ]:
        pass
    return _am_start(
        '-a', 'android.settings.APPLICATION_DETAILS_SETTINGS',
        '-d', 'package:com.kiloiam.iisu_cn_scraper',
    )


def _open_all_files_access(vendor: str = ""):
    """Open the All Files Access permission page using the most compatible intent.

    Tries multiple intent actions in order of specificity, falling back to
    the generic page that works on all Android 11+ devices.
    """
    if sys.platform in ("win32", "darwin"):
        return False
    pkg = 'package:com.kiloiam.iisu_cn_scraper'

    # 1) Directed intent (Android 12+, may work on stock Android)
    if _am_start('-a', 'android.settings.MANAGE_APP_ALL_FILES_ACCESS_PERMISSION', '-d', pkg):
        return True

    # 2) Generic all-files-access page (all Android 11+)
    if _am_start('-a', 'android.settings.MANAGE_ALL_FILES_ACCESS_PERMISSION'):
        return True

    # 3) Last resort: open app details page so user can find the toggle manually
    return _open_app_settings()


def _auto_grant_storage():
    """Android 手动触发：打开「所有文件访问」权限页面（多 intent 回退）。"""
    if sys.platform in ("win32", "darwin"):
        return
    _open_all_files_access()


def _normalize_android_path(path: str) -> str:
    raw = (path or "").strip().strip('"').strip("'")
    if not raw:
        return ""
    # Windows 绝对路径 (如 D:\ROMs) — 直接返回，不要当成 Android URI 处理
    if len(raw) >= 2 and raw[1] == ":":
        return os.path.normpath(raw)
    if raw.startswith("file://"):
        raw = unquote(raw[7:])
    if raw.startswith("/tree/"):
        raw = raw[6:]
    if raw.startswith("primary:"):
        raw = "/storage/emulated/0/" + raw.split(":", 1)[1].lstrip("/")
    if ":" in raw and not raw.startswith("/"):
        volume, rest = raw.split(":", 1)
        raw = f"/storage/{volume}/{rest.lstrip('/')}"
    return os.path.normpath(raw)


def _iter_storage_roots() -> list:
    if sys.platform == "win32":
        import string as _string
        roots = []
        for letter in _string.ascii_uppercase:
            if letter in ("A", "B"):
                continue
            drive = f"{letter}:\\"
            if letter == "C":
                continue  # 已被 ROM_SEARCH_ROOTS ~/ 覆盖
            if os.path.isdir(drive):
                roots.append(drive)
        return roots

    if sys.platform == "darwin":
        roots = []
        volumes = "/Volumes"
        if os.path.isdir(volumes):
            try:
                for entry in sorted(os.listdir(volumes)):
                    if entry.startswith(".") or entry == "Macintosh HD":
                        continue
                    full = os.path.join(volumes, entry)
                    if os.path.isdir(full) and os.access(full, os.R_OK):
                        roots.append(full)
            except PermissionError:
                pass
        return roots

    # Android / Linux
    roots = ["/storage/emulated/0", "/sdcard"]
    storage = "/storage"
    try:
        for entry in sorted(os.listdir(storage)):
            if entry in {"self", "emulated"} or entry.startswith("."):
                continue
            full = os.path.join(storage, entry)
            if os.path.isdir(full) and os.access(full, os.R_OK):
                roots.append(full)
    except PermissionError:
        pass
    except Exception:
        pass
    # 去重 (follow symlinks)
    seen = set()
    unique = []
    for root in roots:
        try:
            real = os.path.realpath(root)
        except Exception:
            real = root
        if real not in seen:
            seen.add(real)
            unique.append(root)
    return unique


_COUNT_ERRORS = []  # 全局，供 UI 展示

_AMBIGUOUS_EXTS = {".bin", ".cue", ".zip", ".7z"}

def _is_ambiguous_ext(filename: str) -> bool:
    """歧义扩展名：不一定是 ROM 文件，需结合目录名判断"""
    return filename.lower().endswith(tuple(_AMBIGUOUS_EXTS))

def _is_rom_dir(path: str) -> bool:
    """判断目录名是否匹配已知 ROM 平台，用于歧义扩展名过滤"""
    basename = os.path.basename(path).lower().replace(" ", "").replace("-", "").replace("_", "")
    return any(k in basename for k in SYSTEMS)

def _count_roms(path: str) -> int:
    """统计目录下 ROM 文件数量（仅一级，不递归）。使用 scandir 减少 stat 调用。"""
    try:
        count = 0
        for entry in os.scandir(path):
            if not entry.is_file():
                continue
            if entry.name.lower().endswith(tuple(ROM_EXTS)):
                # 对歧义扩展名做额外过滤：目录名不在 SYSTEMS 映射中则跳过
                if _is_ambiguous_ext(entry.name) and not _is_rom_dir(path):
                    continue
                count += 1
        return count
    except PermissionError:
        _COUNT_ERRORS.append(f"无权限: {path}")
        return 0
    except FileNotFoundError:
        return 0
    except NotADirectoryError:
        return 0
    except Exception as ex:
        _COUNT_ERRORS.append(f"{path}: {ex}")
        return 0

def _scan_parent(parent: str, depth: int = 2) -> list:
    """递归扫描目录树，寻找含 ROM 的目录。使用 scandir 减少 stat 调用。"""
    results = []
    parent = _normalize_android_path(parent)
    if depth <= 0:
        return results
    try:
        with os.scandir(parent) as entries:
            for entry in sorted(entries, key=lambda e: e.name):
                if entry.name.startswith("."):
                    continue
                if not entry.is_dir():
                    continue
                if entry.name in SKIP_DIRS or entry.name.startswith(SKIP_PREFIXES):
                    continue
                n = _count_roms(entry.path)
                if n >= 1:
                    results.append((f"{_sys(entry.name)}  ({n} ROM)", entry.path))
                if depth > 1:
                    results.extend(_scan_parent(entry.path, depth - 1))
    except PermissionError:
        _COUNT_ERRORS.append(f"无权限扫描: {parent}")
    except FileNotFoundError:
        pass
    except OSError:
        pass
    return results

def _scan_root(root: str, depth: int = 2) -> list:
    """扫描单个根目录，返回 (label, path) 列表。"""
    results = []
    root = _normalize_android_path(root)
    if not os.path.isdir(root):
        return results
    try:
        n = _count_roms(root)
        if n >= 1:
            results.append((f"{_sys(os.path.basename(root))}  ({n} ROM)", root))
        results.extend(_scan_parent(root, depth=depth))
    except (PermissionError, FileNotFoundError, OSError):
        pass
    return results


def _list_dir(path: str) -> tuple[list, list]:
    """列出某个目录的当前层级内容（文件浏览器用）。

    返回 (folders, roms):
        folders: [(name, full_path, rom_count), ...]  子文件夹 + ROM 数量
        roms:    [(name, full_path), ...]             当前目录的 ROM 文件
    即时读取，不做递归扫描。
    """
    path = _normalize_android_path(path)
    folders = []
    roms = []
    try:
        with os.scandir(path) as entries:
            for entry in sorted(entries, key=lambda e: e.name.lower()):
                if entry.name.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in SKIP_DIRS or entry.name.startswith(SKIP_PREFIXES):
                        continue
                    n = _count_roms(entry.path)
                    folders.append((entry.name, entry.path, n))
                elif entry.is_file(follow_symlinks=False):
                    if entry.name.lower().endswith(tuple(ROM_EXTS)):
                        # 歧义扩展名过滤：若目录名不匹配系统，则不显示该文件
                        if _is_ambiguous_ext(entry.name) and not _is_rom_dir(path):
                            continue
                        roms.append((entry.name, entry.path))
    except (PermissionError, FileNotFoundError, NotADirectoryError, OSError):
        pass
    return folders, roms


def _read_dir_scrape_info(dir_path: str) -> list:
    """读取某目录下 gamelist.xml，返回已刮削 ROM 的元数据列表。

    每项: {name, desc, image_path, rating, developer, publisher,
           genre, players, release_date, path, rom_name}
    image_path 为绝对路径（用于 UI 显示封面），缺失字段为空字符串。
    """
    from modules.xml_builder import load_existing_gamelist
    gp = Path(dir_path) / "gamelist.xml"
    _, index = load_existing_gamelist(gp)
    result = []
    for rel, game_elem in index.items():
        # rel 形如 "./xxx.gba"，提取 ROM 文件名
        rom_name = os.path.basename(rel.lstrip("./").lstrip(".\\"))

        def _get(tag):
            el = game_elem.find(tag)
            return el.text.strip() if el is not None and el.text else ""

        # 封面相对路径 → 绝对路径
        img_rel = _get("image")
        img_abs = ""
        if img_rel:
            # img_rel 形如 "./downloaded_media/covers/xxx.png"
            cleaned = img_rel.lstrip("./").lstrip(".\\").replace("\\", "/")
            candidate = Path(dir_path) / cleaned
            img_abs = str(candidate) if candidate.exists() else ""

        result.append({
            "rom_name": rom_name,
            "name": _get("name"),
            "desc": _get("desc"),
            "image_path": img_abs,
            "rating": _get("rating"),
            "developer": _get("developer"),
            "publisher": _get("publisher"),
            "genre": _get("genre"),
            "players": _get("players"),
            "release_date": _get("releasedate"),
            "path": rel,
        })
    return result


def _default_start_dir() -> str:
    """决定首页浏览器默认起始目录：优先上次位置 → 首个存在的 ROM_ROOTS → 家目录。"""
    if state.last_dir and os.path.isdir(state.last_dir):
        return state.last_dir
    for root in ROM_ROOTS:
        if os.path.isdir(root):
            return root
    home = os.path.expanduser("~")
    return home if os.path.isdir(home) else "/"


def detect_dirs(on_found=None, on_progress=None):
    """检测 ROM 目录。on_found/on_progress 可选回调用于增量通知。返回 (dirs, errors)。"""
    global _COUNT_ERRORS
    _COUNT_ERRORS = []
    found = []
    errors = []
    seen = set()

    def _add(label, path):
        if path in seen:
            return
        seen.add(path)
        found.append((label, path))
        if on_found:
            on_found(label, path)

    def _report(msg):
        if on_progress:
            on_progress(msg)

    # 1) 预设路径 — 快速扫描
    for root in ROM_ROOTS:
        _report(f"扫描 {os.path.basename(root) or root[:20]}...")
        for label, path in _scan_root(root, 2):
            _add(label, path)

    # 2) 全盘扫描 — 发现玩家自建目录
    for search_root in ROM_SEARCH_ROOTS + _iter_storage_roots():
        short = os.path.basename(search_root) or search_root.replace("/storage/", "")[:20]
        _report(f"扫描 {short}...")
        for label, path in _scan_root(search_root, 2):
            _add(label, path)

    errors.extend(_COUNT_ERRORS)
    return found, errors

def scan_roms(path):
    path = _normalize_android_path(path)
    if not path:
        return []
    try:
        result = []
        for entry in os.scandir(path):
            if entry.is_file() and entry.name.lower().endswith(tuple(ROM_EXTS)):
                result.append(entry.name)
        result.sort()
        return result
    except:
        return []

def _is_chinese(text: str) -> bool:
    """True if text has CJK characters but no Japanese kana (hiragana/katakana)."""
    if not text:
        return False
    if any('぀' <= c <= 'ゟ' or '゠' <= c <= 'ヿ' for c in text):
        return False
    return any('一' <= c <= '鿿' for c in text)


def _has_cjk(text: str) -> bool:
    """True if text contains any CJK character (汉字/日文假名/韩文谚文)。"""
    if not text:
        return False
    for c in text:
        # CJK 统一表意文字、平假名、片假名、谚文、CJK 扩展等
        if ('\u3040' <= c <= '\u30ff'      # 平假名 + 片假名
                or '\uac00' <= c <= '\ud7af'  # 韩文谚文
                or '\u4e00' <= c <= '\u9fff'  # CJK 统一汉字
                or '\u3400' <= c <= '\u4dbf'):  # CJK 扩展 A
            return True
    return False


def _clean_en_stem(filename: str) -> str:
    """对英文 ROM 文件名做轻量清洗，得到干净的游戏名。

    去扩展名、去括号内容（区域/版本/汉化组标签）、下划线/点转空格、压缩空格。
    例如 'Super_Mario_World_(USA)_(Rev_1).sfc' → 'Super Mario World'
    """
    import re
    stem = Path(filename).stem
    # 去括号内容（含中文/英文括号）— 区域/版本标签都在括号里
    stem = re.sub(r'[\(（][^\)）]*[\)）]', ' ', stem)
    # 去方括号内容（汉化组/标签常在方括号里）
    stem = re.sub(r'\[[^\]]*\]', ' ', stem)
    # 下划线、点、连字符转空格
    stem = re.sub(r'[_\.\-]+', ' ', stem)
    # 压缩空格
    stem = re.sub(r'\s+', ' ', stem).strip()
    return stem

def _slug(s):
    k = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-"
    return "".join(c if c in k else "_" for c in s)[:80]

def _best_slug(*candidates):
    """Return the first candidate whose slug contains at least one alphanumeric character."""
    for s in candidates:
        if not s:
            continue
        slug = _slug(s)
        if any(c.isalnum() for c in slug):
            return slug
    return _slug(candidates[-1]) if candidates else "unknown"

# ======================================================================
# Flet App
# ======================================================================

def _config_dir() -> str:
    """返回配置文件应存放的目录（遵循各平台规范）。

    - 打包后优先使用 FLET_APP_STORAGE_DATA
    - macOS: ~/Library/Application Support/iiSU-CN-Scraper
    - Windows: %APPDATA%/iiSU-CN-Scraper
    - Android / Linux: ~
    """
    d = os.environ.get("FLET_APP_STORAGE_DATA", "")
    if d:
        os.makedirs(d, exist_ok=True)
        return d
    home = Path.home()
    if sys.platform == "darwin":
        d = home / "Library" / "Application Support" / "iiSU-CN-Scraper"
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA", str(home))
        d = Path(base) / "iiSU-CN-Scraper"
    else:
        d = home
    try:
        os.makedirs(str(d), exist_ok=True)
        return str(d)
    except Exception:
        return str(home) if str(home) not in ("", "/") else os.path.dirname(os.path.abspath(__file__))

CONFIG_FILE = os.path.join(_config_dir(), "iisusc_config.json")

class AppState:
    """全局状态 + 配置持久化"""
    def __init__(self):
        self.rom_dir = ""
        self.rom_dirs = []    # 批量刮削
        self.llm_base_url = "https://api.deepseek.com/v1"
        self.llm_api_key = ""
        self.llm_model = "deepseek-chat"
        self.tgdb_api_key = ""   # TGDB API Key (可选备用)
        self.last_dir = ""       # 上次浏览的目录（文件浏览器记住位置）
        self.scrape_single = ""  # 临时标记：仅刮削单个 ROM 文件（一次性）
        self.force_tgdb = False  # 单文件刮削时强制使用 TheGamesDB
        self.load()

    def save(self):
        data = {
            "llm_base_url": self.llm_base_url,
            "llm_api_key": self.llm_api_key,
            "llm_model": self.llm_model,
            "tgdb_api_key": self.tgdb_api_key,
            "last_dir": self.last_dir,
            "force_tgdb": self.force_tgdb,
        }
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def load(self):
        if not os.path.exists(CONFIG_FILE): return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            if not content.strip():
                return
            data = json.loads(content)
            self.llm_base_url = data.get("llm_base_url", self.llm_base_url)
            self.llm_api_key = data.get("llm_api_key", "")
            self.llm_model = data.get("llm_model", self.llm_model)
            self.tgdb_api_key = data.get("tgdb_api_key", "")
            self.last_dir = data.get("last_dir", "")
            self.force_tgdb = data.get("force_tgdb", False)
        except (json.JSONDecodeError, Exception):
            bak = CONFIG_FILE + ".bak"
            try: os.rename(CONFIG_FILE, bak)
            except: pass

state = AppState()


def _has_storage_permission() -> bool:
    """Test if storage is readable."""
    if sys.platform in ("win32", "darwin"):
        return True
    for p in ["/storage/emulated/0", "/sdcard"]:
        try:
            os.listdir(p)
            return True
        except Exception:
            continue
    return False


def _check_storage_permission_on_startup(page: ft.Page):
    """启动时检测存储权限，无权限则弹窗引导用户去系统设置开启。"""
    if _has_storage_permission():
        return

    def _close_permission_dlg(e=None):
        page.pop_dialog()

    def open_settings(e):
        _close_permission_dlg()
        _open_all_files_access()
        # 注册回扫：用户从设置返回后自动重扫
        if _rescan_fn[0]:
            _rescan_fn[0](None)

    dlg = ft.AlertDialog(
        title=ft.Text("需要存储权限", color=TEXT),
        content=ft.Text(
            "检测 ROM 和写入 gamelist.xml 需要「所有文件访问」权限。\n\n"
            "点击「去设置」→ 找到 iiSU CN Scraper → 开启允许管理所有文件 → 返回即可。",
            color=TEXT_DIM, size=13,
        ),
        actions=[
            ft.TextButton("稍后", on_click=_close_permission_dlg,
                          style=ft.ButtonStyle(color=TEXT_DIM)),
            ft.TextButton("去设置", on_click=open_settings, style=ft.ButtonStyle(color=ACCENT)),
        ],
        bgcolor=SURFACE,
    )
    page.show_dialog(dlg)


_rescan_fn = [None]
_home_reset_fn = [None]  # 从刮削页返回首页时恢复 UI

_last_scan_dirs = []  # 设置页检测结果缓存（切片赋值引用）

def main(page: ft.Page):
    # 启动即检查存储权限，无权限弹窗引导
    _check_storage_permission_on_startup(page)

    def on_lifecycle(e):
        """从权限设置页或 SAF 目录选择器返回时自动重扫。"""
        if e.data in ("resume", "show") and _rescan_fn[0]:
            page.run_task(_rescan_fn[0], None)

    page.on_app_lifecycle_state_change = on_lifecycle
    page.title = "iiSU CN Scraper"
    page.theme_mode = ft.ThemeMode.DARK
    page.dark_theme = ft.Theme(
        color_scheme_seed=ACCENT,
        scaffold_bgcolor=BG,
    )
    page.padding = 0

    # ---- FilePicker 服务 (桌面端文件夹选择，替代 tkinter) ----
    # Flet 0.85: FilePicker 是 Service，挂到 page.services 后用 async get_directory_path()
    file_picker = ft.FilePicker()
    page.services.append(file_picker)

    # ---- 桌面端窗口尺寸 ----
    # 移动端不设固定尺寸；桌面端给一个合理默认窗口并居中
    if sys.platform in ("win32", "darwin"):
        try:
            page.window.width = 920
            page.window.height = 680
            page.window.min_width = 720
            page.window.min_height = 560
            page.window.center()
        except Exception:
            pass

    # ---- 导航 (防止重复页面) ----
    def navigate(view):
        """推入新页面，如果当前已是同类型则跳过"""
        route = view.route
        if page.views and page.views[-1].route == route:
            return  # 已在目标页，不重复
        page.views.append(view)
        page.update()

    def go_home(e=None):
        page.views.clear()
        page.views.append(build_home())
        page.update()

    def go_settings(e=None):
        navigate(build_settings())

    def go_scrape(e=None):
        _rescan_fn[0] = None
        # 先移除旧 scrape 页（如果有），确保 build_scrape 读到最新的 state
        page.views = [v for v in page.views if v.route != "/scrape"]
        page.views.append(build_scrape())
        page.update()

    def pop_view(e=None):
        if len(page.views) > 1:
            page.views.pop()
            page.update()
        # 回到首页时刷新当前目录（反映刮削后的新数据）
        if page.views and page.views[-1].route == "/":
            if _home_reset_fn[0]:
                _home_reset_fn[0]()

    # ================================================================
    # 首页
    # ================================================================
    def build_home():
        """首页 — 文件浏览器（双栏）。左栏浏览目录/ROM，右栏显示目录概览或ROM详情。"""
        import xml.etree.ElementTree as _ET

        # ---- 浏览器状态 ----
        browser = {
            "dir": _default_start_dir(),       # 当前目录
            "selected_rom": None,              # 选中的 ROM (name, path) 或 None
            "checks": {},                      # {rom_path: Checkbox} 多选刮削
        }

        # ---- 左栏组件 ----
        path_bar = ft.Text(size=13, color=TEXT, weight=ft.FontWeight.BOLD,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        left_list = ft.ListView(spacing=4, expand=True, padding=ft.Padding(left=4, right=4, top=4))
        select_all_cb = ft.Checkbox(value=False, fill_color=ACCENT, on_change=lambda e: _toggle_all(e))
        sel_count_text = ft.Text("已选 0", size=12, color=TEXT_DIM)
        scrape_sel_btn = ft.Button("刮削选中",
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT, shape=ft.RoundedRectangleBorder(radius=8)),
            disabled=True, on_click=lambda e: _scrape_selected())
        scrape_dir_btn = ft.ElevatedButton("刮削此目录",
            style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT, shape=ft.RoundedRectangleBorder(radius=8)),
            on_click=lambda e: _scrape_current_dir())

        # ---- 右栏组件 ----
        right_panel = ft.ListView(spacing=10, expand=True, padding=ft.Padding(left=12, right=12, top=12, bottom=12))

        # ================================================================
        # 刷新左栏（进入新目录 / 重选 ROM 时调用）
        # ================================================================
        def _refresh_left():
            d = browser["dir"]
            browser["selected_rom"] = None
            browser["checks"].clear()
            path_bar.value = d if len(d) <= 55 else "..." + d[-52:]

            controls = []

            # 工具行：返回上级 / 主目录
            parent = os.path.dirname(d)
            if parent and parent != d:  # 不是根
                controls.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.ARROW_UPWARD, color=ACCENT, size=16),
                        ft.Text("返回上级", size=13, color=TEXT_DIM),
                    ], spacing=6),
                    bgcolor=SURFACE, border_radius=8,
                    padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                    ink=True, on_click=lambda e: _enter(parent),
                ))

            folders, roms = _list_dir(d)

            # 子文件夹
            for name, fpath, n_rom in folders:
                badge = (ft.Container(
                    content=ft.Text(f"{n_rom}", size=10, color=TEXT, weight=ft.FontWeight.BOLD),
                    bgcolor=ACCENT if n_rom > 0 else SURFACE,
                    border_radius=8,
                    padding=ft.Padding(left=7, right=7, top=2, bottom=2),
                ) if n_rom > 0 else
                ft.Container(
                    content=ft.Text(f"{n_rom}", size=10, color=TEXT_DIM),
                    border=ft.Border(left=ft.BorderSide(1, "#3a3a4a"), right=ft.BorderSide(1, "#3a3a4a"), top=ft.BorderSide(1, "#3a3a4a"), bottom=ft.BorderSide(1, "#3a3a4a")),
                    border_radius=8,
                    padding=ft.Padding(left=7, right=7, top=2, bottom=2),
                ))
                controls.append(ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FOLDER, color=ACCENT, size=18),
                        ft.Text(name, size=13, color=TEXT, expand=True,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        badge,
                    ], spacing=8),
                    bgcolor=SURFACE, border_radius=10,
                    padding=ft.Padding(left=12, right=12, top=9, bottom=9),
                    ink=True, on_click=lambda e, p=fpath: _enter(p),
                ))

            # ROM 文件
            if roms:
                controls.append(ft.Container(height=2))
                for name, rpath in roms:
                    cb = ft.Checkbox(value=False, fill_color=ACCENT,
                                     on_change=lambda e: _on_check_change())
                    browser["checks"][rpath] = cb
                    controls.append(ft.Container(
                        content=ft.Row([
                            ft.Icon(ft.Icons.VIDEOGAME_ASSET, color=TEXT_DIM, size=18),
                            ft.Text(name, size=13, color=TEXT, expand=True,
                                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            cb,
                        ], spacing=8),
                        bgcolor=SURFACE, border_radius=10,
                        padding=ft.Padding(left=12, right=12, top=9, bottom=9),
                        ink=True, on_click=lambda e, p=rpath, n=name: _select_rom(n, p),
                    ))

            if not folders and not roms:
                controls.append(ft.Container(
                    content=ft.Text("（空目录）", size=13, color=TEXT_DIM,
                                    text_align=ft.TextAlign.CENTER),
                    padding=20,
                ))

            left_list.controls = controls

            # 重置底部状态
            select_all_cb.value = False
            _update_sel_count()
            _refresh_right()
            try:
                page.update()
            except Exception:
                pass

        # ================================================================
        # 刷新右栏（目录概览 或 ROM 详情）
        # ================================================================
        def _refresh_right():
            # 若选中了 ROM → 显示该 ROM 详情；否则显示当前目录概览
            sel = browser["selected_rom"]
            if sel:
                _render_rom_detail(sel[0], sel[1])
            else:
                _render_dir_overview()

        def _render_dir_overview():
            d = browser["dir"]
            folders, roms = _list_dir(d)
            scraped = _read_dir_scrape_info(d)
            total = len(roms)

            controls = [
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN, color=ACCENT, size=18),
                    ft.Text("目录概览", size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                ], spacing=8),
                ft.Container(
                    content=ft.Text(
                        f"ROM 文件: {total}    已刮削: {len(scraped)}",
                        size=13, color=TEXT_DIM),
                    bgcolor=SURFACE, border_radius=8,
                    padding=ft.Padding(left=12, right=12, top=8, bottom=8),
                ),
            ]

            if not scraped:
                controls.append(ft.Container(
                    content=ft.Text(
                        "尚无刮削记录\n\n点击左下角「刮削此目录」开始" if total else "此目录无 ROM 文件",
                        size=13, color=TEXT_DIM, text_align=ft.TextAlign.CENTER),
                    padding=30,
                ))
            else:
                controls.append(ft.Text(f"已刮削游戏 ({len(scraped)})",
                                        size=12, color=TEXT_DIM, weight=ft.FontWeight.BOLD))
                for item in scraped:
                    controls.append(_build_scraped_card(item))

            right_panel.controls = controls

        def _build_scraped_card(item):
            """单条已刮削记录的卡片（封面 + 名称 + 评分）。"""
            # 封面
            cover = ft.Container(
                content=ft.Image(src=item["image_path"], fit=ft.BoxFit.CONTAIN)
                        if item["image_path"] else
                        ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED, color=TEXT_DIM, size=32),
                width=56, height=56, bgcolor=SURFACE,
                border_radius=6, alignment=ft.alignment.Alignment(0, 0),
            )
            # 信息列
            name = item["name"] or item["rom_name"]
            rating = f"⭐ {item['rating']}" if item["rating"] else ""
            date = (item["release_date"][:4] + "年") if len(item["release_date"]) >= 4 else ""
            sub_parts = [p for p in (date, item["developer"], rating) if p]
            sub = " · ".join(sub_parts) if sub_parts else item["rom_name"]
            return ft.Container(
                content=ft.Row([cover, ft.Column([
                    ft.Text(name, size=13, color=TEXT, weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(sub, size=11, color=TEXT_DIM, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                ], spacing=2, expand=True)], spacing=10),
                bgcolor=SURFACE, border_radius=8,
                padding=ft.Padding(left=10, right=10, top=8, bottom=8),
            )

        def _build_rom_detail_controls(name, rpath):
            """构建单个 ROM 的完整元数据详情控件列表（供右栏或窄屏弹窗复用）。"""
            d = browser["dir"]
            scraped = _read_dir_scrape_info(d)
            rel = "./" + name
            # 从 gamelist 找该 ROM 的元数据
            info = next((x for x in scraped if x["path"] == rel or x["rom_name"] == name), None)

            controls = [
                ft.Row([
                    ft.Icon(ft.Icons.VIDEOGAME_ASSET, color=ACCENT, size=18),
                    ft.Text(name, size=14, weight=ft.FontWeight.BOLD, color=TEXT,
                            max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ], spacing=8),
            ]

            if not info:
                # 未刮削
                controls.append(ft.Container(
                    content=ft.Column([
                        ft.Icon(ft.Icons.HELP_OUTLINE, color=TEXT_DIM, size=40),
                        ft.Text("尚未刮削", size=13, color=TEXT_DIM, text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8),
                    padding=30,
                ))
                controls.append(ft.ElevatedButton("刮削这一个",
                    icon=ft.Icons.PLAY_ARROW,
                    style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT),
                    on_click=lambda e: _scrape_one(rpath)))
            else:
                # 封面大图
                if info["image_path"]:
                    controls.append(ft.Container(
                        content=ft.Image(src=info["image_path"], fit=ft.BoxFit.CONTAIN,
                                         border_radius=8),
                        width=140, height=140, bgcolor=SURFACE,
                        border_radius=8, alignment=ft.alignment.Alignment(0, 0),
                    ))
                # 元数据字段
                name_disp = info["name"] or name
                controls.append(ft.Text(name_disp, size=16, weight=ft.FontWeight.BOLD, color=TEXT))
                fields = [
                    ("评分", info["rating"] or "—"),
                    ("发售", _fmt_date(info["release_date"])),
                    ("开发", info["developer"] or "—"),
                    ("发行", info["publisher"] or "—"),
                    ("类型", info["genre"] or "—"),
                    ("人数", info["players"] or "—"),
                ]
                grid = ft.Column(spacing=4)
                for label, val in fields:
                    grid.controls.append(ft.Row([
                        ft.Text(label, size=12, color=TEXT_DIM, width=40),
                        ft.Text(val, size=12, color=TEXT, expand=True,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=8))
                controls.append(grid)
                # 简介
                if info["desc"]:
                    controls.append(ft.Container(
                        content=ft.Column([
                            ft.Text("简介", size=12, color=TEXT_DIM, weight=ft.FontWeight.BOLD),
                            ft.Text(info["desc"], size=12, color=TEXT,
                                    max_lines=8, overflow=ft.TextOverflow.ELLIPSIS),
                        ], spacing=4),
                        bgcolor=SURFACE, border_radius=8,
                        padding=ft.Padding(left=10, right=10, top=10, bottom=10),
                    ))
                # 重新刮削按钮
                controls.append(ft.ElevatedButton("重新刮削",
                    icon=ft.Icons.REFRESH,
                    style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT),
                    on_click=lambda e: _scrape_one(rpath)))

            return controls

        def _render_rom_detail(name, rpath):
            """宽屏：刷新右栏为单个 ROM 详情。"""
            right_panel.controls = _build_rom_detail_controls(name, rpath)

        def _show_rom_sheet(name, rpath):
            """窄屏：用底部弹窗显示 ROM 详情。"""
            controls = _build_rom_detail_controls(name, rpath)
            sheet = ft.BottomSheet(
                content=ft.Container(
                    content=ft.Column(controls, scroll=ft.ScrollMode.AUTO),
                    bgcolor=SURFACE,
                    padding=ft.Padding(left=16, right=16, top=8, bottom=24),
                ),
                show_drag_handle=True,
                dismissible=True,
            )
            page.overlay.append(sheet)
            sheet.open = True
            page.update()

        def _fmt_date(d):
            """YYYYMMDDTHHMMSS → YYYY-MM-DD，或原样返回。"""
            if not d:
                return "—"
            d = d.strip()
            if len(d) >= 8 and d[:8].isdigit():
                return f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
            return d[:10] if d else "—"

        # ================================================================
        # 交互回调
        # ================================================================
        def _enter(path):
            """进入某目录。"""
            path = _normalize_android_path(path)
            if not os.path.isdir(path):
                return
            browser["dir"] = path
            state.last_dir = path
            state.save()
            _refresh_left()

        def _select_rom(name, rpath):
            """点击某个 ROM → 选中并显示详情。窄屏用弹窗，宽屏刷新右栏。"""
            browser["selected_rom"] = (name, rpath)
            if is_narrow["value"]:
                _show_rom_sheet(name, rpath)
            else:
                _refresh_right()
            try:
                page.update()
            except Exception:
                pass

        def _on_check_change():
            _update_sel_count()
            try:
                page.update()
            except Exception:
                pass

        def _toggle_all(e):
            val = select_all_cb.value
            for cb in browser["checks"].values():
                cb.value = val
            _update_sel_count()
            try:
                page.update()
            except Exception:
                pass

        def _update_sel_count():
            n = sum(1 for cb in browser["checks"].values() if cb.value)
            sel_count_text.value = f"已选 {n}"
            scrape_sel_btn.disabled = (n == 0)
            scrape_sel_btn.text = f"刮削选中 ({n})" if n else "刮削选中"

        def _scrape_selected():
            """刮削勾选的 ROM。"""
            selected = [p for p, cb in browser["checks"].items() if cb.value]
            if not selected:
                return
            state.rom_dirs = list(selected)
            state.rom_dir = browser["dir"]
            go_scrape()

        def _scrape_current_dir():
            """刮削当前目录的所有 ROM。"""
            state.rom_dir = browser["dir"]
            state.rom_dirs = [browser["dir"]]
            go_scrape()

        def _scrape_one(rpath):
            """刮削单个 ROM 文件（通过 state.scrape_single 标记，刮削页会过滤）。"""
            state.rom_dir = browser["dir"]
            state.rom_dirs = [browser["dir"]]
            state.scrape_single = rpath
            go_scrape()

        # 桌面端：浏览文件夹按钮（FilePicker）
        def _browse(e):
            if sys.platform not in ("win32", "darwin"):
                return
            async def _pick():
                try:
                    path = await file_picker.get_directory_path(dialog_title="选择目录")
                except Exception:
                    path = None
                if path:
                    _enter(os.path.normpath(path))
            page.run_task(_pick)

        browse_btn = ft.IconButton(
            ft.Icons.FOLDER_OPEN, icon_color=ACCENT,
            tooltip="浏览文件夹", on_click=_browse)

        # 从刮削页返回时恢复（重新刷新当前目录以反映新刮削的数据）
        def _reset_home():
            _refresh_left()
        _home_reset_fn[0] = _reset_home

        # 初始填充
        _refresh_left()

        # ================================================================
        # 布局
        # ================================================================
        left_panel = ft.Column([
            # 路径栏 + 操作按钮
            ft.Container(
                content=ft.Row([
                    ft.IconButton(ft.Icons.HOME, icon_color=ACCENT, icon_size=20,
                                  tooltip="主目录", on_click=lambda e: _enter(_default_start_dir())),
                    path_bar,
                    browse_btn,
                ], spacing=4),
                bgcolor=CARD_BG, border_radius=10,
                padding=ft.Padding(left=8, right=8, top=4, bottom=4),
            ),
            # 目录/文件列表
            ft.Container(content=left_list, expand=True, bgcolor=CARD_BG, border_radius=10),
            # 底部操作栏
            ft.Container(
                content=ft.Row([
                    select_all_cb,
                    sel_count_text,
                    ft.Container(expand=True),
                    scrape_sel_btn,
                    scrape_dir_btn,
                ], spacing=8),
                bgcolor=CARD_BG, border_radius=10,
                padding=ft.Padding(left=12, right=12, top=8, bottom=8),
            ),
        ], spacing=8, expand=True)

        right_container = ft.Container(
            content=right_panel,
            bgcolor=CARD_BG, border_radius=10, expand=True,
        )

        # ================================================================
        # 响应式：宽屏左右双栏；窄屏（移动端）只显示左栏，ROM 详情用底部弹窗
        # ================================================================
        is_narrow = {"value": False}
        main_container = ft.Container(expand=True, padding=ft.Padding(left=12, right=12, top=8, bottom=8))

        def _apply_layout():
            try:
                w = page.width or 800
            except Exception:
                w = 800
            narrow = w < 700
            changed = narrow != is_narrow["value"]
            is_narrow["value"] = narrow
            if narrow:
                main_container.content = left_panel
            else:
                main_container.content = ft.Row([left_panel, right_container], spacing=8, expand=True)
            if changed:
                # 布局模式切换时刷新右栏（回到宽屏补全右栏内容）
                _refresh_right()
            return changed

        def _on_resize(e):
            if _apply_layout():
                try:
                    page.update()
                except Exception:
                    pass

        page.on_resize = _on_resize
        _apply_layout()

        return ft.View(
            route="/",
            bgcolor=BG,
            appbar=ft.AppBar(
                title=ft.Text("iiSU CN Scraper", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                bgcolor=BG,
                actions=[
                    ft.IconButton(ft.Icons.SETTINGS, icon_color=ACCENT,
                                  on_click=lambda _: go_settings()),
                ],
            ),
            controls=[main_container],
        )

    # ================================================================
    # 设置页
    # ================================================================
    def build_settings():
        field_style = dict(
            bgcolor=SURFACE, border_color="#2a2a3a", color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM, size=13),
            content_padding=12, border_radius=8,
        )
        llm_url = ft.TextField(label="API 地址", value=state.llm_base_url, **field_style)
        llm_key = ft.TextField(label="API Key", value=state.llm_api_key, password=True, **field_style)
        llm_model = ft.TextField(label="模型名称", value=state.llm_model, **field_style)
        tgdb_key = ft.TextField(label="API Key", value=state.tgdb_api_key, **field_style)
        force_tgdb_switch = ft.Switch(
            label="单文件刮削时强制使用 TheGamesDB",
            value=state.force_tgdb, active_color=ACCENT,
        )
        dir_list = ft.Column(spacing=3)
        picked_path = ft.Text("", size=13, color=TEXT)
        manual_path = ft.TextField(
            label="手动输入 ROM 路径",
            hint_text="例如 /storage/emulated/0/ROMs/GBA 或 primary:ROMs/GBA",
            **field_style,
        )
        scrape_from_settings_btn = ft.Button("开始刮削此目录",
            style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT, shape=ft.RoundedRectangleBorder(radius=10)),
            visible=False)
        selected_box = ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.CHECK_CIRCLE, color=ACCENT, size=16),
                    ft.Text("已选择目录", size=11, color=TEXT_DIM),
                ], spacing=4),
                ft.Container(content=picked_path, bgcolor=CARD_BG, border_radius=6, padding=8),
                scrape_from_settings_btn,
            ], spacing=8),
            bgcolor=SURFACE, border_radius=10, padding=12,
            visible=False,
        )

        def apply_manual_path(e):
            path = _normalize_android_path(manual_path.value)
            if not path:
                picked_path.value = "请输入路径"
                page.update()
                return
            try:
                os.listdir(path)
                _set(path)
            except PermissionError:
                picked_path.value = "无读取权限，正在打开系统权限设置..."
                _auto_grant_storage()
                page.update()
            except (FileNotFoundError, NotADirectoryError):
                picked_path.value = "路径不存在，请检查拼写"
                page.update()
            except Exception as ex:
                picked_path.value = f"无法访问: {ex}"
                page.update()

        def do_detect(e):
            _rescan_fn[0] = do_detect  # 从权限/SAF页面返回时自动重扫
            dir_list.controls.clear()
            page.update()

            def _scan_thread():
                def _on_progress(msg):
                    dir_list.controls[-1].value = f"检测中 — {msg}" if dir_list.controls else msg
                    try: page.update()
                    except: pass

                dir_list.controls.append(ft.Text("检测中...", size=12, color=TEXT_DIM))
                try: page.update()
                except: pass

                try:
                    dirs, errors = detect_dirs(on_progress=_on_progress)
                    _last_scan_dirs[:] = dirs
                except Exception as ex:
                    dirs, errors = [], [str(ex)]

                # 原子替换，避免 clear() 中间态闪烁
                new_controls = []
                if errors:
                    for err in errors[:3]:
                        new_controls.append(
                            ft.Text(f"\u26a0 {err}", size=12, color="#ff9f43"))
                if not dirs:
                    new_controls.append(
                        ft.Text("未检测到 ROM 目录", size=12, color=TEXT_DIM) if not errors else
                        ft.Text("无存储权限 \u2192 请到系统设置 \u2192 应用 \u2192 iiSU CN Scraper \u2192 所有文件访问权限", size=12, color="#ff9f43"))
                else:
                    for label, path in dirs:
                        short = path if len(path) <= 55 else "..." + path[-52:]
                        new_controls.append(
                            ft.TextButton(
                                content=ft.Column([
                                    ft.Text(label, size=13, color=TEXT, weight=ft.FontWeight.BOLD),
                                    ft.Text(short, size=10, color=TEXT_DIM),
                                ], spacing=1, alignment=ft.CrossAxisAlignment.START),
                                style=ft.ButtonStyle(
                                    bgcolor=SURFACE, shape=ft.RoundedRectangleBorder(radius=8),
                                    padding=ft.Padding(left=10, top=8, right=10, bottom=8),
                                ),
                                on_click=lambda e, p=path: _set(p),
                            )
                        )
                dir_list.controls = new_controls
                page.update()

            page.run_thread(_scan_thread)

        def _set(path):
            path = _normalize_android_path(path)
            state.rom_dir = path
            manual_path.value = path
            picked_path.value = path
            scrape_from_settings_btn.visible = True
            selected_box.visible = True
            page.update()

        def go_scrape_from_settings(e):
            if state.rom_dir:
                state.rom_dirs = [state.rom_dir]
                save_all()
                # pop 设置页 → 移除旧 scrape 页 → 推入新 scrape 页
                if len(page.views) > 1:
                    page.views.pop()
                page.views = [v for v in page.views if v.route != "/scrape"]
                page.views.append(build_scrape())
                page.update()

        scrape_from_settings_btn.on_click = go_scrape_from_settings

        def save_all():
            state.llm_base_url = llm_url.value.strip()
            state.llm_api_key = llm_key.value.strip()
            state.llm_model = llm_model.value.strip()
            state.tgdb_api_key = tgdb_key.value.strip()
            state.force_tgdb = bool(force_tgdb_switch.value)
            state.save()

        # 带左紫条装饰的卡片
        def _card(icon, title, controls):
            return ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Icon(icon, color=ACCENT, size=18),
                        ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                    ], spacing=8),
                    ft.Container(height=2, bgcolor="#2a2a3a"),
                    ft.Container(height=4),
                    *controls,
                ], spacing=8),
                bgcolor=CARD_BG, border_radius=14, padding=18,
                border=ft.Border(
                    left=ft.BorderSide(3, ACCENT),
                    top=ft.BorderSide(0, "#00000000"),
                    right=ft.BorderSide(0, "#00000000"),
                    bottom=ft.BorderSide(0, "#00000000"),
                ),
            )

        return ft.View(
            route="/settings",
            bgcolor=BG,
            appbar=ft.AppBar(
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK_IOS_NEW, icon_color=ACCENT,
                    icon_size=20,
                    on_click=lambda _: (save_all(), pop_view()),
                ),
                title=ft.Text("设置", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                bgcolor=BG,
            ),
            controls=[
                ft.ListView(
                    expand=True,
                    spacing=20,
                    padding=ft.Padding(left=16, top=12, right=16, bottom=32),
                    controls=[
                        # ROM 目录 — 重新设计布局
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.FOLDER_OPEN, color=ACCENT, size=18),
                                    ft.Text("ROM 目录", size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                                ], spacing=8),
                                ft.Container(height=2, bgcolor="#2a2a3a"),
                                ft.Container(height=8),
                                ft.Button("自动检测", on_click=do_detect,
                                        style=ft.ButtonStyle(bgcolor=SURFACE, color=ACCENT,
                                                             shape=ft.RoundedRectangleBorder(radius=8))),
                                manual_path,
                                ft.Button("确认路径", on_click=apply_manual_path,
                                    style=ft.ButtonStyle(bgcolor=ACCENT, color=TEXT,
                                                         shape=ft.RoundedRectangleBorder(radius=8))),
                                # 检测结果列表
                                dir_list,
                                # 选中路径展示 + 刮削按钮
                                selected_box,
                            ], spacing=6),
                            bgcolor=CARD_BG, border_radius=14, padding=18,
                            border=ft.Border(
                                left=ft.BorderSide(3, ACCENT),
                                top=ft.BorderSide(0, "#00000000"),
                                right=ft.BorderSide(0, "#00000000"),
                                bottom=ft.BorderSide(0, "#00000000"),
                            ),
                        ),
                        # LLM
                        _card(ft.Icons.PSYCHOLOGY, "AI 语义清洗", [
                            llm_url, llm_key, llm_model,
                        ]),
                        # TheGamesDB (可选备用)
                        _card(ft.Icons.CLOUD_DOWNLOAD, "TheGamesDB (可选备用)", [
                            tgdb_key,
                            ft.Text("Bangumi 已免费覆盖大部分中文游戏，TGDB 作为英文补充",
                                    size=11, color=TEXT_DIM),
                            ft.Container(height=4),
                            force_tgdb_switch,
                            ft.Text("开启后，从首页单文件刮削时跳过 Bangumi 直接用 TGDB（用于 Bangumi 匹配不准时手动纠正）",
                                    size=11, color=TEXT_DIM),
                        ]),
                    ],
                ),
            ],
        )

    # ================================================================
    # 刮削页
    # ================================================================
    def build_scrape():
        # 支持批量目录。先校验路径有效性
        raw_dirs = state.rom_dirs if state.rom_dirs else [state.rom_dir]
        rom_dirs = []
        skipped_dirs = 0
        for d in raw_dirs:
            d = _normalize_android_path(d)
            if d and os.path.isdir(d):
                rom_dirs.append(d)
            else:
                skipped_dirs += 1
        all_roms = []
        for d in rom_dirs:
            for fname in scan_roms(d):
                all_roms.append((fname, os.path.join(d, fname)))
        # 单文件刮削：仅保留标记的那个 ROM（一次性）
        single = getattr(state, "scrape_single", "")
        if single:
            all_roms = [(f, p) for f, p in all_roms if p == single]
            state.scrape_single = ""  # 消费掉标记
        total = len(all_roms)
        dir_label = f"{len(rom_dirs)} 目录"
        if skipped_dirs:
            dir_label += f" (跳过 {skipped_dirs} 无效)"
        rom_count = ft.Text(f"{total} ROM ({dir_label})", size=14, color=TEXT)
        status = ft.Text("就绪", size=13, color=TEXT_DIM)
        progress = ft.ProgressBar(value=0, color=ACCENT, bgcolor=SURFACE, expand=True)
        log_list = ft.ListView(spacing=1, expand=True)
        log_controls = []  # 保持引用，用于 add_log

        def add_log(msg):
            log_controls.append(ft.Text(msg, size=11, color=TEXT_DIM))
            log_list.controls = log_controls
            try:
                page.update()
            except RuntimeError:
                pass
        start_btn = ft.Button(
            "开始刮削",
            style=ft.ButtonStyle(
                bgcolor=ACCENT, color=TEXT,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding(left=24, top=14, right=24, bottom=14),
            ),
        )

        # ROM 勾选列表 —— 卡片式
        checks = {}
        rom_cards = ft.Column(spacing=6)
        for fname, fpath in all_roms:
            cb = ft.Checkbox(value=True, fill_color=ACCENT)
            checks[fname] = cb
            card = ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.VIDEOGAME_ASSET, color=TEXT_DIM, size=18),
                    ft.Text(
                        fname, size=13, color=TEXT,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        expand=True,
                    ),
                    cb,
                ], spacing=10, alignment=ft.MainAxisAlignment.START),
                bgcolor=SURFACE, border_radius=10, padding=ft.Padding(left=14, top=10, right=8, bottom=10),
            )
            rom_cards.controls.append(card)

        # 全选/取消
        def toggle_all(e):
            all_on = all(cb.value for cb in checks.values())
            for cb in checks.values():
                cb.value = not all_on
            toggle_btn.text = "取消全选" if not all_on else "全选"
            page.update()

        toggle_btn = ft.TextButton("全选", on_click=toggle_all,
                                   style=ft.ButtonStyle(color=ACCENT))

        def do_scrape(e):
            # 从 all_roms 中取完整路径
            path_map = {fn: fp for fn, fp in all_roms}
            selected = [path_map[f] for f, cb in checks.items() if cb.value and f in path_map]
            if not selected:
                status.value = "未选中 ROM"
                page.update(); return

            # 检查 API 配置
            missing = []
            if not state.llm_api_key: missing.append("LLM API Key")
            if missing:
                status.value = f"请在设置中填入: {', '.join(missing)}"
                add_log("API 密钥未配置，无法刮削")
                page.update()
                return

            start_btn.disabled = True
            start_btn.text = "刮削中..."
            start_btn.style = ft.ButtonStyle(
                bgcolor=TEXT_DIM, color=TEXT,
                shape=ft.RoundedRectangleBorder(radius=12),
                padding=ft.Padding(left=24, top=14, right=24, bottom=14),
            )
            progress.value = 0
            log_controls.clear()
            log_list.controls = []
            status.value = "初始化..."
            add_log("--- 初始化 API 客户端 ---")
            page.update()

            def _update_ui():
                try:
                    page.update()
                except RuntimeError:
                    pass  # 页面已关闭
                except Exception:
                    # 一次重试
                    try:
                        page.update()
                    except Exception:
                        pass

            def _run():
                nonlocal start_btn
                try:
                    add_log("--- LLM 语义清洗 ---")
                    cl = OpenAI(base_url=state.llm_base_url, api_key=state.llm_api_key)
                    lm = {}
                    for i, p in enumerate(selected):
                        fn = os.path.basename(p)
                        progress.value = 0.05 + 0.15 * (i+1)/len(selected)
                        # 英文文件名（无 CJK 字符）：跳过 LLM，直接用清洗后的文件名
                        if not _has_cjk(fn):
                            en = _clean_en_stem(fn)
                            lm[fn] = {"standard_zh": "", "standard_en": en, "desc_zh": ""}
                            status.value = f"英文直通 {i+1}/{len(selected)}"
                            add_log(f"{fn[:35]} → {en} (跳过LLM)")
                            _update_ui()
                            continue
                        status.value = f"AI 清洗 {i+1}/{len(selected)}"
                        _update_ui()
                        try:
                            lm[fn] = normalize_rom_name(cl, state.llm_model, fn)
                            zh = lm[fn].get("standard_zh","")
                            en = lm[fn].get("standard_en","")
                            add_log(f"{fn[:35]} → {zh or en or '(空)'}")
                        except Exception as e:
                            lm[fn] = {"standard_zh": "", "standard_en": ""}
                            add_log(f"{fn[:35]} → LLM错误: {e}")
                        _update_ui()

                    add_log("--- GameGear 刮削 (第一数据源) ---")
                    _update_ui()
                    gg = GameGearFetcher()
                    bgm = BangumiFetcher()
                    tgdb = TGDBFetcher(state.tgdb_api_key) if state.tgdb_api_key else None
                    # 批量: 按 ROM 所在目录分组写入 gamelist
                    gamelists = {}  # {parent_dir: (root, existing_index)}
                    ok = 0

                    for i, rp in enumerate(selected):
                        fn = os.path.basename(rp); rel = "./" + fn
                        parent = str(Path(rp).parent)
                        # 懒加载各目录的 gamelist
                        if parent not in gamelists:
                            gp = Path(parent) / "gamelist.xml"
                            rt, ex = load_existing_gamelist(gp)
                            gamelists[parent] = (gp, rt, ex)
                        else:
                            gp, rt, ex = gamelists[parent]
                        cd = Path(parent) / "downloaded_media" / "covers"

                        progress.value = 0.30 + 0.65 * (i+1)/len(selected)
                        status.value = fn[:50]; _update_ui()

                        # 增量跳过：单文件刮削（"重新刮削"/"刮削这一个"）强制重刮，不走跳过逻辑
                        if not single and rel in ex:
                            add_log(f"跳过: {fn[:35]}"); continue
                        ll = lm.get(fn, {"standard_zh": "", "standard_en": "", "desc_zh": ""})
                        zh, en = ll.get("standard_zh",""), ll.get("standard_en","")
                        if not zh and not en:
                            add_log(f"无名称: {fn[:35]}"); continue

                        # 数据源选择：单文件刮削 + 强制 TGDB 开启 → 跳过 GameGear/Bangumi 直接 TGDB
                        use_tgdb_first = bool(single) and state.force_tgdb
                        meta = None
                        source = ""
                        rom_platform, platform_source = detect_rom_platform(rp)
                        if rom_platform:
                            add_log(f"平台识别: {rom_platform}（来源: {platform_source}）")
                        else:
                            add_log(f"平台识别失败: {fn[:35]}，跳过 GameGear 防止跨平台误匹配")

                        if use_tgdb_first:
                            # 强制 TGDB：未配 key 则提示并回退
                            if tgdb:
                                status.value = f"TGDB (强制): {zh or en}"
                                _update_ui()
                                meta = tgdb.search_game(zh, en)
                                source = "TGDB"
                            else:
                                add_log("强制 TGDB 已开启但未配 API Key，回退默认流程")

                        # 1) GameGear (第一数据源) — 平台 slug 过滤，媒体最丰富
                        if rom_platform and (not meta or "_error" in meta):
                            status.value = f"GameGear: {en or zh or fn}"
                            _update_ui()
                            try:
                                meta = gg.search_game(zh, en, platform=rom_platform, rom_name=fn)
                                source = "GameGear"
                            except Exception as ex:
                                add_log(f"GameGear异常: {str(ex)[:60]}")
                                meta = None

                        # 2) Bangumi (第二优先级) — 中文优先，平台匹配
                        if not meta or "_error" in meta:
                            status.value = f"Bangumi: {zh or en}"
                            _update_ui()
                            try:
                                meta = bgm.search_game(zh, en, platform=rom_platform)
                                source = "Bangumi"
                            except Exception as ex:
                                add_log(f"Bangumi异常: {str(ex)[:60]}")
                                meta = None

                        # 3) TGDB 备用
                        if not meta or "_error" in meta:
                            if tgdb:
                                status.value = f"TGDB: {zh or en}"
                                _update_ui()
                                try:
                                    meta = tgdb.search_game(zh, en)
                                    source = "TGDB"
                                except Exception as ex:
                                    add_log(f"TGDB异常: {str(ex)[:60]}")
                                    meta = None

                        if not meta:
                            add_log(f"未匹配: {zh or en}"); continue
                        if "_error" in meta:
                            add_log(f"{source}错误: {meta['_error'][:60]}")
                            continue

                        sf = _best_slug(ll.get("standard_en", ""), meta.get("name_en", ""), Path(fn).stem)
                        # 封面下载链: GameGear → Bangumi → TGDB
                        cr = ""
                        cover_url = meta.get("cover_url", "")
                        if cover_url:
                            if source == "GameGear":
                                if gg.download_cover(meta, cd / f"{sf}-image.png"):
                                    cr = f"./downloaded_media/covers/{sf}-image.png"
                            else:
                                if bgm.download_cover(meta, cd / f"{sf}-image.png"):
                                    cr = f"./downloaded_media/covers/{sf}-image.png"
                                elif tgdb and tgdb.download_cover(meta, cd / f"{sf}-image.png"):
                                    cr = f"./downloaded_media/covers/{sf}-image.png"
                        if cr:
                            add_log(f"封面: OK")
                        else:
                            add_log(f"封面: 无")

                        # marquee: 仅 GameGear 提供
                        mq = ""
                        if source == "GameGear":
                            if gg.download_marquee(meta, cd / f"{sf}-marquee.png"):
                                mq = f"./downloaded_media/covers/{sf}-marquee.png"
                                add_log("marquee: OK")
                            else:
                                add_log("marquee: 无")

                        # 描述: 只写入中文
                        raw_desc = meta.get("desc", "")
                        if raw_desc and not _is_chinese(raw_desc):
                            desc = translate_desc(cl, state.llm_model, raw_desc) or ll.get("desc_zh", "")
                        elif _is_chinese(raw_desc):
                            desc = raw_desc
                        else:
                            desc = ll.get("desc_zh", "")

                        # 名称: 中文优先 (LLM) > Bangumi中文 > GameGear英文 > 原名
                        display_name = (ll.get("standard_zh", "")
                                        or meta.get("name_zh", "")
                                        or meta.get("name_en", "")
                                        or meta.get("name", "")
                                        or Path(fn).stem)
                        add_log(f"完成: {display_name}")

                        entry = {
                            "name": display_name,
                            "desc": desc, "image": cr, "marquee": mq,
                            "developer": meta.get("developer",""), "publisher": meta.get("publisher",""),
                            "genre": meta.get("genre",""), "players": meta.get("players",""),
                            "release_date": meta.get("release_date",""), "rating": meta.get("rating",""),
                        }
                        ge = build_game_element(rel, entry)
                        if rel in ex: rt.remove(ex[rel])
                        rt.append(ge); ex[rel] = ge; write_gamelist(gp, rt); ok += 1
                        # 进度：元数据获取 30%-90%，写入 gamelist 90%-98%
                        progress.value = 0.30 + 0.68 * (i+1)/len(selected)

                    # 写入 gamelist 阶段
                    add_log("--- 写入 gamelist.xml ---")
                    gkeys = list(gamelists.keys())
                    for j, pdir in enumerate(gkeys):
                        gp, rt_existing, _ = gamelists[pdir]
                        progress.value = 0.98 + 0.02 * (j+1)/len(gkeys)
                        status.value = f"写入 {j+1}/{len(gkeys)}"
                        _update_ui()
                        add_log(f"gamelist.xml -> {pdir}")
                    progress.value = 1.0
                    status.value = f"完成 {ok} 个"
                except Exception as ex:
                    status.value = f"错误: {ex}"
                finally:
                    # 释放 GameGear 浏览器（Playwright）
                    try:
                        gg.close()
                    except Exception:
                        pass
                    start_btn.disabled = False
                    start_btn.text = "开始刮削"
                    page.update()

            page.run_thread(_run)

        start_btn.on_click = do_scrape

        return ft.View(
            route="/scrape",
            bgcolor=BG,
            appbar=ft.AppBar(
                leading=ft.IconButton(
                    ft.Icons.ARROW_BACK, icon_color=ACCENT, on_click=pop_view,
                ),
                title=ft.Row([
                    ft.Text("刮削任务", size=18, weight=ft.FontWeight.BOLD, color=TEXT),
                    ft.Container(width=8),
                    rom_count,
                ]),
                bgcolor=BG,
                actions=[toggle_btn],
            ),
            controls=[
                ft.Column(
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                    spacing=12,
                    controls=[
                        # ROM 列表区
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Text("ROM 列表", size=13, weight=ft.FontWeight.BOLD, color=TEXT_DIM),
                                ]),
                                ft.Container(height=6),
                                rom_cards,
                            ]),
                            padding=ft.Padding(left=16, top=4, right=16, bottom=0),
                        ),
                        # 进度区
                        ft.Container(
                            content=ft.Column([
                                ft.Row([
                                    ft.Icon(ft.Icons.DOWNLOADING, color=ACCENT, size=16),
                                    ft.Container(width=6),
                                    status,
                                ], spacing=0),
                                ft.Container(height=8),
                                progress,
                            ]),
                            bgcolor=SURFACE, border_radius=12,
                            padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                            margin=ft.Padding(left=16, top=0, right=16, bottom=0),
                        ),
                        # 日志区 (ListView 自动滚动)
                        ft.Container(
                            content=ft.Column([
                                ft.Text("日志", size=12, weight=ft.FontWeight.BOLD, color=TEXT_DIM),
                                ft.Container(height=4),
                                ft.Container(
                                    content=log_list,
                                    expand=True,
                                ),
                            ]),
                            bgcolor=SURFACE, border_radius=12,
                            padding=ft.Padding(left=16, top=12, right=16, bottom=12),
                            margin=ft.Padding(left=16, top=0, right=16, bottom=0),
                        ),
                        # 按钮
                        ft.Container(
                            content=start_btn,
                            padding=ft.Padding(left=16, top=4, right=16, bottom=16),
                        ),
                    ],
                ),
            ],
        )

    # 启动
    go_home()


if __name__ == "__main__":
    ft.run(main)
