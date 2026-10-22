#!/usr/bin/env python3
"""从 Android boot.img (header v4) 中提取纯内核 Image。

boot v4 布局:
    offset 0   : boot_img_hdr_v4 (1580 字节)
    offset 4096: kernel  (kernel_size 字节, 已按页对齐)
    ...        : ramdisk (ramdisk_size)
    ...        : boot signature

用法:
    python extract_kernel.py <boot.img> [输出路径]
"""
import os
import struct
import sys

PAGE = 4096
BOOT_MAGIC = b"ANDROID!"


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else "Image"

    size = os.path.getsize(src)
    with open(src, "rb") as f:
        hdr = f.read(PAGE)

    if hdr[:8] != BOOT_MAGIC:
        print(f"!! 魔数不符: {hdr[:8]!r} (期望 {BOOT_MAGIC!r})")
        return 1
    if hdr[40:48] != b"\x00" * 8:  # 兼容旧版本判空
        pass
    header_version = struct.unpack_from("<I", hdr, 40)[0]
    kernel_size = struct.unpack_from("<I", hdr, 8)[0]
    ramdisk_size = struct.unpack_from("<I", hdr, 16)[0]
    header_size = struct.unpack_from("<I", hdr, 20)[0]
    os_version = struct.unpack_from("<I", hdr, 44)[0]

    print(f"文件        : {src} ({size} B)")
    print(f"header_ver  : {header_version}")
    print(f"header_size : {header_size}")
    print(f"kernel_size : {kernel_size}")
    print(f"ramdisk_size: {ramdisk_size}")
    print(f"os_version  : 0x{os_version:08x}")

    if kernel_size == 0 or kernel_size > size:
        print("!! kernel_size 异常，终止")
        return 1

    with open(src, "rb") as f:
        f.seek(PAGE)
        kernel = f.read(kernel_size)

    with open(dst, "wb") as f:
        f.write(kernel)

    # 校验是否为 aarch64 Image: 0x0 处应是 ARM64 分支指令 (MZ 或 branch)
    magic = kernel[:4]
    print(f"\n已写出        : {dst} ({len(kernel)} B)")
    print(f"头部 4 字节   : {magic.hex()}  -> {'疑似 ARM64 Image' if magic[:2] == b'MZ' else '需人工确认'}")

    # 从 Image 中抽取内核版本串
    idx = kernel.find(b"Linux version ")
    if idx >= 0:
        end = kernel.find(b"\x00", idx)
        print(f"内核版本串    : {kernel[idx:end].decode('ascii', 'replace')}")
    else:
        print("内核版本串    : 未找到")
    return 0


if __name__ == "__main__":
    sys.exit(main())
