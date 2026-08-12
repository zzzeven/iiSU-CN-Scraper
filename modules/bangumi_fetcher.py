"""Bangumi (bgm.tv) 中文刮削模块 — 免费、无需 API Key

支持基于主机平台 (platform) 的精准匹配：
    search_game(中文名, 英文名, platform="GBA")
      → 搜索拿候选 → 逐个查 v0 详情 → infobox 平台含目标则命中
      → 命中失败回退 list[0]（保持向后兼容）

查 v0 详情时顺手从 infobox 提取 genre/players/developer/publisher，
让 gamelist.xml 字段更完整。
"""

import time
import urllib.parse

import requests
from pathlib import Path


# 项目 SYSTEMS 缩写 → Bangumi infobox 里的平台命名
# 实测确认：Bangumi 用 "PS" 而非 "PS1"；Switch 用全称
TO_BANGUMI_PLATFORM = {
    "GBA": "GBA", "GBC": "GB", "GB": "GB",
    "NDS": "NDS", "3DS": "3DS", "N64": "N64",
    "NES": "NES", "FC": "FC", "FDS": "FC",
    "SFC": "SFC", "SMC": "SFC",
    "MD": "MD", "GEN": "MD", "SMD": "MD",
    "32X": "32X", "GG": "GG", "SMS": "SMS", "PCE": "PCE",
    "PSP": "PSP",
    "PS1": "PS", "PS2": "PS2", "PSX": "PS",
    "DC": "DC", "NGC": "NGC",
    "Wii": "Wii", "WiiU": "Wii U",
    "Switch": "Nintendo Switch",
}


class BangumiFetcher:
    """Bangumi API 封装 — 中文游戏数据库。"""

    BASE = "https://api.bgm.tv"
    # 平台匹配时最多查多少个候选的详情
    MAX_DETAIL_LOOKUP = 5

    def __init__(self, request_delay: float = 1.0):
        self.request_delay = request_delay
        self._last = 0.0

    def _rate(self):
        now = time.monotonic()
        gap = now - self._last
        if gap < self.request_delay:
            time.sleep(self.request_delay - gap)
        self._last = time.monotonic()

    # ------------------------------------------------------------------
    def search_game(self, name_zh: str, name_en: str = "",
                    platform: str = "") -> dict | None:
        """搜索游戏。

        Args:
            name_zh / name_en: 中文名优先，英文兜底
            platform: 目标主机平台（如 "GBA"）。传入时会做精准匹配；
                      空字符串则盲取 list[0]（向后兼容）。

        Returns:
            统一格式的元数据 dict，或 None / {"_error": ...}
        """
        # 1) 搜索拿候选列表（中文名 → 英文名）
        candidates = []
        for name in (name_zh, name_en):
            if not name:
                continue
            candidates = self._search_candidates(name)
            if candidates:
                break

        if not candidates:
            return None

        # ⚠️ _search_candidates 出错时返回 [{"_error": ...}]，这种条目无 id 字段。
        #    过滤掉错误条目，保留正常候选；若全是错误条目则透传错误。
        clean = [c for c in candidates if "_error" not in c and "id" in c]
        if not clean:
            return candidates[0] if "_error" in (candidates[0] or {}) else None

        # 2) 无平台参数 → 盲取首条（保持原行为）
        if not platform:
            return self._build_meta_from_search(clean[0])

        # 3) 有平台 → 逐个查 v0 详情，命中目标平台即返回
        bgm_platform = TO_BANGUMI_PLATFORM.get(platform.upper(), platform.upper())
        for cand in clean[:self.MAX_DETAIL_LOOKUP]:
            detail = self._fetch_detail(cand["id"])
            if detail is None:
                continue
            # 平台比对
            if bgm_platform in detail["platforms"]:
                return self._build_meta_from_detail(cand, detail)
            # 同时容忍 meta_tags 命中（infobox 平台缺失时的补充）
            if bgm_platform in detail.get("meta_tags", []):
                return self._build_meta_from_detail(cand, detail)

        # 4) 候选里都没命中目标平台 → 回退首条（但仍尝试查详情补字段）
        first = clean[0]
        detail = self._fetch_detail(first["id"])
        if detail is not None:
            return self._build_meta_from_detail(first, detail)
        return self._build_meta_from_search(first)

    def _search_candidates(self, name: str) -> list:
        """调用搜索接口，返回候选 list（原始 dict 列表）。"""
        self._rate()
        try:
            resp = requests.get(
                f"{self.BASE}/search/subject/{urllib.parse.quote(name)}",
                params={"type": 4, "responseGroup": "large"},
                headers={"User-Agent": "iiSU-CN-Scraper/1.0"},
                timeout=15,
            )
        except requests.RequestException as e:
            return [{"_error": f"Bangumi网络: {e}"}]

        if resp.status_code >= 400:
            return [{"_error": f"Bangumi错误({resp.status_code})"}]

        try:
            data = resp.json()
        except Exception:
            return [{"_error": "Bangumi返回非JSON"}]

        # ⚠️ 无结果时 list 是 null（不是 []），必须用 or 兜底
        items = data.get("list") or []
        return items

    def _fetch_detail(self, subject_id) -> dict | None:
        """查 v0 详情接口，提取 infobox 全字段 + 平台列表。

        Returns:
            {platforms, genre, players, developer, publisher, meta_tags}
            或 None（查询失败）
        """
        if not subject_id:
            return None
        self._rate()
        try:
            resp = requests.get(
                f"{self.BASE}/v0/subjects/{subject_id}",
                headers={"User-Agent": "iiSU-CN-Scraper/1.0"},
                timeout=15,
            )
        except requests.RequestException:
            return None
        if resp.status_code >= 400:
            return None
        try:
            data = resp.json()
        except Exception:
            return None

        return self._parse_infobox(data)

    def _parse_infobox(self, data: dict) -> dict:
        """从 v0 详情解析 infobox，提取平台/类型/人数/开发商/发行商。"""
        platforms = []
        genre = ""
        players = ""
        developer = ""
        publisher = ""

        for item in data.get("infobox", []):
            key = item.get("key", "")
            val = item.get("value", "")
            if key == "平台" and isinstance(val, list):
                # [{"v":"SFC"}, {"v":"PS"}, ...]
                platforms = [v.get("v", "") for v in val if isinstance(v, dict)]
            elif key == "平台" and isinstance(val, str):
                platforms = [val]
            elif key == "游戏类型":
                genre = val if isinstance(val, str) else str(val)
            elif key == "游玩人数":
                players = str(val)
            elif key in ("开发", "开发商", "开发者"):
                developer = self._extract_name(val)
            elif key in ("发行", "发行商"):
                publisher = self._extract_name(val)

        return {
            "platforms": platforms,
            "genre": genre,
            "players": players,
            "developer": developer,
            "publisher": publisher,
            "meta_tags": data.get("meta_tags", []),
        }

    @staticmethod
    def _extract_name(val) -> str:
        """从 infobox 值里提取名字（可能是 str / [{"v":...}] / [{"k":..,"v":..}]）。"""
        if isinstance(val, str):
            return val
        if isinstance(val, list) and val:
            first = val[0]
            if isinstance(first, dict):
                return first.get("v", "") or first.get("k", "")
            return str(first)
        return str(val) if val else ""

    # ------------------------------------------------------------------
    def _build_meta_from_search(self, item: dict) -> dict:
        """从搜索结果构建元数据（字段不全，无 platform/genre/players）。"""
        if "_error" in item:
            return item
        # 封面图
        images = item.get("images", {}) or {}
        cover_url = images.get("large", images.get("common", ""))
        # 评分 (API may return "rating": null)
        rating = (item.get("rating") or {}).get("score", "")
        return {
            "name_zh": item.get("name_cn", ""),
            "name_en": item.get("name", ""),  # 原名(日文/英文)
            "desc": item.get("summary", ""),
            "developer": "",
            "publisher": "",
            "genre": "",
            "players": "",
            "release_date": item.get("air_date", ""),
            "rating": str(rating) if rating else "",
            "cover_url": cover_url,
        }

    def _build_meta_from_detail(self, cand: dict, detail: dict) -> dict:
        """从搜索结果 + v0 详情合并构建元数据（字段完整）。"""
        meta = self._build_meta_from_search(cand)
        meta["genre"] = detail.get("genre", "")
        meta["players"] = detail.get("players", "")
        meta["developer"] = detail.get("developer", "")
        meta["publisher"] = detail.get("publisher", "")
        return meta

    # ------------------------------------------------------------------
    def download_cover(self, meta: dict, dest: Path) -> bool:
        url = meta.get("cover_url", "")
        if not url:
            return False
        # Bangumi 图片可能需要 referer
        if url.startswith("http:"):
            url = url.replace("http:", "https:", 1)
        self._rate()
        try:
            resp = requests.get(url, timeout=30,
                headers={"User-Agent": "iiSU-CN-Scraper/1.0", "Referer": "https://bgm.tv/"})
            resp.raise_for_status()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(resp.content)
            return True
        except requests.RequestException:
            return False
