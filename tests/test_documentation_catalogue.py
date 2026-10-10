"""Keep the public plugin directory complete and GUI previews readable."""
from io import BytesIO

from PIL import Image

from tools.validate_docs import check_plugin_catalogue, check_readme_captures


GUIDES = {'first_plugin': 'first_plugin/README.md', 'second_plugin': 'second_plugin/ReadMe.md'}
FIRST = '| ![icon](first_plugin/icon.png) [First](first_plugin/README.md) | Editing | First purpose |'
SECOND = '| ![icon](second_plugin/icon.png) [Second](second_plugin/ReadMe.md) | Analysis | Second purpose |'


def catalogue(*rows, count=2, introduction=2):
    return (f'# Suite\n\n**{introduction} KiCad plugins**.\n\n'
        f'## All {count} plugins\n\n'
        '| Plugin and guide | Features | Purpose |\n|---|---|---|\n'
        + '\n'.join(rows) + '\n\n## Plugin previews\n')


def png(mode='RGBA', alpha=255):
    buffer = BytesIO()
    image = Image.new(mode, (4, 3), (240, 240, 240, alpha) if mode == 'RGBA' else (240, 240, 240))
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def test_small_inline_icons_and_guide_rows_cover_the_inventory():
    assert check_plugin_catalogue('README.md', catalogue(FIRST, SECOND), GUIDES) == []
    with_fragments = catalogue(FIRST.replace('first_plugin/README.md)', './first_plugin/README.md#workflow)'), SECOND)
    assert check_plugin_catalogue('README.md', with_fragments, GUIDES) == []


def test_guide_links_elsewhere_do_not_hide_a_missing_catalogue_row():
    text = '[Second](second_plugin/ReadMe.md)\n' + catalogue(FIRST)
    errors = check_plugin_catalogue('README.md', text, GUIDES)
    assert errors == ['README.md: catalogue table missing guide row for second_plugin']


def test_duplicate_rows_are_rejected_even_if_all_plugins_are_present():
    errors = check_plugin_catalogue('README.md', catalogue(FIRST, SECOND, FIRST), GUIDES)
    assert errors == ['README.md: catalogue table has 2 guide rows for first_plugin; expected one']


def test_heading_and_introduction_counts_follow_active_metadata():
    errors = check_plugin_catalogue('README.md', catalogue(FIRST, SECOND, count=1, introduction=1), GUIDES)
    assert errors == [
        'README.md: catalogue declares 1 plugins; active metadata has 2',
        'README.md: introduction declares 1 KiCad plugins; active metadata has 2',
    ]


def test_a_table_is_required_and_unrelated_rows_do_not_count_as_plugins():
    assert check_plugin_catalogue('README.md', '# Suite', GUIDES) == [
        'README.md: expected one All N plugins catalogue heading']
    assert check_plugin_catalogue('README.md', '## All 2 plugins\n[First](first_plugin/README.md)', GUIDES) == [
        'README.md: expected one Markdown plugin catalogue table']
    unrelated = '| [Retired](retired_plugin/README.md) | Old | Old |'
    errors = check_plugin_catalogue('README.md', catalogue(FIRST, SECOND, unrelated), GUIDES)
    assert errors == ['README.md: catalogue row 3 must link exactly one active plugin guide']


def test_a_row_cannot_combine_separate_plugins_or_break_the_column_layout():
    combined = '| [First](first_plugin/README.md) and [Second](second_plugin/ReadMe.md) | Features | Purpose |'
    assert 'must link exactly one' in check_plugin_catalogue('README.md', catalogue(combined), GUIDES)[0]
    errors = check_plugin_catalogue('README.md', catalogue(FIRST.replace(' | Editing |', ' | Extra | Editing |'), SECOND), GUIDES)
    assert errors == ['README.md: catalogue row 1 has 4 columns; expected 3']


def test_rgb_and_opaque_rgba_native_captures_are_accepted():
    text = '## Plugin previews\n![native workspace](tool_plugin/help-workspace.png)\n'
    for data in (png('RGB'), png('RGBA')):
        assert check_readme_captures('README.md', text, lambda _: data) == []


def test_a_transparent_pixel_in_a_gui_capture_is_rejected():
    buffer = BytesIO()
    image = Image.new('RGBA', (4, 3), (240, 240, 240, 255))
    image.putpixel((0, 0), (240, 240, 240, 0))
    image.save(buffer, format='PNG')
    text = '## Plugin previews\n<img src="tool_plugin/help-workspace.png" alt="Native GUI">\n'
    assert check_readme_captures('README.md', text, lambda _: buffer.getvalue()) == [
        'README.md: GUI capture tool_plugin/help-workspace.png has transparent pixels; recapture on an opaque background']


def test_transparent_icons_and_illustrations_outside_the_gallery_are_unaffected():
    text = ('## All 1 plugins\n![icon](tool_plugin/icon.png)\n'
        '## Plugin previews\n![icon](tool_plugin/resources/icon-96.png)\n'
        '![diagram](docs/layout.svg)\n'
        '## Workflows\n![transparent illustration](docs/illustration.png)\n')
    def unexpected_read(target):
        raise AssertionError(f'Not a GUI capture: {target}')
    assert check_readme_captures('README.md', text, unexpected_read) == []
