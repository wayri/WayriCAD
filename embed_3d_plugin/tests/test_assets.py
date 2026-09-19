"""Asset bytes and UI-loader contract tests; fakes are NOT native GUI testing."""
from pathlib import Path
import hashlib
import importlib.util
import json
import shutil
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image
from embed_3d_plugin import assets
from tools.generate_suite_icons import icon, SPECS

ROOT = Path(__file__).resolve().parents[1]


class AssetFileTests(unittest.TestCase):
    def test_all_sizes_are_rgba_png(self):
        for n in assets.ICON_SIZES:
            with self.subTest(size=n), Image.open(assets.icon_path(n)) as im:
                im.load()
                self.assertEqual(im.format, 'PNG')
                self.assertEqual(im.mode, 'RGBA')
                self.assertEqual(im.size, (n, n))
                lo, hi = im.getchannel('A').getextrema()
                self.assertLess(lo, 32)
                self.assertGreater(hi, 240)

    def test_theme_assets_are_distinct(self):
        self.assertNotEqual(Path(assets.toolbar_icon_path()).read_bytes(),
                            Path(assets.toolbar_icon_path(True)).read_bytes())

    def test_toolbar_paths_are_absolute_and_theme_assets_present(self):
        for dark in (False, True):
            path = Path(assets.toolbar_icon_path(dark))
            self.assertTrue(path.is_absolute())
            self.assertTrue(path.is_file())
            with Image.open(path) as im:
                self.assertEqual(im.size, (24, 24))

    def test_pcm_icon_matches_generated_artwork(self):
        self.assertEqual((ROOT/'icon.png').read_bytes(), assets.icon_path(64).read_bytes())

    def test_unknown_icon_size_rejected(self):
        with self.assertRaises(ValueError):
            assets.icon_path(27)

    def test_windows_ico_has_multiple_native_sizes(self):
        with Image.open(ROOT/'icons/WayriCAD Embed3D.ico') as ico:
            self.assertTrue({(16,16), (24,24), (32,32), (48,48), (64,64), (128,128), (256,256)} <= ico.ico.sizes())
            for size in ico.ico.sizes():
                self.assertEqual(ico.ico.getimage(size).size, size)

    def test_asset_rebuild_is_reproducible(self):
        generated = icon(*SPECS['embed_3d_plugin']).resize((64,64), Image.Resampling.LANCZOS)
        # PNG compression can differ across platform zlib versions.
        # Compare the actual raster, including alpha, instead of compressed bytes.
        with Image.open(ROOT/'icon.png') as committed:
            self.assertEqual(generated.tobytes(), committed.convert('RGBA').tobytes())


class FakeBitmap:
    def __init__(self, value, kind=None):
        if isinstance(value, FakeImage):
            self.size = value.size
        else:
            with Image.open(value) as image:
                self.size = image.size
        self.scale = 1
    def IsOk(self): return True
    def GetWidth(self): return self.size[0]
    def ConvertToImage(self): return FakeImage(self.size)
    def SetScaleFactor(self, value): self.scale = value


class FakeImage:
    def __init__(self, size): self.size = size
    def Scale(self, w, h, quality): return FakeImage((w, h))


class FakeIcon:
    def CopyFromBitmap(self, bitmap): self.bitmap = bitmap
    def IsOk(self): return hasattr(self, 'bitmap')


class FakeIconBundle:
    def __init__(self): self.icons = []
    def AddIcon(self, icon): self.icons.append(icon)
    def GetIconCount(self): return len(self.icons)


class FakeStaticBitmap:
    def __init__(self, parent, bitmap): self.parent, self.bitmap = parent, bitmap
    def SetName(self, text): self.name = text
    def SetToolTip(self, text): self.tooltip = text


class FakeWindow:
    def FromDIP(self, size): return size*2
    def GetContentScaleFactor(self): return 1.0  # GTK uses physical pixels
    def SetIcons(self, bundle): self.bundle = bundle


def fake_wx(modern=True):
    api = SimpleNamespace(Bitmap=FakeBitmap, Icon=FakeIcon, IconBundle=FakeIconBundle,
                          StaticBitmap=FakeStaticBitmap, BITMAP_TYPE_PNG=1, IMAGE_QUALITY_HIGH=2)
    if modern:
        api.BitmapBundle = SimpleNamespace(FromBitmaps=lambda values: ('bundle', values))
    return api


class IconLoaderContractTests(unittest.TestCase):
    def test_window_icon_bundle_contains_seven_sizes(self):
        win = FakeWindow()
        self.assertTrue(assets.set_window_icons(win, fake_wx()))
        self.assertEqual([i.bitmap.size[0] for i in win.bundle.icons], [16,24,32,48,64,128,256])

    def test_header_bundle_has_hidpi_sources_and_tooltip(self):
        control = assets.make_header_icon(FakeWindow(), fake_wx())
        self.assertEqual([b.size[0] for b in control.bitmap[1]], [64,96,128,192,256])
        self.assertIn('Embed linked 3D model', control.tooltip)

    def test_older_wx_single_bitmap_fallback(self):
        control = assets.make_header_icon(FakeWindow(), fake_wx(modern=False))
        self.assertEqual(control.bitmap.size, (128,128))

    def test_missing_icons_do_not_break_header(self):
        with patch.object(assets, '_valid_bitmaps', return_value=[]):
            self.assertIsNone(assets.make_header_icon(FakeWindow(), fake_wx()))

    def test_missing_icons_do_not_break_window(self):
        with patch.object(assets, '_valid_bitmaps', return_value=[]):
            self.assertFalse(assets.set_window_icons(FakeWindow(), fake_wx()))

    def test_header_bitmap_errors_are_nonfatal(self):
        with patch.object(assets, '_valid_bitmaps', side_effect=RuntimeError('injected decode failure')):
            self.assertIsNone(assets.make_header_icon(FakeWindow(), fake_wx()))

    def test_window_bitmap_errors_are_nonfatal(self):
        with patch.object(assets, '_valid_bitmaps', side_effect=RuntimeError('injected decode failure')):
            self.assertFalse(assets.set_window_icons(FakeWindow(), fake_wx()))

    def test_action_plugin_uses_both_packaged_icons(self):
        class ActionPlugin:
            def __init__(self): self.defaults()
        spec = importlib.util.spec_from_file_location('embed_3d_plugin._plugin_asset_test', ROOT/'plugin.py')
        module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'pcbnew': SimpleNamespace(ActionPlugin=ActionPlugin), 'wx': fake_wx()}):
            spec.loader.exec_module(module)
            plugin = module.WayriCADEmbed3DPlugin()
        self.assertEqual(plugin.icon_file_name, assets.toolbar_icon_path())
        self.assertEqual(plugin.dark_icon_file_name, assets.toolbar_icon_path(True))
        self.assertTrue(plugin.show_toolbar_button)
        self.assertEqual('WayriCAD Embed3D', plugin.name)


if __name__ == '__main__': unittest.main()
