#!/usr/bin/env python3
"""Pure-python LZ4 (legacy frame 0x184C2102) decoder + cpio (newc) extractor.

Supports the two formats AOSP uses for vendor_boot vendor_ramdisk:
  - legacy frame magic 0x184C2102 (lz4 -l)
  - modern frame magic 0x184D2204 (lz4)
  - bare cpio (uncompressed)
"""
import struct, sys, os

def lz4_block_decompress(src, expected=None):
    dst = bytearray()
    i, n = 0, len(src)
    while i < n:
        token = src[i]; i += 1
        lit = token >> 4
        if lit == 15:
            while True:
                b = src[i]; i += 1
                lit += b
                if b != 255:
                    break
        dst += src[i:i+lit]; i += lit
        if i >= n:
            break
        off = src[i] | (src[i+1] << 8); i += 2
        ml = token & 0x0F
        if ml == 15:
            while True:
                b = src[i]; i += 1
                ml += b
                if b != 255:
                    break
        ml += 4
        start = len(dst) - off
        if start < 0:
            raise ValueError('bad offset')
        for k in range(ml):
            dst.append(dst[start + k])
    return bytes(dst)

def lz4_legacy(data):
    assert data[:4] == b'\x02\x21\x4c\x18', data[:4]
    i, out = 4, bytearray()
    while i + 4 <= len(data):
        sz = struct.unpack('<I', data[i:i+4])[0]; i += 4
        if sz == 0:
            break
        if sz & 0x80000000:            # uncompressed block
            n = sz & 0x7fffffff
            out += data[i:i+n]; i += n
        else:
            out += lz4_block_decompress(data[i:i+sz])
            i += sz
    return bytes(out)

def lz4_modern(data):
    assert data[:4] == b'\x04\x22\x4d\x18'
    flg = data[4]
    i = 6
    if flg & 0x08: i += 8
    if flg & 0x01: i += 4
    i += 1  # header checksum
    out = bytearray()
    while i + 4 <= len(data):
        sz = struct.unpack('<I', data[i:i+4])[0]; i += 4
        if sz == 0:
            break
        raw = bool(sz & 0x80000000)
        n = sz & 0x7fffffff
        if raw:
            out += data[i:i+n]
        else:
            out += lz4_block_decompress(data[i:i+n])
        i += n
        if flg & 0x10: i += 4  # block checksum
    return bytes(out)

def decompress_maybe(data):
    if data[:4] == b'\x02\x21\x4c\x18':
        return lz4_legacy(data)
    if data[:4] == b'\x04\x22\x4d\x18':
        return lz4_modern(data)
    if data[:2] == b'\x1f\x8b':
        import gzip
        return gzip.decompress(data)
    return data

def cpio_entries(data):
    out, i = [], 0
    while True:
        if data[i:i+6] not in (b'070701', b'070702'):
            raise ValueError(f'bad cpio magic at {i}: {data[i:i+8]!r}')
        f = [int(data[i+6+8*k:i+6+8*(k+1)], 16) for k in range(13)]
        mode, filesize, namesize = f[1], f[6], f[11]
        name = data[i+110:i+110+namesize-1].decode('utf-8', 'replace')
        pad = (4 - ((110 + namesize) % 4)) % 4
        dstart = i + 110 + namesize + pad
        out.append((name, filesize, mode, dstart))
        i = dstart + filesize + ((4 - (filesize % 4)) % 4)
        if name == 'TRAILER!!!':
            break
    return out

def read_vendor_boot(path):
    b = open(path, 'rb').read()
    assert b[:8] == b'VNDRBOOT', b[:8]
    page = struct.unpack('<I', b[12:16])[0]
    rd_size = struct.unpack('<I', b[24:28])[0]
    return b, page, page, rd_size

if __name__ == '__main__':
    path = sys.argv[1]
    want = sys.argv[2] if len(sys.argv) > 2 else None
    outdir = sys.argv[3] if len(sys.argv) > 3 else None
    b, page, off, size = read_vendor_boot(path)
    raw = b[off:off+size]
    data = decompress_maybe(raw)
    print(f'ramdisk {size} -> {len(data)} bytes, magic {raw[:4].hex()}')
    for name, sz, mode, ds in cpio_entries(data):
        print(f'  {sz:>9} {oct(mode)[2:]:>6} {name}')
        if outdir and sz and not name.startswith('TRAILER'):
            p = os.path.join(outdir, name.lstrip('./').replace('/', '_'))
            with open(p, 'wb') as fh:
                fh.write(data[ds:ds+sz])
            print(f'      -> {p}')
