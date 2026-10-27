"""Native-help presentation from canonical HTML, without network image reads."""
from functools import lru_cache
from html import escape,unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import struct
import textwrap
from urllib.parse import urlsplit,unquote


@lru_cache(maxsize=256)
def _dimensions(path,mtime,size):
    with Path(path).open('rb') as source:data=source.read(1024*1024)
    if data[:8]==b'\x89PNG\r\n\x1a\n' and len(data)>=24:return struct.unpack('>II',data[16:24])
    if data[:6] in (b'GIF87a',b'GIF89a') and len(data)>=10:return struct.unpack('<HH',data[6:10])
    if data[:2]==b'BM' and len(data)>=26:
        width,height=struct.unpack('<ii',data[18:26]);return abs(width),abs(height)
    if data[:2]==b'\xff\xd8':
        index=2
        while index+4<=len(data):
            if data[index]!=255:index+=1;continue
            while index<len(data) and data[index]==255:index+=1
            if index>=len(data):break
            marker=data[index];index+=1
            if marker in (0xD8,0xD9,0x01) or 0xD0<=marker<=0xD7:continue
            if index+2>len(data):break
            length=int.from_bytes(data[index:index+2],'big')
            if length<2:break
            if marker in {0xC0,0xC1,0xC2,0xC3,0xC5,0xC6,0xC7,0xC9,0xCA,0xCB,0xCD,0xCE,0xCF} and index+7<=len(data):
                height,width=struct.unpack('>HH',data[index+3:index+7]);return width,height
            index+=length
    return None


def image_dimensions(path):
    """Read bounded local image metadata; no Pillow or GUI dependency required."""
    try:
        path=Path(path);stat=path.stat();result=_dimensions(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
        return result if result and min(result)>0 else None
    except (OSError,ValueError,struct.error):return None


def fitted_size(width,height,limit):
    """Use one scale for both axes, never upscale or produce zero dimensions."""
    scale=min(1.,max(1.,float(limit))/width)
    return max(1,round(width*scale)),max(1,round(height*scale))


def _image_path(src,base):
    try:
        parsed=urlsplit(src or '')
        if parsed.scheme or parsed.netloc:return None
        path=(base/unquote(parsed.path)).resolve()
        return path if path.is_relative_to(base) and path.is_file() else None
    except (OSError,ValueError,RuntimeError):return None


class _Images(HTMLParser):
    def __init__(self,markup):
        super().__init__(convert_charrefs=False);self.records=[];self.anchors=[];self.offsets=[0]
        self.offsets.extend(match.end() for match in re.finditer('\n',markup));self.feed(markup)
    def handle_starttag(self,tag,attrs):
        line,column=self.getpos();start=self.offsets[line-1]+column;raw=self.get_starttag_text()
        attributes=dict(attrs)
        if attributes.get('id') and attributes.get('name')!=attributes['id']:self.anchors.append((start,attributes['id']))
        if tag=='img':self.records.append((start,start+len(raw),attributes))
    handle_startendtag=handle_starttag


def responsive_html(markup,base_dir,available_width,reader=image_dimensions):
    """Resize local screenshot figures from canonical markup, retaining icons.

    Every figure uses one common width, bounded by its natural pixels and any
    explicit canonical width. Remote/out-of-scope images are omitted only in
    this native fallback. Repeated calls always use the untouched source HTML.
    """
    base=Path(base_dir).resolve();width=max(1,int(available_width));parsed=_Images(markup)
    figures=[];records=[]
    for start,end,attrs in parsed.records:
        path=_image_path(attrs.get('src',''),base);dimensions=reader(path) if path is not None else None
        limit=dimensions[0] if dimensions else 0
        declared=(attrs.get('width') or '').strip().lower()
        declared_width=int(declared.removesuffix('px')) if re.fullmatch(r'\d+(?:px)?',declared) else None
        figure=dimensions is not None and dimensions[0]>=320 and (declared_width is None or declared_width>=320)
        if declared_width is not None and declared_width>0:limit=min(limit,declared_width)
        if figure:figures.append(limit)
        records.append((start,end,attrs,path,dimensions,figure))
    common=min([width,*figures]) if figures else width
    changes=[]
    for start,end,attrs,path,dimensions,figure in records:
        if path is None or dimensions is None:
            replacement='<span>[Image omitted: '+escape(attrs.get('alt') or 'external or unavailable image')+']</span>'
        else:
            attrs=dict(attrs,src=path.as_uri())
            if dimensions:
                target=common if figure else min(width,dimensions[0])
                if not figure and (attrs.get('width') or '').isdigit() and int(attrs['width'])>0:target=min(target,int(attrs['width']))
                shown=fitted_size(*dimensions,target);attrs.update(width=str(shown[0]),height=str(shown[1]))
            replacement='<img '+ ' '.join(escape(key,quote=True)+'="'+escape(value or '',quote=True)+'"' for key,value in attrs.items())+'>'
            if figure:replacement='<div align="center">'+replacement+'</div>'
        changes.append((start,end,replacement))
    changes.extend((position,position,'<a name="'+escape(name,quote=True)+'"></a>') for position,name in parsed.anchors)
    result=markup
    for start,end,replacement in sorted(changes,reverse=True):result=result[:start]+replacement+result[end:]
    # wx.html does not implement browser CSS max-width/white-space rules. Keep
    # examples readable by wrapping their presentation instead of forcing a
    # horizontal document wider than its screenshots.
    columns=max(16,int(width/10.5))
    def pre(match):
        content=re.sub(r'</?code\b[^>]*>','',match.group(1),flags=re.I)
        lines=[]
        for line in unescape(content).splitlines():
            lines.extend(textwrap.wrap(line,columns,replace_whitespace=False,drop_whitespace=False) or [''])
        return '<div><tt>'+'<br>'.join(escape(line).replace(' ','&nbsp;') for line in lines)+'</tt></div>'
    return re.sub(r'<pre\b[^>]*>(.*?)</pre\s*>',pre,result,flags=re.I|re.S)
