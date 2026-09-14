"""Packaged icon loading: no Pillow, native DLLs, or network needed at runtime."""
from __future__ import annotations
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ICON_SIZES = (16, 24, 32, 48, 64, 96, 128, 192, 256, 512)


def toolbar_icon_path(dark: bool = False) -> str:
    """KiCad ActionPlugin requires an absolute PNG pathname, not a wx.Bitmap."""
    return str(ROOT / 'resources' / ('icon-dark-24.png' if dark else 'icon-24.png'))


def icon_path(size: int) -> Path:
    if size not in ICON_SIZES:
        raise ValueError(f'No packaged WayriCAD Embed3D icon at {size} pixels')
    return ROOT / 'icons' / f'icon{size}.png'


def _valid_bitmaps(wx, sizes):
    result = []
    for size in sizes:
        path = icon_path(size)
        if not path.is_file():
            continue
        bitmap = wx.Bitmap(str(path), wx.BITMAP_TYPE_PNG)
        if bitmap.IsOk():
            result.append(bitmap)
    return result


def set_window_icons(window, wx) -> bool:
    """Let each window manager select a suitable icon size; fail non-fatally."""
    try:
        bitmaps = _valid_bitmaps(wx, (16, 24, 32, 48, 64, 128, 256))
        if not bitmaps:
            return False
        bundle = wx.IconBundle()
        for bitmap in bitmaps:
            icon = wx.Icon()
            icon.CopyFromBitmap(bitmap)
            if icon.IsOk():
                bundle.AddIcon(icon)
        if not bundle.GetIconCount():
            return False
        window.SetIcons(bundle)
        return True
    except Exception:
        # Branding must never stop the underlying embedding workflow.
        from .logging_utils import get_logger
        get_logger().exception('Could not load WayriCAD Embed3D window icons')
        return False


def make_header_icon(parent, wx):
    """A 64-DIP branded header, with 1x/1.5x/2x/3x/4x bitmap sources.

    Modern wx chooses from the bitmap bundle when the window's DPI changes.
    A single-bitmap fallback keeps older wx bindings usable.
    """
    try:
        bitmaps = _valid_bitmaps(wx, (64, 96, 128, 192, 256))
        if not bitmaps:
            return None
        if hasattr(wx, 'BitmapBundle'):
            picture = wx.BitmapBundle.FromBitmaps(bitmaps)
        else:
            wanted = parent.FromDIP(64)
            best = next((b for b in bitmaps if b.GetWidth() >= wanted), bitmaps[-1])
            image = best.ConvertToImage().Scale(wanted, wanted, wx.IMAGE_QUALITY_HIGH)
            picture = wx.Bitmap(image)
            if hasattr(picture, 'SetScaleFactor'):
                picture.SetScaleFactor(parent.GetContentScaleFactor())
        control = wx.StaticBitmap(parent, bitmap=picture)
        control.SetName('WayriCAD Embed3D branding')
        control.SetToolTip('WayriCAD Embed3D — Embed linked 3D model files into footprints')
        return control
    except Exception:
        from .logging_utils import get_logger
        get_logger().exception('Could not load WayriCAD Embed3D header icon')
        return None
