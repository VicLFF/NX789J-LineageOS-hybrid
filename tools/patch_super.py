#!/usr/bin/env python3
"""Parse Android dynamic-partition (super) LP metadata and optionally patch
logical partitions in place with new images.

Usage:
  python patch_super.py <super.img> --list
  python patch_super.py <super.img> --verify
  python patch_super.py <super.img> --patch system_a=system.img ...
"""
import struct, sys, os

MAGIC = 0x414C5030  # LP_METADATA_GEOMETRY_MAGIC little endian "0PLA"
EROFS_MAGIC = 0xE0F5E1E2


def load_meta(path, sector=512):
    with open(path, 'rb') as f:
        blob = f.read(4 * 1024 * 1024)
    idx = blob.find(b'\x30PLA')
    if idx < 0:
        raise RuntimeError('LP magic not found')
    header_size = struct.unpack_from('<I', blob, idx + 8)[0]
    part_off, part_num, part_esz = struct.unpack_from('<III', blob, idx + 80)
    ext_off, ext_num, ext_esz = struct.unpack_from('<III', blob, idx + 92)
    meta_start = idx + header_size
    parts = {}
    order = []
    for i in range(part_num):
        base = meta_start + part_off + i * part_esz
        name = blob[base:base + 36].split(b'\x00')[0].decode('utf-8', 'replace')
        first_ext, num_ext = struct.unpack_from('<II', blob, base + 40)
        parts[name] = (first_ext, num_ext)
        order.append(name)
    exts = []
    for i in range(ext_num):
        base = meta_start + ext_off + i * ext_esz
        num_sectors = struct.unpack_from('<Q', blob, base)[0]
        target_type = struct.unpack_from('<I', blob, base + 8)[0]
        if ext_esz == 24:
            tdata, tsource = struct.unpack_from('<QI', blob, base + 12)
        else:
            tdata, tsource = struct.unpack_from('<QIQ', blob, base + 16)[:2]
        exts.append((num_sectors, target_type, tdata, tsource))
    return parts, order, exts, sector


def main():
    path = sys.argv[1]
    args = sys.argv[2:]
    sector = 512
    mode = 'list'
    patches = []
    for a in args:
        if a == '--list':
            mode = 'list'
        elif a == '--verify':
            mode = 'verify'
        elif a == '--patch':
            mode = 'patch'
        elif a.startswith('--sector='):
            sector = int(a.split('=')[1])
        elif '=' in a:
            patches.append(a.split('=', 1))

    parts, order, exts, sector = load_meta(path, sector)
    total = os.path.getsize(path)
    print(f'super={path} size={total/1024**3:.2f} GiB  partitions={len(order)} extents={len(exts)} (sector={sector})')

    for name in order:
        if not name.endswith('_a'):
            continue
        first, num = parts[name]
        sz = sum(exts[first + k][0] for k in range(num)) * sector
        extsizes = [exts[first + k][0] * sector for k in range(num)]
        print(f'  {name:<16} {sz/1024**2:9.1f} MB  extents={num} -> {[f"{e/1024**2:.1f}MB@{exts[first+k][2]*sector/1024**3:.2f}G" for k,e in enumerate(extsizes)]}')

    if mode == 'verify':
        with open(path, 'rb') as f:
            for name in order:
                if not name.endswith('_a'):
                    continue
                first, num = parts[name]
                off = exts[first][2] * sector
                f.seek(off + 1024)
                m = struct.unpack('<I', f.read(4))[0]
                print(f'  {name:<16} magic@+1024 = {m:08x} {"EROFS" if m == EROFS_MAGIC else "??"}')

    if mode == 'patch':
        mode_rw = 'r+b'
        with open(path, mode_rw) as f:
            for name, img in patches:
                if name not in parts:
                    print(f'!! {name} not in metadata')
                    continue
                first, num = parts[name]
                isz = os.path.getsize(img)
                cap = sum(exts[first + k][0] for k in range(num)) * sector
                print(f'patching {name}: image={isz/1024**2:.1f} MB capacity={cap/1024**2:.1f} MB')
                if isz > cap:
                    print(f'!! {img} does not fit in {name}')
                    continue
                done = 0
                with open(img, 'rb') as s:
                    for k in range(num):
                        nsect, ttype, tdata, tsource = exts[first + k]
                        cap_ext = nsect * sector
                        n = min(cap_ext, isz - done)
                        if n <= 0:
                            break
                        f.seek(tdata * sector)
                        left = n
                        while left > 0:
                            chunk = s.read(min(left, 8 * 1024 * 1024))
                            if not chunk:
                                raise RuntimeError('unexpected EOF')
                            f.write(chunk)
                            left -= len(chunk)
                        done += n
                print(f'   wrote {done/1024**2:.1f} MB into {name}')
            f.flush()
            os.fsync(f.fileno())
        print('patch done')


if __name__ == '__main__':
    main()
