#!/usr/bin/env python3
# 检查 super.img 内各逻辑分区的文件系统类型（只读 4KB，不抽整包）
import struct, sys, os

def parse_lp(super_path):
    with open(super_path, 'rb') as f:
        blob = f.read(2 * 1024 * 1024)
    idx = blob.find(b'\x30PLA')
    if idx < 0:
        raise RuntimeError("未找到 LP metadata magic")
    header_size = struct.unpack_from('<I', blob, idx + 8)[0]
    part_off, part_num, part_esz = struct.unpack_from('<III', blob, idx + 80)
    ext_off, ext_num, ext_esz = struct.unpack_from('<III', blob, idx + 92)
    meta_start = idx + header_size
    parts = {}
    for i in range(part_num):
        base = meta_start + part_off + i * part_esz
        name = blob[base:base+36].split(b'\x00')[0].decode('utf-8', 'replace')
        first_ext, num_ext = struct.unpack_from('<II', blob, base + 40)
        parts[name] = (first_ext, num_ext)
    exts = []
    for i in range(ext_num):
        base = meta_start + ext_off + i * ext_esz
        num_sectors = struct.unpack_from('<Q', blob, base)[0]
        if ext_esz == 24:
            tdata = struct.unpack_from('<Q', blob, base + 12)[0]
        else:
            tdata = struct.unpack_from('<Q', blob, base + 16)[0]
        exts.append((num_sectors, tdata))
    return parts, exts

def identify(head):
    """head = 分区前 4096 字节"""
    if len(head) >= 0x440:
        b400 = head[0x400:0x404]
        if b400 == b'\xe2\xe1\xf5\xe0':
            return 'EROFS', f'superblock magic @0x400 = {b400.hex()}'
        if b400 == b'\x10\x20\xf5\xf2':
            return 'F2FS ', f'superblock magic @0x400 = {b400.hex()}'
        b438 = head[0x438:0x43a]
        if b438 == b'\x53\xef':
            return 'EXT4 ', f'ext4 magic @0x438 = {b438.hex()}'
        if head[0x400:0x408] == b'ANDROID!':
            return 'BOOT ', 'Android boot image'
    if head[:8] == b'\x3a\xff\x26\xed':
        return 'SPARSE', 'sparse image header'
    return 'UNKNOWN', head[:16].hex()

def main():
    super_path = sys.argv[1]
    targets = sys.argv[2:] or ['system_a', 'system_ext_a', 'product_a',
                               'vendor_a', 'odm_a', 'vendor_dlkm_a', 'system_dlkm_a']
    parts, exts = parse_lp(super_path)
    print(f"{'分区':<16}{'大小(MB)':>12}  {'类型':<8} 证据")
    print('-' * 78)
    with open(super_path, 'rb') as f:
        for name in targets:
            if name not in parts:
                print(f"{name:<16}{'-':>12}  不存在")
                continue
            first, num = parts[name]
            total = sum(exts[first + k][0] for k in range(num)) * 512
            f.seek(exts[first][1] * 512)
            head = f.read(0x1000)
            fs, ev = identify(head)
            print(f"{name:<16}{total/1024/1024:>12.1f}  {fs:<8} {ev}")

if __name__ == '__main__':
    main()
