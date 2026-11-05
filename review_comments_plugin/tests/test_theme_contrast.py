"""Readable text and distinguishable controls across native and web themes."""
from pathlib import Path
import re

import pytest

from review_comments_plugin.theme import PALETTES, AVATAR_COLORS


def contrast(first, second):
    def luminance(color):
        color = color.lstrip('#')
        if len(color) == 3:
            color = ''.join(channel * 2 for channel in color)
        channels = [int(color[i:i+2], 16) / 255 for i in (0, 2, 4)]
        linear = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in channels]
        return sum(c * weight for c, weight in zip(linear, (.2126, .7152, .0722)))
    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + .05) / (low + .05)


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_native_text_links_status_and_disabled_labels_remain_readable(theme):
    colors = PALETTES[theme]
    for background in ('background', 'surface', 'hover', 'tint'):
        for foreground in ('text', 'muted', 'accent', 'warning'):
            assert contrast(colors[foreground], colors[background]) >= 4.5, (theme, foreground, background)
    assert contrast(colors['primary_text'], colors['primary']) >= 4.5
    assert contrast(colors['disabled_text'], colors['disabled']) >= 4.5
    for background in ('background', 'surface'):
        assert contrast(colors['border'], colors[background]) >= 3


@pytest.mark.parametrize('theme', ['light', 'dark'])
def test_embedded_viewer_controls_keep_contrast_without_opacity_fading(theme):
    css = (Path(__file__).parents[1] / 'web/style.css').read_text(encoding='utf-8')
    selector = ':root' if theme == 'light' else ':root[data-theme=dark]'
    body = re.search(re.escape(selector) + r'\{([^}]+)\}', css)[1]
    colors = dict(re.findall(r'--([a-z-]+):(#[0-9a-fA-F]+)', body))
    for background in ('page', 'surface', 'active'):
        for foreground in ('text', 'muted', 'accent'):
            assert contrast(colors[foreground], colors[background]) >= 4.5, (theme, foreground, background)
    assert contrast(colors['disabled-text'], colors['disabled']) >= 4.5
    assert contrast(colors['border'], colors['surface']) >= 3
    assert 'button:disabled{opacity:1;' in css


def test_author_initials_remain_readable_on_every_avatar_color():
    for color in AVATAR_COLORS:
        assert contrast('#ffffff', color) >= 4.5


def test_comment_pin_numbers_keep_contrast_including_the_selected_pin():
    source = (Path(__file__).parents[1] / 'web/bridge.mjs').read_text(encoding='utf-8')
    declaration = re.search(r'MARKER_COLORS = Object.freeze\(\{([^}]+)\}', source)[1]
    colors = dict(re.findall(r"(\w+):'(#[0-9a-fA-F]+)'", declaration))
    for role in ('normal', 'selected', 'error'):
        assert contrast('#ffffff', colors[role]) >= 4.5, role
