#!/usr/bin/env python3
"""在 vendor_a.img (EROFS 原始镜像) 里定位 libgdix_tsa.so 并原地打补丁。

补丁目标：ParseFramedata 里那条 `b.ne 0x7c61c`（帧头校验失败就丢弃整帧），
.so 内偏移 0x7c5bc，原始字节 01 03 00 54，改成 nop (1f 20 03 d5)。

用法:
  python patch_tsa_in_vendor.py <vendor_a.img> <libgdix_tsa.so> [--patch <out.img>]
"""
import sys, hashlib

SIG_OFF    = 0x7c544          # ParseFramedata 函数入口
SIG_LEN    = 64
TARGET_OFF = 0x7c5bc          # b.ne 指令
OLD        = bytes.fromhex("01030054")
NEW        = bytes.fromhex("1f2003d5")   # nop


def main():
    img, so = sys.argv[1], sys.argv[2]
    out = None
    if "--patch" in sys.argv:
        out = sys.argv[sys.argv.index("--patch") + 1]

    with open(so, "rb") as f:
        f.seek(SIG_OFF)
        sig = f.read(SIG_LEN)
    print(f"从 {so} 取签名 @0x{SIG_OFF:x}: {sig[:16].hex()}... ({len(sig)} 字节)")

    with open(img, "rb") as f:
        data = f.read()
    print(f"镜像大小 {len(data):,} 字节")

    hits, start = [], 0
    while True:
        i = data.find(sig, start)
        if i < 0:
            break
        hits.append(i)
        start = i + 1
    print(f"签名命中 {len(hits)} 处: {[hex(h) for h in hits]}")
    if len(hits) != 1:
        print("!! 命中数不为 1，不能安全定位，终止")
        return 1

    base = hits[0] - SIG_OFF
    tgt  = base + TARGET_OFF
    print(f"libgdix_tsa.so 数据起点 = 0x{base:x}")
    print(f"目标指令偏移        = 0x{tgt:x}")
    cur = data[tgt:tgt + 4]
    print(f"当前字节 = {cur.hex()}  (期望 {OLD.hex()})")
    if cur != OLD:
        print("!! 字节不匹配，终止")
        return 1

    if out:
        buf = bytearray(data)
        buf[tgt:tgt + 4] = NEW
        with open(out, "wb") as f:
            f.write(buf)
        print(f"已写补丁镜像 {out} ({len(buf):,} 字节)")
        print(f"  md5 = {hashlib.md5(buf).hexdigest()}")
        print(f"  补丁点 = 0x{tgt:x}  {OLD.hex()} -> {NEW.hex()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
