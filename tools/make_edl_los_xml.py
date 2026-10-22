#!/usr/bin/env python3
"""Generate an fh_loader XML that writes images directly into the logical
partitions inside the `super` physical partition (EDL / firehose).

Usage:
  python make_edl_los_xml.py <super.img> <super_start_sector_4096> <out.xml> name=image [...]
     --verify-only  : only print resolved offsets
"""
import sys, os, struct

EROFS = 0xE0F5E1E2
SECTOR_4096 = 4096


def load_meta(path):
    with open(path, 'rb') as f:
        blob = f.read(4 * 1024 * 1024)
    idx = blob.find(b'\x30PLA')
    header_size = struct.unpack_from('<I', blob, idx + 8)[0]
    part_off, part_num, part_esz = struct.unpack_from('<III', blob, idx + 80)
    ext_off, ext_num, ext_esz = struct.unpack_from('<III', blob, idx + 92)
    meta_start = idx + header_size
    parts = {}
    for i in range(part_num):
        base = meta_start + part_off + i * part_esz
        name = blob[base:base + 36].split(b'\x00')[0].decode('utf-8', 'replace')
        first_ext, num_ext = struct.unpack_from('<II', blob, base + 40)
        parts[name] = (first_ext, num_ext)
    exts = []
    for i in range(ext_num):
        base = meta_start + ext_off + i * ext_esz
        num_sectors = struct.unpack_from('<Q', blob, base)[0]
        tdata = struct.unpack_from('<Q', blob, base + 12)[0] if ext_esz == 24 else struct.unpack_from('<Q', blob, base + 16)[0]
        exts.append((num_sectors, tdata))
    return parts, exts


def main():
    super_img, super_start, out_xml = sys.argv[1], int(sys.argv[2]), sys.argv[3]
    pairs = [a.split('=', 1) for a in sys.argv[4:] if '=' in a]
    parts, exts = load_meta(super_img)

    entries = []
    print(f'super start sector (4096B units) = {super_start}')
    for name, img in pairs:
        if name not in parts:
            print(f'!! {name} not in super metadata')
            return 1
        first, num = parts[name]
        isz = os.path.getsize(img)
        # sanity: check image magic (raw erofs has magic at +1024)
        with open(img, 'rb') as f:
            f.seek(1024)
            magic = struct.unpack('<I', f.read(4))[0]
        _ns, tdata = exts[first]
        abs_sector = super_start + tdata // 8
        cap = sum(exts[first + k][0] for k in range(num)) * 512
        need = (isz + SECTOR_4096 - 1) // SECTOR_4096
        print(f'  {name:<14} img={isz/1024**2:8.1f}MB magic={magic:08x}{" EROFS" if magic == EROFS else ""} '
              f'-> abs_start_sector={abs_sector} sectors={need} cap={cap/1024**2:.1f}MB fits={isz <= cap}')
        if isz > cap:
            print(f'!! {img} bigger than partition capacity')
            return 1
        entries.append((name, img, abs_sector, need))

    if '--verify-only' in sys.argv:
        return 0

    with open(out_xml, 'w') as f:
        f.write('<?xml version="1.0" ?>\n<data>\n')
        for name, img, start, need in entries:
            f.write(f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                    f'filename="{img}" label="{name}" num_partition_sectors="{need}" '
                    f'physical_partition_number="0" start_sector="{start}" />\n')
        f.write('</data>\n')
    print(f'wrote {out_xml}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
