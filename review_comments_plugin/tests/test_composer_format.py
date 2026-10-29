"""Plain Markdown edits, hostile clipboard inputs and resource-free preview."""
from html.parser import HTMLParser

import pytest

from review_comments_plugin.composer_format import (
    MAX_HTML, MAX_TEXT, apply_format, html_to_markdown, preview_html, safe_https,
)


@pytest.mark.parametrize('action,expected,selected',[
    ('bold','Before **choice** after','choice'),
    ('italic','Before *choice* after','choice'),
    ('inlinecode','Before `choice` after','choice'),
    ('link','Before [choice](https://example.com) after','choice'),
])
def test_inline_formats_preserve_surroundings_and_select_content(action,expected,selected):
    result,start,end=apply_format('Before choice after',7,13,action)
    assert result==expected and result[start:end]==selected


@pytest.mark.parametrize('action,expected',[
    ('heading','# first\n# second'),('quote','> first\n> second'),
    ('bullets','- first\n- second'),('numbered','1. first\n2. second'),('tasks','- [ ] first\n- [ ] second'),
])
def test_block_formats_expand_touched_lines_and_keep_next_line(action,expected):
    text='untouched\nfirst\nsecond\ntrailing'
    result,start,end=apply_format(text,12,23,action)
    assert result=='untouched\n'+expected+'\ntrailing'
    assert result[start:end]==expected


@pytest.mark.parametrize('action',['bold','italic','inlinecode','codeblock','heading','quote','bullets','numbered','tasks','link','table'])
def test_empty_selection_inserts_editable_markdown(action):
    result,start,end=apply_format('',0,0,action)
    assert result and 0<=start<end<=len(result)
    assert '<' not in result


def test_unicode_offsets_are_python_character_offsets():
    result,start,end=apply_format('µ 🛰 net',2,3,'bold')
    assert result=='µ **🛰** net' and result[start:end]=='🛰'


def test_code_delimiters_keep_embedded_backticks_and_blank_lines():
    result,start,end=apply_format('a`b',0,3,'inlinecode')
    assert result=='``a`b``' and result[start:end]=='a`b'
    block='before\n```\n\n\nafter'
    result,start,end=apply_format(block,0,len(block),'codeblock')
    assert result.startswith('````\n') and result.endswith('\n````')
    assert result[start:end]==block
    with pytest.raises(ValueError,match='multiline'):
        apply_format('a\nb',0,3,'inlinecode')


def test_table_preserves_tabbed_values_and_escapes_literal_pipes():
    result,start,end=apply_format('Name\tValue\nA|B\t2',0,16,'table')
    assert result=='| Name | Value |\n| --- | --- |\n| A\\|B | 2 |'
    assert (start,end)==(0,len(result))
    html=preview_html(result)
    assert '<table>' in html and '<th>Name</th>' in html and '<td>A|B</td>' in html


@pytest.mark.parametrize('start,end',[(-1,0),(0,10),(2,1),(True,2),(0,1.5)])
def test_invalid_selections_are_rejected(start,end):
    with pytest.raises(ValueError):apply_format('abc',start,end,'bold')


def test_text_and_formatted_output_limits_never_silently_truncate():
    assert preview_html('a'*MAX_TEXT)
    with pytest.raises(ValueError):apply_format('a'*(MAX_TEXT+1),0,0,'bold')
    with pytest.raises(ValueError):apply_format('a'*MAX_TEXT,0,MAX_TEXT,'bold')
    with pytest.raises(ValueError):preview_html('a'*(MAX_TEXT+1))
    with pytest.raises(ValueError):apply_format('abc',0,3,'unknown')
    with pytest.raises(ValueError):preview_html('a\x00b')


@pytest.mark.parametrize('url',['javascript:alert(1)','data:text/html,attack','http://example.com',
    '//example.com','file:///private/file','https://user:secret@example.com','https://example.com\\evil',
    'https://example.com/\nattack','https://example.com/a b','https://example.com:wrong','https://[]',
    'https://example.com/" onload="attack'])
def test_links_require_unambiguous_https_without_credentials(url):
    with pytest.raises(ValueError):safe_https(url)
    with pytest.raises(ValueError):apply_format('label',0,5,'link',url=url)


def test_markdown_link_delimiters_are_escaped_and_url_parentheses_encoded():
    result,start,end=apply_format('array[x]',0,8,'link',url='https://example.com/a(b)?x=[1]')
    assert result=='[array\\[x\\]](https://example.com/a%28b%29?x=%5B1%5D)'
    assert result[start:end]=='array\\[x\\]'


def test_clipboard_paragraphs_breaks_and_inline_formatting():
    source='<p>Hello <strong>bold</strong> <em>italic</em><br>next &amp; last</p><p>End</p>'
    assert html_to_markdown(source)=='Hello **bold** *italic*\nnext & last\n\nEnd'


def test_clipboard_nested_lists_quotes_and_safe_links_are_visible_markdown():
    source='<blockquote><p>Quoted</p></blockquote><ul><li>one</li><li><strong>two</strong><ul><li>child</li></ul></li></ul><ol><li>alpha</li><li>beta</li></ol><p><a href="https://example.com/a(b)">safe</a></p>'
    result=html_to_markdown(source)
    assert '> Quoted' in result and '- one' in result and '- **two**' in result
    assert '  - child' in result and '1. alpha\n2. beta' in result
    assert '[safe](https://example.com/a%28b%29)' in result


def test_clipboard_preformatted_code_retains_every_blank_line_and_escapes_fence():
    source='<pre><code>if x &lt; 2:\n\n\n    print("```")</code></pre>'
    result=html_to_markdown(source)
    assert result=='````\nif x < 2:\n\n\n    print("```")\n````'
    assert '<pre><code>if x &lt; 2:\n\n\n    print(&quot;```&quot;)</code></pre>' in preview_html(result)


def test_clipboard_drops_active_content_and_never_converts_images_to_fetchable_markup():
    source='<style>@import "https://secret.invalid";</style><script>fetch("https://secret.invalid")</script><iframe src="https://secret.invalid">hidden</iframe><p onclick="attack()">Visible <img src="https://secret.invalid/private.png" onerror="attack()" alt="diagram"></p><a href="javascript:attack()">label</a>'
    result=html_to_markdown(source)
    assert 'secret.invalid' not in result and 'attack' not in result and 'hidden' not in result
    assert 'Visible' in result and 'diagram' in result and 'label' in result
    assert '![' not in result and '<img' not in result


def test_clipboard_literal_markdown_characters_do_not_acquire_hidden_formatting():
    result=html_to_markdown('<p>*literal* [label](javascript:attack) &lt;img src=x&gt;</p>')
    assert '\\*literal\\*' in result and '\\[label\\]' in result and '\\<img' in result
    preview=preview_html(result)
    assert '<em>literal</em>' not in preview and '&lt;img src=x&gt;' in preview


@pytest.mark.parametrize('source',['x'*(MAX_HTML+1),'<div>'*70+'x'+'</div>'*70,
    '<br>'*5000,'a'*(MAX_TEXT+1)],ids=['html-size','depth','nodes','text-size'])
def test_hostile_oversized_or_deep_clipboard_html_is_rejected(source):
    with pytest.raises(ValueError):html_to_markdown(source)


def test_malformed_clipboard_is_bounded_and_preserves_visible_content():
    result=html_to_markdown('<p><strong>hello</p>after<em>world')
    assert 'hello' in result and 'after' in result and 'world' in result


class PreviewAudit(HTMLParser):
    def __init__(self):
        super().__init__();self.tags=[];self.attrs=[]
    def handle_starttag(self,tag,attrs):
        self.tags.append(tag);self.attrs.extend(attrs)


def test_preview_escapes_html_and_has_no_active_or_remote_loading_surfaces():
    text='<script>alert(1)</script> <img src="https://secret.invalid" onerror=attack()>\n![remote](https://secret.invalid/image.png)\n[label](https://example.com)\n[bad](javascript:attack)\nhttps://example.com/plain'
    rendered=preview_html(text);audit=PreviewAudit();audit.feed(rendered)
    assert not set(audit.tags)&{'script','img','iframe','object','embed','style','link','base','video','audio','a'}
    assert not any(name in ('href','src','srcdoc','style') or name.startswith('on') for name,_ in audit.attrs)
    assert '&lt;script&gt;' in rendered and '&lt;img' in rendered
    assert 'md-link' in rendered and 'https://example.com/plain' in rendered


def test_preview_supports_composer_markdown_features_without_resources():
    text='# Heading\n> Quote **bold**\n- [ ] task\n- [x] done\n1. first\n2. second\n***both*** and `x < y`\n```python\n<script>literal</script>\n```'
    rendered=preview_html(text)
    assert '<h1>Heading</h1>' in rendered and '<blockquote>' in rendered
    assert '<strong>bold</strong>' in rendered and '<strong><em>both</em></strong>' in rendered
    assert '☐ task' in rendered and '☑ done' in rendered and '<ol>' in rendered
    assert '<code>x &lt; y</code>' in rendered and '&lt;script&gt;literal&lt;/script&gt;' in rendered


def test_unclosed_code_fence_cannot_reactivate_html():
    result=preview_html('```\n</code><img src="https://secret.invalid">')
    audit=PreviewAudit();audit.feed(result)
    assert 'img' not in audit.tags and '&lt;/code&gt;&lt;img' in result
