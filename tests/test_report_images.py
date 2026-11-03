"""Report compression keeps decoded pixels, gradients and figure dimensions."""
import io

import pytest
from PIL import Image

from wayricad_runtime.report_images import optimize_png, figure_png


def encoded(image):
    stream=io.BytesIO()
    image.save(stream,format='PNG',compress_level=0)
    return stream.getvalue()


@pytest.mark.parametrize('kind',['opaque','gradient','transparent','palette','gray','colour_key'])
def test_png_compression_preserves_all_pixels_and_size(kind):
    if kind=='palette':
        image=Image.new('P',(80,60));image.putpalette([i for i in range(256) for _ in range(3)])
        image.putdata([i%256 for i in range(4800)])
    elif kind=='colour_key':
        image=Image.new('RGB',(80,60),(10,20,30));image.info['transparency']=(10,20,30)
    elif kind=='gray':
        image=Image.new('L',(80,60));image.putdata([i%256 for i in range(4800)])
    else:
        image=Image.new('RGBA',(80,60))
        image.putdata([(x%256,(x//256)%256,x%17,255 if kind!='transparent' else x%256)
                       if kind!='opaque' else (10 if x%2 else 200,20,30,255) for x in range(4800)])
    original=encoded(image)
    optimized=optimize_png(original)
    with Image.open(io.BytesIO(optimized)) as result:
        assert result.size==image.size
        assert result.convert('RGBA').tobytes()==image.convert('RGBA').tobytes()
        if kind=='opaque':assert result.mode=='P'
        if kind=='gradient':assert result.mode=='RGB'  # More than 256 exact colours.
        if kind=='transparent':assert result.mode=='RGBA'
    assert len(optimized)<len(original)
    assert len(optimize_png(optimized))<=len(optimized)


def test_figure_compression_keeps_resolution_and_gradient_pixels():
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    figure=Figure(figsize=(2,1),dpi=80);FigureCanvasAgg(figure)
    figure.add_subplot().imshow([[0,.1,.7],[.2,.6,1]],interpolation='bilinear')
    original=io.BytesIO();figure.savefig(original,format='png',dpi=80)
    optimized=figure_png(figure,dpi=80)
    with Image.open(io.BytesIO(original.getvalue())) as before,Image.open(io.BytesIO(optimized)) as after:
        assert after.size==before.size==(160,80)
        assert after.info['dpi']==before.info['dpi']
        assert before.convert('RGBA').tobytes()==after.convert('RGBA').tobytes()
    assert len(optimized)<=len(original.getvalue())
