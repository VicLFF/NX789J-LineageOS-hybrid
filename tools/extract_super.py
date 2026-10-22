#!/usr/bin/env python3
# 从 super.img 抽出指定逻辑分区的原始镜像（用于 fastbootd 回滚）
# 用法: python extract_super.py <super.img> <outdir> [分区名 ...]
import struct, sys, os, time


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
        name = blob[base:base + 36].split(b'\x00')[0].decode('utf-8', 'replace')
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


def main():
    super_path, outdir = sys.argv[1], sys.argv[2]
    targets = sys.argv[3:] or ['system_a', 'system_ext_a', 'product_a']
    os.makedirs(outdir, exist_ok=True)
    parts, exts = parse_lp(super_path)
    with open(super_path, 'rb') as src:
        for name in targets:
            if name not in parts:
                print(f"{name}: 不存在，跳过")
                continue
            first, num = parts[name]
            total = sum(exts[first + k][0] for k in range(num)) * 512
            out = os.path.join(outdir, f"{name}.img")
            t0 = time.time()
            written = 0
            with open(out, 'wb') as dst:
                for k in range(num):
                    nsect, tdata = exts[first + k]
                    nbytes = nsect * 512
                    src.seek(tdata * 512)
                    left = nbytes
                    while left > 0:
                        chunk = src.read(min(left, 8 * 1024 * 1024))
                        if not chunk:
                            raise RuntimeError(f"{name}: 读到 EOF（期望 {total} 字节）")
                        dst.write(chunk)
                        left -= len(chunk)
                    written += nbytes
            dt = time.time() - t0
            print(f"{name}: {written/1024/1024:.1f} MB, {num} 个 extent, {dt:.1f}s -> {out}")


if __name__ == '__main__':
    main()
