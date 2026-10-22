#!/usr/bin/env python3
"""Android sparse image -> raw image (pure python, no dependencies).

Usage: python sparse2raw.py <in.simg> <out.img>

Sparse header (little endian):
  magic           u32  0xED26FF3A
  major_version   u16
  minor_version   u16
  file_hdr_sz     u16
  chunk_hdr_sz    u16
  blk_sz          u32
  total_blks      u32
  total_chunks    u32
  image_checksum  u32

Chunk types:
  RAW   0xCAC1  1 header + blk_sz*chunk_sz bytes
  FILL  0xCAC2  1 header + 4 bytes pattern
  DONT  0xCAC3  1 header only
  CRC32 0xCAC4  1 header + 4 bytes crc
"""
import sys
import struct

SPARSE_MAGIC = 0xED26FF3A
CHUNK_RAW = 0xCAC1
CHUNK_FILL = 0xCAC2
CHUNK_DONT = 0xCAC3
CHUNK_CRC = 0xCAC4


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, 'rb') as f:
        hdr = f.read(28)
        magic, major, _minor, file_hdr_sz, chunk_hdr_sz, blk_sz, total_blks, total_chunks, _crc = \
            struct.unpack('<IHHHHIIII', hdr)
        if magic != SPARSE_MAGIC:
            # already raw -> copy
            print('not a sparse image, copying as-is')
            with open(dst, 'wb') as o:
                o.write(hdr)
                while True:
                    b = f.read(1 << 20)
                    if not b:
                        break
                    o.write(b)
            return 0
        print(f'sparse: blk_sz={blk_sz} total_blks={total_blks} chunks={total_chunks} '
              f'expected_raw={total_blks * blk_sz / 1024**2:.1f}MB')
        f.seek(file_hdr_sz)
        written = 0
        with open(dst, 'wb') as o:
            for i in range(total_chunks):
                ch = f.read(12)
                if len(ch) < 12:
                    print(f'!! truncated chunk header at #{i}')
                    return 1
                ctype, _res, chunk_sz, total_sz = struct.unpack('<HHII', ch)
                # skip the rest of the chunk header if it is bigger than 12
                if chunk_hdr_sz > 12:
                    f.read(chunk_hdr_sz - 12)
                if ctype == CHUNK_RAW:
                    left = chunk_sz * blk_sz
                    while left:
                        b = f.read(min(left, 1 << 20))
                        if not b:
                            print(f'!! truncated RAW chunk #{i}')
                            return 1
                        o.write(b)
                        left -= len(b)
                    written += chunk_sz * blk_sz
                elif ctype == CHUNK_FILL:
                    pattern = f.read(4)
                    o.write(pattern * (chunk_sz * blk_sz // 4))
                    written += chunk_sz * blk_sz
                elif ctype == CHUNK_DONT:
                    o.seek(chunk_sz * blk_sz, 1)
                    written += chunk_sz * blk_sz
                elif ctype == CHUNK_CRC:
                    f.read(4)
                else:
                    print(f'!! unknown chunk type 0x{ctype:04x} at #{i}')
                    return 1
        print(f'wrote {dst}: {written / 1024**2:.1f}MB')
    return 0


if __name__ == '__main__':
    sys.exit(main())
