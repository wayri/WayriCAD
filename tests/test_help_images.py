"""Native help figures retain proportions and packaged paths on every reflow."""
from html.parser import HTMLParser
from pathlib import Path
import struct
import tempfile
import unittest

from wayricad_runtime.help_images import responsive_html,image_dimensions,fitted_size


class Images(HTMLParser):
    def __init__(self,text):super().__init__();self.images=[];self.feed(text)
    def handle_starttag(self,tag,attrs):
        if tag=='img':self.images.append(dict(attrs))


class HelpImageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        for name,width,height in [('wide.png',1280,720),('tall.png',1000,1000),('icon.png',96,96)]:
            (self.root/name).write_bytes(b'\x89PNG\r\n\x1a\n'+b'\0'*8+struct.pack('>II',width,height))
        self.canonical='<h2 id="tail">Help</h2><img src="wide.png" width="1280" height="900"><img src="tall.png"><img src="icon.png" width="24"><pre>'+('verylongargument'*20)+'</pre>'

    def test_png_and_proportional_common_width_without_upscaling(self):
        self.assertEqual(image_dimensions(self.root/'wide.png'),(1280,720))
        for width in (432,852,1352):
            rendered=responsive_html(self.canonical,self.root,width);rows=Images(rendered).images
            first,second,icon=rows
            self.assertEqual(first['width'],second['width'])
            self.assertLessEqual(int(first['width']),min(width,1000))
            self.assertAlmostEqual(int(first['height'])/int(first['width']),720/1280,delta=1/int(first['width']))
            self.assertEqual(icon['width'],'24');self.assertEqual(icon['height'],'24')
            self.assertNotIn('<pre>',rendered)
            self.assertIn('<a name="tail"></a>',rendered)
            self.assertEqual((self.root / "wide.png").resolve().as_uri(), first["src"])
        self.assertEqual(responsive_html(self.canonical,self.root,432),responsive_html(self.canonical,self.root,432))
        self.assertIn('width="1280" height="900"',self.canonical)

    def test_remote_and_out_of_scope_images_never_read(self):
        calls=[]
        result=responsive_html('<img src="https://example.test/photo.png"><img src="../secret.png">',self.root,400,
                               reader=lambda path:calls.append(path))
        self.assertEqual(calls,[]);self.assertNotIn('<img',result);self.assertIn('Image omitted',result)

    def test_inline_thumbnail_does_not_shrink_screenshots(self):
        text='<img src="wide.png"><img src="tall.png" width="96">'
        rows=Images(responsive_html(text,self.root,800)).images
        self.assertEqual(rows[0]['width'],'800');self.assertEqual(rows[1]['width'],'96')
        self.assertEqual(fitted_size(100,50,300),(100,50))

    def test_jpeg_metadata_and_bad_headers(self):
        jpeg=self.root/'sample.jpg'
        jpeg.write_bytes(b'\xff\xd8\xff\xc0'+b'\0\x11\x08'+struct.pack('>HH',300,600)+b'\0'*10)
        self.assertEqual(image_dimensions(jpeg),(600,300))
        self.assertIsNone(image_dimensions(self.root/'absent.png'))


if __name__=='__main__':unittest.main()
