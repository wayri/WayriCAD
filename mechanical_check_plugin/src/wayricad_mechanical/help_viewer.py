"""Responsive images for wx.html, which does not implement browser CSS sizing."""
import re
from pathlib import Path

import wx
import wx.html


IMAGE_TAG = re.compile(r'<img\b[^>]*>', re.IGNORECASE)
SOURCE = re.compile(r'\bsrc\s*=\s*[\"\']([^\"\']+)[\"\']', re.IGNORECASE)
DIMENSION = re.compile(r'\s+(?:width|height)\s*=\s*(?:\"[^\"]*\"|\'[^\']*\'|[^\s>]+)', re.IGNORECASE)


def size_images(markup, available_width, dimensions):
    """Set both native HTML dimensions; never stretch or upscale source images."""
    # A shared figure width keeps the left/right edges aligned across screenshots
    # with different aspect ratios, while each image retains its own height.
    figure_width = min(max(1, available_width), 840,
                       *(min(width, 520 * width / height) for width, height in dimensions.values()))
    def resize(match):
        tag = match.group(0)
        source = SOURCE.search(tag)
        if not source or source[1] not in dimensions:
            return tag
        width, height = dimensions[source[1]]
        scale = min(1, figure_width / width)
        fitted_width, fitted_height = max(1, round(width * scale)), max(1, round(height * scale))
        tag = DIMENSION.sub('', tag).rstrip('> ').rstrip('/')
        return f'{tag} width="{fitted_width}" height="{fitted_height}">'
    return IMAGE_TAG.sub(resize, markup)


class HelpViewer(wx.html.HtmlWindow):
    def __init__(self, parent, path):
        super().__init__(parent, style=wx.html.HW_SCROLLBAR_AUTO)
        self.path = Path(path)
        self.markup = self.path.read_text(encoding='utf-8')
        self.border = self.FromDIP(20)
        self.SetBorders(self.border)
        self.dimensions = {}
        for tag in IMAGE_TAG.findall(self.markup):
            source = SOURCE.search(tag)
            if source:
                image = wx.Image(str(self.path.parent / source[1]))
                if image.IsOk():
                    self.dimensions[source[1]] = (image.GetWidth(), image.GetHeight())
        self.last_width = None
        self.resize_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self.reflow, self.resize_timer)
        self.Bind(wx.EVT_SIZE, self.on_size)
        self.Bind(wx.EVT_WINDOW_DESTROY, self.on_destroy)
        # Loading first establishes the base directory for relative image paths.
        self.LoadPage(str(self.path))
        self.reflow()

    def on_size(self, event):
        event.Skip()
        self.resize_timer.StartOnce(100)

    def reflow(self, event=None):
        width = self.GetClientSize().width
        if width <= 0 or width == self.last_width:
            return
        self.last_width = width
        available = max(1, width - 2 * self.border - self.FromDIP(20))
        old_height = max(1, self.GetVirtualSize().height - self.GetClientSize().height)
        scroll_unit = self.GetScrollPixelsPerUnit()[1]
        fraction = self.GetViewStart()[1] * scroll_unit / old_height
        self.Freeze()
        try:
            self.SetPage(size_images(self.markup, available, self.dimensions))
            new_height = max(0, self.GetVirtualSize().height - self.GetClientSize().height)
            new_unit = self.GetScrollPixelsPerUnit()[1]
            self.Scroll(0, round(fraction * new_height / new_unit) if new_unit else 0)
        finally:
            self.Thaw()

    def on_destroy(self, event):
        if event.GetEventObject() is self:
            self.resize_timer.Stop()
        event.Skip()

    def OnLinkClicked(self, link):
        if link.GetHref().startswith('#'):
            self.ScrollToAnchor(link.GetHref()[1:])
        else:
            super().OnLinkClicked(link)
