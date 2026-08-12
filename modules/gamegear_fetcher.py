"""GameGear (gamegear.net) 刮削模块 — 第一数据源

GameGear 提供极其丰富的游戏媒体（box art / marquee / screenshots / fanart 等），
但搜索页/游戏页被 Cloudflare 保护，必须用真实浏览器（Playwright）访问。

本模块：
1. 用 Playwright 持久化 profile + stealth 参数自动过 Cloudflare（首次约 5-15 秒）
2. 搜索 → 按平台 slug 过滤 → 访问游戏页 → 提取 og:image 里的 mediaID
3. 媒体直链可用 requests 直接下载（无需过 Cloudflare）

用法:
    gg = GameGearFetcher()
    meta = gg.search_game("最终幻想VI", platform="SFC")
    gg.download_cover(meta, dest)
    gg.download_marquee(meta, dest)
    gg.close()   # 刮削结束后释放浏览器
"""

import asyncio
import os
import sys
import tempfile
import threading
import time
import urllib.parse
from pathlib import Path

import requests


# 项目 SYSTEMS 缩写 → GameGear 平台 slug（浏览器实测确认）
PLATFORM_SLUGS = {
    "GBA": "gba", "GBC": "gbc", "GB": "gb", "NDS": "nds", "3DS": "3ds",
    "N64": "n64", "NES": "nes", "FC": "nes", "FDS": "nes",
    "SFC": "snes", "SMC": "snes",
    "MD": "megadrive", "GEN": "megadrive", "SMD": "megadrive",
    "32X": "sega32x", "GG": "gamegear", "SMS": "mastersystem",
    "PCE": "pce", "PSP": "psp", "PS1": "psx", "PS2": "ps2",
    "PSX": "psx", "DC": "dreamcast", "NGC": "gamecube",
    "Wii": "wii", "WiiU": "wiiu", "Switch": "switch",
    "SATURN": "saturn",
    "ARCADE": "arcade",  # 街机：ROM 短名即页面 slug（avsp.zip → /arcade/avsp）
}

# 媒体类型 → URL 后缀（gamegear 规范化路径）
MEDIA_TYPES = {
    "cover": "box2d",       # 2D 封面（首选）
    "marquee": "marquee",   # 灯箱 Logo
    "screenshot": "screenshot",  # 游戏截图
    "titlescreen": "titlescreen",
    "fanart": "fanart",
    "wheel": "wheel",
}

# Playwright 持久化 profile 目录（cookie 跨会话复用，避免每次过 Cloudflare）
_PROFILE_DIR = os.path.join(
    tempfile.gettempdir(), "iisusc_gg_profile"
)

# UA 按平台生成，避免 macOS UA 跑在 Windows Chromium 上触发 Cloudflare 指纹异常
if sys.platform == "win32":
    _UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
elif sys.platform == "darwin":
    _UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")
else:
    _UA = ("Mozilla/5.0 (X11; Linux x86_64) "
           "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36")


class GameGearFetcher:
    """GameGear 数据源封装。"""

    BASE = "https://gamegear.net"

    def __init__(self, request_delay: float = 0.8):
        self.request_delay = request_delay
        self._last = 0.0
        self._pw = None
        self._ctx = None
        self._page = None
        self._loop = None
        self._loop_thread = None
        self._closed = False

    # ------------------------------------------------------------------
    # Playwright 浏览器管理
    # ------------------------------------------------------------------
    def _rate(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < self.request_delay:
            time.sleep(self.request_delay - gap)
        self._last = time.monotonic()

    def _ensure_browser(self):
        """懒启动 Playwright 浏览器（持久化 profile，自动过 Cloudflare）。

        持久化 profile 可能因异常退出残留锁（Windows 上常见），
        启动失败时自动回退到一次性临时 profile。
        """
        if self._page is not None:
            return self._page
        from playwright.async_api import async_playwright

        async def _start(profile_dir: str):
            self._pw = await async_playwright().start()
            self._ctx = await self._pw.chromium.launch_persistent_context(
                profile_dir,
                headless=False,  # 真实浏览器窗口，利于过 Cloudflare
                user_agent=_UA,
                args=["--disable-blink-features=AutomationControlled"],
            )
            self._page = self._ctx.pages[0] if self._ctx.pages else await self._ctx.new_page()
            return self._page

        try:
            return self._run(_start(_PROFILE_DIR))
        except Exception as first_err:
            # 持久化 profile 锁残留/损坏 → 用临时 profile 重试
            self._pw = self._ctx = self._page = None
            try:
                tmp_dir = tempfile.mkdtemp(prefix="iisusc_gg_profile_")
                return self._run(_start(tmp_dir))
            except Exception:
                return {"_error": f"GameGear浏览器启动失败: {first_err}"}

    # ------------------------------------------------------------------
    # 事件循环管理（Playwright async 对象绑定创建它的 loop，必须持久复用）
    # ------------------------------------------------------------------
    def _ensure_loop(self):
        """确保有一个后台线程运行持久事件循环。"""
        if self._loop is not None:
            return self._loop
        self._loop = asyncio.new_event_loop()

        def _run_loop():
            asyncio.set_event_loop(self._loop)
            self._loop.run_forever()

        self._loop_thread = threading.Thread(target=_run_loop, daemon=True)
        self._loop_thread.start()
        return self._loop

    def _run(self, coro, timeout: float = 120.0):
        """把协程提交到持久事件循环执行（同步 API 封装，带超时保护）。"""
        loop = self._ensure_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        return fut.result(timeout=timeout)

    def close(self):
        """释放浏览器。"""
        if self._closed:
            return
        self._closed = True

        async def _close():
            if self._ctx:
                try:
                    await self._ctx.close()
                except Exception:
                    pass
            if self._pw:
                try:
                    await self._pw.stop()
                except Exception:
                    pass
            if self._loop is not None:
                self._loop.stop()

        if self._pw is not None or self._ctx is not None:
            try:
                self._run(_close(), timeout=30)
            except Exception:
                pass
        self._pw = self._ctx = self._page = None

    # ------------------------------------------------------------------
    # 页面导航（健壮：忽略 Cloudflare challenge 阻塞，轮询等就绪）
    # ------------------------------------------------------------------
    @staticmethod
    def _is_challenge(title: str) -> bool:
        t = (title or "").lower()
        return "just a moment" in t or "请稍候" in t or "challenge" in t

    async def _robust_goto(self, page, url: str, timeout: int = 40) -> bool:
        """导航到 URL，轮询等待真实内容出现（容忍 Cloudflare 挑战）。"""
        try:
            await page.goto(url, timeout=timeout * 1000, wait_until="domcontentloaded")
        except Exception:
            pass
        for _ in range(timeout):
            await page.wait_for_timeout(1000)
            try:
                title = await page.title()
                if self._is_challenge(title):
                    continue
                # 页面有 h1 且非验证页 → 就绪
                if await page.locator("h1").count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _wait_results(self, page, timeout: int = 30) -> bool:
        """等待搜索结果出现（含游戏链接）。"""
        for _ in range(timeout):
            await page.wait_for_timeout(1000)
            try:
                if await page.locator('a[href*="/archive/games/"]').count() > 0:
                    return True
            except Exception:
                pass
        return False

    # ------------------------------------------------------------------
    # 名称相似度（避免搜索模糊匹配到不相关的游戏）
    # ------------------------------------------------------------------
    @staticmethod
    def _similar(a: str, b: str) -> float:
        """名称相似度检查（0~1）。基于词集重叠，避免字符级包含误判。"""
        import re
        a = (a or "").lower().strip()
        b = (b or "").lower().strip()
        a = re.sub(r"[^a-z0-9 ]", " ", a)
        b = re.sub(r"[^a-z0-9 ]", " ", b)
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        wa = set(a.split())
        wb = set(b.split())
        if not wa or not wb:
            return 0.0
        # 移除公共停用词（版本/区域标记等）
        stop = {"the", "of", "and", "a", "an", "edition", "version",
                "usa", "japan", "europe", "world", "rev", "rev1", "rev2"}
        wa2 = wa - stop
        wb2 = wb - stop
        if not wa2 or not wb2:
            return 0.0
        # 交集/并集（Jaccard 相似度，更严格）
        inter = len(wa2 & wb2)
        union = len(wa2 | wb2)
        return inter / union

    # ------------------------------------------------------------------
    # 搜索 + 解析
    # ------------------------------------------------------------------
    def search_game(self, name_zh: str = "", name_en: str = "",
                    platform: str = "", rom_name: str = "") -> dict | None:
        """搜索游戏。

        Args:
            name_zh / name_en: 中文名或英文名（GameGear 是英文站，用英文名效果好）
            platform: 项目平台缩写（如 "SFC"），用于过滤搜索结果
            rom_name: ROM 文件名（含扩展名）。Arcade 平台 ROM 名即页面 slug，
                      直接拼 URL 优先命中（如 avsp.zip → /archive/games/arcade/avsp）

        Returns:
            {name, name_en, desc, developer, publisher, genre, players,
             release_date, rating, cover_url, media: {type: url}, source: "GameGear"}
            或 None
        """
        # GameGear 是英文站，优先英文名
        query = name_en or name_zh
        # 有 rom_name 时可直拼 URL，无需搜索词
        if not query and not rom_name:
            return None

        try:
            page = self._ensure_browser()
        except Exception as e:
            return {"_error": f"GameGear浏览器启动失败: {e}"}
        # _ensure_browser 失败时返回 {"_error": ...} dict 而非 page
        if isinstance(page, dict):
            return page

        slug = PLATFORM_SLUGS.get((platform or "").upper(), "")

        async def _search():
            # 0) 优先尝试 ROM 文件名直拼 URL（Arcade 平台 ROM 名即页面 slug）
            if rom_name and slug:
                from pathlib import Path as _P
                rom_stem = _P(rom_name).stem.lower()
                direct = f"/archive/games/{slug}/{rom_stem}"
                result = await self._try_game_page(page, direct, slug)
                if result is not None and "_error" not in result:
                    return result

            # 直拼失败且无搜索词 → 无法继续
            if not query:
                return None

            # 1) 搜索
            q = urllib.parse.quote(query)
            ok = await self._robust_goto(page, f"{self.BASE}/archive/search?q={q}")
            if not ok:
                return {"_error": "GameGear搜索失败 (Cloudflare)"}
            await self._wait_results(page)

            # 2) 提取搜索结果（href + 链接文字），按平台过滤 + 相似度排序
            results = await page.eval_on_selector_all(
                'a[href*="/archive/games/"]',
                "els => els.map(e => ({href: e.getAttribute('href'), text: e.textContent.trim()}))",
            )
            game_links = [r for r in results if r["href"] and r["href"].startswith("/archive/games/")]

            # 去重
            seen = set()
            uniq = []
            for r in game_links:
                if r["href"] not in seen:
                    seen.add(r["href"])
                    uniq.append(r)

            if not uniq:
                return None

            # 平台过滤：优先 slug 匹配
            if slug:
                slugged = [r for r in uniq if f"/archive/games/{slug}/" in r["href"]]
                if slugged:
                    uniq = slugged

            # Arcade 平台：slug 是 MAME 短名（avsp/ikari/sfach），与英文名无词重叠，
            # 相似度判断无意义 → 直接用搜索结果第一个（GameGear 已按相关度排序）
            if slug == "arcade":
                target = uniq[0]["href"]

            # 主机平台：用 slug 转词做相似度排序
            elif name_en:
                def _slug_to_words(href: str) -> str:
                    # /archive/games/gba/pokemon-emerald-version-usa-europe → pokemon emerald version usa europe
                    parts = href.rstrip("/").split("/")
                    return (parts[-1] if parts else "").replace("-", " ")

                scored = [(self._similar(name_en, _slug_to_words(r["href"])), r) for r in uniq]
                scored.sort(key=lambda x: -x[0])
                best_score, best = scored[0]
                # 相似度低于阈值视为未命中（避免模糊匹配到无关游戏）
                if best_score < 0.25:
                    return None
                target = best["href"]
            else:
                target = uniq[0]["href"]

            # 3) 访问游戏页，提取媒体 URL
            return await self._try_game_page(page, target, slug)

        return self._run(_search())

    async def _try_game_page(self, page, game_path: str, slug: str) -> dict | None:
        """尝试访问游戏页并提取媒体。404/无效页返回 None（调用方回退搜索）。"""
        ok = await self._robust_goto(page, f"{self.BASE}{game_path}")
        if not ok:
            return None  # 页面没就绪（Cloudflare 或 404），回退搜索

        # h1 与 404 检测
        try:
            h1 = await page.eval_on_selector("h1", "e => e.textContent || ''")
        except Exception:
            return None
        h1 = (h1 or "").strip()
        low_h1 = h1.lower()
        if not h1 or "not found" in low_h1 or "page not found" in low_h1 or "404" in low_h1:
            return None  # 404 页面

        # og:image（可选，有的页面无封面）
        og = ""
        try:
            og = await page.eval_on_selector(
                'meta[property="og:image"]',
                "e => e.getAttribute('content') || ''",
            )
        except Exception:
            og = ""
        og = og or ""

        # 从 og:image 推导媒体 URL 模式（同 slug + 同 mediaID，不同 type 后缀）
        media = {}
        if og and "/media/canonical/" in og:
            media["cover"] = og  # box2d
            # 从 URL 推导其他类型：把 box2d 替换成其他 type
            for mtype, suffix in MEDIA_TYPES.items():
                if mtype == "cover":
                    continue
                # URL 形如 .../{type}/{slug}__{id}.png → 替换 type
                try:
                    base = og.rsplit("/", 2)[0]  # .../canonical/console/snes
                    fname = og.rsplit("/", 1)[-1]  # box2d/final-fantasy-vi-japan__713.png
                    # fname 含 type 前缀，替换掉
                    url = og.replace("/box2d/", f"/{suffix}/")
                    media[mtype] = url
                except Exception:
                    pass

        # 详情字段（dt/dd）
        details = {}
        try:
            pairs = await page.eval_on_selector_all(
                "dt",
                "dts => dts.map(dt => { const dd = dt.nextElementSibling; "
                "return {k: dt.textContent.trim(), v: dd ? dd.textContent.trim() : ''}; })",
            )
            for p in pairs:
                details[p["k"]] = p["v"]
        except Exception:
            pass

        # 开发商/年份/类型（页面顶部链接）
        dev = ""
        year = ""
        genre = ""
        try:
            links_info = await page.eval_on_selector_all(
                "main a",
                "els => els.map(e => ({t: e.textContent.trim(), h: e.getAttribute('href')||''}))",
            )
            for li in links_info:
                if "developer=" in li["h"] and not dev:
                    dev = li["t"]
                elif "year_from=" in li["h"] and not year:
                    year = li["t"]
                elif "canonical_genre=" in li["h"] and not genre:
                    genre = li["t"]
        except Exception:
            pass

        return {
            "name": h1 or "",
            "name_en": h1 or "",
            "name_zh": "",
            "desc": "",  # 页面无简介摘要，由 LLM 补
            "developer": dev,
            "publisher": "",
            "genre": genre,
            "players": details.get("Players", ""),
            "release_date": year,
            "rating": "",
            "cover_url": og,
            "media": media,
            "source": "GameGear",
            "gg_platform": slug,
        }

    # ------------------------------------------------------------------
    # 媒体下载（媒体直链无需过 Cloudflare，requests 直接下）
    # ------------------------------------------------------------------
    def _download(self, url: str, dest) -> bool:
        if not url:
            return False
        dest = Path(dest)
        self._rate()
        try:
            resp = requests.get(url, timeout=30,
                headers={"User-Agent": _UA})
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        except requests.RequestException:
            return False

    def download_cover(self, meta: dict, dest: Path) -> bool:
        url = (meta.get("media") or {}).get("cover") or meta.get("cover_url", "")
        return self._download(url, dest)

    def download_marquee(self, meta: dict, dest: Path) -> bool:
        url = (meta.get("media") or {}).get("marquee", "")
        return self._download(url, dest)

    def download_screenshot(self, meta: dict, dest: Path) -> bool:
        url = (meta.get("media") or {}).get("screenshot", "")
        return self._download(url, dest)

    # ------------------------------------------------------------------
    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
