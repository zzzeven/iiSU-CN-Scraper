import unittest

from modules.platform_detector import detect_rom_platform, platform_from_dirname
from modules.gamegear_fetcher import filter_platform_links


class PlatformDetectorTests(unittest.TestCase):
    def test_detects_platform_from_direct_parent(self):
        self.assertEqual(detect_rom_platform("D:/ROMs/GBA/中文游戏.gba")[0], "GBA")

    def test_detects_platform_from_upper_parent(self):
        platform, source = detect_rom_platform("D:/ROMs/GBA/汉化版/中文游戏.gba")
        self.assertEqual(platform, "GBA")
        self.assertEqual(source, "目录 GBA")

    def test_arcade_board_wins_over_ps2_substring(self):
        self.assertEqual(platform_from_dirname("CPS2"), "Arcade")

    def test_longer_platform_name_wins(self):
        self.assertEqual(platform_from_dirname("Nintendo WiiU"), "WiiU")

    def test_uses_unambiguous_extension_as_fallback(self):
        platform, source = detect_rom_platform("D:/收藏/汉化版/中文游戏.gba")
        self.assertEqual((platform, source), ("GBA", "扩展名 .gba"))

    def test_does_not_guess_ambiguous_extension(self):
        self.assertEqual(detect_rom_platform("D:/收藏/汉化版/游戏.zip"), ("", ""))

    def test_gamegear_rejects_other_platform_results(self):
        links = [{"href": "/archive/games/ps2/example-game", "text": "Example Game"}]
        self.assertEqual(filter_platform_links(links, "gba"), [])


if __name__ == "__main__":
    unittest.main()
