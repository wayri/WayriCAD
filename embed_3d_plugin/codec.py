"""KiCad-native embedded payloads: Zstandard frame, Base64, SHA-256.

KiCad 10 explicitly accepts 64-character SHA-256 checksums and upgrades them to
its internal MMH3 checksum on load. No third-party Python dependency is required.
If libzstd is unavailable, valid raw-block Zstandard frames are written instead
of inventing a different encoding. That fallback increases file size.
"""
from __future__ import annotations
import base64
import ctypes
import ctypes.util
import hashlib
import os
from pathlib import Path
import struct
import sys

MAX_BYTES = 256 * 1024 * 1024

class CodecError(ValueError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def raw_frame(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise CodecError('Model exceeds 256 MiB safety limit')
    # Single-segment frame, four-byte content size, no dictionary/checksum.
    out = bytearray(b'\x28\xb5\x2f\xfd\xa0' + struct.pack('<I', len(data)))
    chunks = [data[i:i+131072] for i in range(0, len(data), 131072)] or [b'']
    for i, chunk in enumerate(chunks):
        header = (len(chunk) << 3) | int(i == len(chunks)-1)
        out.extend(header.to_bytes(3, 'little'))
        out.extend(chunk)
    return bytes(out)


def read_raw_frame(data: bytes) -> bytes:
    if len(data) < 9 or data[:5] != b'\x28\xb5\x2f\xfd\xa0':
        raise CodecError('This Zstandard frame requires a native Zstandard decoder')
    size = int.from_bytes(data[5:9], 'little')
    if size > MAX_BYTES:
        raise CodecError('Embedded data exceeds safety limit')
    pos, out = 9, bytearray()
    while True:
        if pos+3 > len(data):
            raise CodecError('Truncated Zstandard block')
        header = int.from_bytes(data[pos:pos+3], 'little'); pos += 3
        last, kind, count = header & 1, (header >> 1) & 3, header >> 3
        if count > 131072 or len(out)+count > size:
            raise CodecError('Invalid Zstandard block size')
        if kind == 0:
            if pos+count > len(data):
                raise CodecError('Truncated raw block')
            out.extend(data[pos:pos+count]); pos += count
        elif kind == 1:
            if pos >= len(data):
                raise CodecError('Truncated run-length block')
            out.extend(data[pos:pos+1]*count); pos += 1
        else:
            raise CodecError('Compressed block requires native decoder')
        if last:
            break
    if len(out) != size or pos != len(data):
        raise CodecError('Zstandard size mismatch or trailing bytes')
    return bytes(out)


class Codec:
    def __init__(self, native: bool = True):
        self.lib = None
        self.label = 'Zstandard raw-frame fallback (larger files)'
        if not native:
            return
        # Only normal loader lookup and trusted application/system locations.
        names = []
        if os.name != 'nt':
            found = ctypes.util.find_library('zstd')
            if found:
                names.append(found)
        roots = [Path(sys.executable).parent]
        mod = sys.modules.get('pcbnew')
        if mod and getattr(mod, '__file__', None):
            p = Path(mod.__file__).resolve()
            roots += [p.parent, p.parent.parent, p.parent.parent/'bin']
        if os.name == 'nt':
            for env in ('ProgramW6432', 'ProgramFiles'):
                if os.environ.get(env):
                    roots.append(Path(os.environ[env])/'KiCad'/'10.0'/'bin')
        for root in roots:
            for name in ('zstd.dll', 'libzstd.dll', 'libzstd-1.dll', 'libzstd.so.1', 'libzstd.dylib'):
                p = root/name
                if p.is_file():
                    names.append(str(p))
        for name in names:
            try:
                lib = ctypes.CDLL(name)
                lib.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
                lib.ZSTD_compressBound.restype = ctypes.c_size_t
                lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int]
                lib.ZSTD_compress.restype = ctypes.c_size_t
                lib.ZSTD_decompress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
                lib.ZSTD_decompress.restype = ctypes.c_size_t
                lib.ZSTD_getFrameContentSize.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
                lib.ZSTD_getFrameContentSize.restype = ctypes.c_ulonglong
                lib.ZSTD_isError.argtypes = [ctypes.c_size_t]
                lib.ZSTD_isError.restype = ctypes.c_uint
                self.lib = lib
                self.label = 'Zstandard compression, level 6'
                break
            except (OSError, AttributeError):
                continue

    def compress(self, data: bytes) -> bytes:
        if len(data) > MAX_BYTES:
            raise CodecError('Model exceeds 256 MiB safety limit')
        if not self.lib:
            return raw_frame(data)
        cap = self.lib.ZSTD_compressBound(len(data))
        dst = ctypes.create_string_buffer(cap)
        src = ctypes.create_string_buffer(data)
        n = self.lib.ZSTD_compress(dst, cap, src, len(data), 6)
        if self.lib.ZSTD_isError(n):
            raise CodecError('Zstandard compression failed')
        return dst.raw[:n]

    def decompress(self, data: bytes) -> bytes:
        if not self.lib:
            return read_raw_frame(data)
        src = ctypes.create_string_buffer(data)
        size = self.lib.ZSTD_getFrameContentSize(src, len(data))
        if size > MAX_BYTES:
            raise CodecError('Invalid, unknown, or excessive Zstandard content size')
        dst = ctypes.create_string_buffer(max(size, 1))
        n = self.lib.ZSTD_decompress(dst, size, src, len(data))
        if self.lib.ZSTD_isError(n) or n != size:
            raise CodecError('Zstandard decompression failed')
        return dst.raw[:n]

    def encode(self, data: bytes) -> str:
        compressed = self.compress(data)
        if self.decompress(compressed) != data:
            raise CodecError('Embedding round-trip verification failed')
        return base64.b64encode(compressed).decode('ascii')

    def decode(self, text: str) -> bytes:
        try:
            raw = base64.b64decode(''.join(text.split()), validate=True)
        except (ValueError, TypeError) as exc:
            raise CodecError('Invalid embedded Base64') from exc
        return self.decompress(raw)
