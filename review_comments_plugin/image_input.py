"""Bound image-file decoding before passing local bytes to the native GUI."""
import struct

MAX_BYTES = 4 * 1024 * 1024
MAX_PIXELS = 16 * 1024 * 1024


def image_size(data):
    if not isinstance(data, bytes) or not 0 < len(data) <= MAX_BYTES:
        raise ValueError('Choose a PNG or JPEG image no larger than 4 MiB.')
    if data.startswith(b'\x89PNG\r\n\x1a\n'):
        if len(data) < 33 or data[8:16] != b'\0\0\0\rIHDR':
            raise ValueError('Invalid PNG header.')
        width, height = struct.unpack('>II', data[16:24])
    elif data.startswith(b'\xff\xd8'):
        offset = 2
        width = height = 0
        while offset < len(data):
            if data[offset] != 255:
                raise ValueError('Invalid JPEG header.')
            while offset < len(data) and data[offset] == 255:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xd9, 0xda):
                break
            if marker == 1 or 0xd0 <= marker <= 0xd7:
                continue
            if offset + 2 > len(data):
                break
            size = int.from_bytes(data[offset:offset+2], 'big')
            if size < 2 or offset + size > len(data):
                break
            if marker in (0xc0, 0xc1, 0xc2):
                if size < 8:
                    break
                height, width = struct.unpack('>HH', data[offset+3:offset+7])
                break
            offset += size
    else:
        raise ValueError('Drop PNG or JPEG image files. Other files are never uploaded automatically.')
    if not width or not height or width * height > MAX_PIXELS or max(width, height) > 16384:
        raise ValueError('Image dimensions are invalid or exceed the 16 megapixel limit.')
    return width, height
