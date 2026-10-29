import struct

import pytest

from review_comments_plugin.image_input import image_size, MAX_BYTES


def png(width, height):
    return b'\x89PNG\r\n\x1a\n' + b'\0\0\0\rIHDR' + struct.pack('>II', width, height) + b'\x08\x02\0\0\0' + b'\0'*4


def test_png_dimensions_checked_before_decode():
    assert image_size(png(640, 480)) == (640, 480)


def test_jpeg_dimensions_checked_before_decode():
    data = b'\xff\xd8\xff\xc0\0\x0b\x08' + struct.pack('>HH', 240, 320) + b'\x01\x01\x11\0'
    assert image_size(data) == (320, 240)


@pytest.mark.parametrize('data', [png(0, 1), png(20000, 20000), b'<svg/>', b'\xff\xd8',
                                b'\xff\xd8\xff\xc0\0\x01', b'x'*(MAX_BYTES+1)],
                         ids=['zero-size', 'oversized-dimensions', 'not-image', 'truncated', 'invalid-segment', 'oversized-file'])
def test_invalid_or_oversized_inputs_rejected(data):
    with pytest.raises(ValueError):
        image_size(data)
