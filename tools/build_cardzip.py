#!/usr/bin/env python3
"""Build an OrangeFox/TWRP flashable zip that writes the three LineageOS
system-side images straight into the `super` partition's logical extents.

The on-device installer parses the LP metadata itself, so the zip is
independent of which stock base is installed: it just walks the extent table
for system_a / system_ext_a / product_a and overwrites exactly those byte
ranges.  No GPT, no super metadata, no vbmeta, no boot/init_boot/vendor_boot/
dtbo/recovery is touched.

Usage:
    python build_cardzip.py                 # build the zip
    python build_cardzip.py --inspect       # show what the images look like
"""
import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, 'cardzip')
IMAGES = os.path.join(HERE, 'los')
OUTZIP = os.path.join(HERE, 'LineageOS-23.2-NX789J-cardslot.zip')

EROFS_MAGIC = 0xE0F5E1E2

UPDATE_BINARY = r'''#!/sbin/sh
# LineageOS 23.2 for nubia NX789J (RedMagic 10S Pro / Pro+)
# Base-agnostic installer: parses super's LP metadata on the device and
# overwrites only the extents that belong to system_a/system_ext_a/product_a.
# Nothing else is touched -- not the GPT, not the metadata, not vbmeta, not any
# boot image.
OUTFD=$2
ZIPFILE=$3

ui_print() { echo "ui_print $1" >&$OUTFD; echo "ui_print" >&$OUTFD; }
abort() { ui_print "  ! 错误: $1"; ui_print "  ! 已中止，未改动任何分区"; exit 1; }

# ---- 定位 super 块设备 -------------------------------------------------
SUPER=$(readlink -f /dev/block/by-name/super 2>/dev/null)
if [ ! -b "$SUPER" ]; then
  SUPER=$(readlink -f /dev/block/mapper/super 2>/dev/null)
fi
[ -b "$SUPER" ] || abort "找不到 super 分区"

ui_print "========================"
ui_print " LineageOS 23.2  NX789J"
ui_print "========================"
ui_print "  super -> $SUPER"

# ---- 读 32 位是小端字段 ------------------------------------------------
u32() { dd if="$SUPER" bs=1 skip=$1 count=4 2>/dev/null | od -An -tu4 | tr -d " \n"; }
u64() { echo $(( $(u32 "$1") + $(u32 $(( $1 + 4 ))) * 4294967296 )); }

# ---- 找 LP 元数据头 ----------------------------------------------------
META=""
for off in 12288 8192 16384 4096; do
  m=$(dd if="$SUPER" bs=1 skip=$off count=4 2>/dev/null | od -An -tx1 | tr -d " \n")
  if [ "$m" = "30504c41" ]; then META=$off; break; fi
done
[ -n "$META" ] || abort "没找到 super 的 LP 元数据头"
ui_print "  元数据头 @ $META"

HDRSZ=$(u32 $(( META + 8 )))
P_OFF=$(u32 $(( META + 80 ))); P_NUM=$(u32 $(( META + 84 ))); P_ESZ=$(u32 $(( META + 88 )))
E_OFF=$(u32 $(( META + 92 ))); E_NUM=$(u32 $(( META + 96 ))); E_ESZ=$(u32 $(( META + 100 )))
BASE=$(( META + HDRSZ ))
ui_print "  分区表 n=$P_NUM esz=$P_ESZ / extent 表 n=$E_NUM esz=$E_ESZ"
[ "$P_NUM" -gt 0 ] && [ "$P_NUM" -lt 256 ] || abort "分区表异常"
[ "$E_ESZ" = 24 ] || [ "$E_ESZ" = 32 ] || abort "extent 结构大小异常 ($E_ESZ)"

# ---- 解压镜像 ----------------------------------------------------------
TMP=/tmp/loszip
rm -rf "$TMP"; mkdir -p "$TMP/images" || abort "无法创建临时目录"
ui_print "  解压镜像 ..."
unzip -o -q "$ZIPFILE" "images/*" -d "$TMP" || abort "解压失败"
for p in system system_ext product; do
  [ -f "$TMP/images/$p.img" ] || abort "缺少 images/$p.img"
done

# ---- 卸载已挂载的逻辑分区 ---------------------------------------------
umount /system_root /system /vendor /product /system_ext /odm 2>/dev/null

# ---- 依 extent 表写出 ---------------------------------------------------
write_part() {
  want_a=$1
  img="$TMP/images/$2.img"

  i=0; first=""; num=""
  while [ $i -lt $P_NUM ]; do
    b=$(( BASE + P_OFF + i * P_ESZ ))
    nm=$(dd if="$SUPER" bs=1 skip=$b count=36 2>/dev/null | tr -d "\000")
    if [ "$nm" = "$want_a" ]; then
      first=$(u32 $(( b + 40 ))); num=$(u32 $(( b + 44 ))); break
    fi
    i=$(( i + 1 ))
  done
  [ -n "$first" ] || abort "元数据里没有 $want_a"
  [ "$num" -gt 0 ] || abort "$want_a 的 extent 数为 0"

  # 先算配额（单位: 4096 字节块 —— 用块做单位是为了避开 32 位 shell 的算术溢出）
  cap=0; k=0
  while [ $k -lt "$num" ]; do
    eb=$(( BASE + E_OFF + (first + k) * E_ESZ ))
    cap=$(( cap + $(u64 $eb) / 8 ))
    k=$(( k + 1 ))
  done
  isz=$(stat -c %s "$img")
  need=$(( (isz + 4095) / 4096 ))
  ui_print "  $want_a: 镜像 $(( isz / 1048576 ))MB / 配额 $(( cap / 256 ))MB ($num 段)"
  [ "$need" -le "$cap" ] || abort "$want_a 镜像大于配额 ($need > $cap 块)"

  off=0; k=0
  while [ $k -lt "$num" ]; do
    eb=$(( BASE + E_OFF + (first + k) * E_ESZ ))
    ns=$(u64 $eb)
    if [ "$E_ESZ" = 24 ]; then td=$(u64 $(( eb + 12 ))); else td=$(u64 $(( eb + 16 ))); fi
    abs=$(( td / 8 ))
    len=$(( ns / 8 ))
    rem=$(( (isz - off + 4095) / 4096 ))
    cnt=$len
    [ "$cnt" -gt "$rem" ] && cnt=$rem
    [ "$cnt" -le 0 ] && break
    ui_print "    -> super 偏移 $(( abs / 256 ))MB, $cnt 块"
    dd if="$img" of="$SUPER" bs=4096 skip=$(( off / 4096 )) seek=$abs count=$cnt conv=notrunc 2>/dev/null \
      || abort "写入失败: $want_a 段 $k"
    off=$(( off + cnt * 4096 ))
    [ "$off" -ge "$isz" ] && break
    k=$(( k + 1 ))
  done
  [ "$off" -ge "$isz" ] || abort "$want_a 写入不完整"
}

write_part system_a system
write_part system_ext_a system_ext
write_part product_a product

sync
ui_print "  已全部写入"

# ---- 回读校验 erofs 魔数 -----------------------------------------------
check_magic() {
  i=0
  while [ $i -lt $P_NUM ]; do
    b=$(( BASE + P_OFF + i * P_ESZ ))
    nm=$(dd if="$SUPER" bs=1 skip=$b count=36 2>/dev/null | tr -d "\000")
    case "$nm" in
      system_a|system_ext_a|product_a)
        first=$(u32 $(( b + 40 )))
        eb=$(( BASE + E_OFF + first * E_ESZ ))
        if [ "$E_ESZ" = 24 ]; then td=$(u64 $(( eb + 12 ))); else td=$(u64 $(( eb + 16 ))); fi
        abs=$(( td / 8 ))
        m=$(dd if="$SUPER" bs=4096 skip=$abs count=1 2>/dev/null | dd bs=1 skip=1024 count=4 2>/dev/null | od -An -tx1 | tr -d " \n")
        if [ "$m" = "e2e1f5e0" ]; then ui_print "    $nm erofs OK"; else ui_print "    $nm 魔数 $m 异常"; fi
        ;;
    esac
    i=$(( i + 1 ))
  done
}
check_magic

ui_print "========================"
ui_print " 写入完成"
ui_print " 下一步必须做: 返回主菜单 -> 清除"
ui_print " -> 格式化 Data 分区(输入 yes)"
ui_print " 然后重启系统"
ui_print "========================"
exit 0
'''

UPDATER_SCRIPT = '''# LineageOS 23.2 NX789J -- all installer logic lives in update-binary
ui_print("installing via update-binary");
'''

README = '''LineageOS 23.2 (Android 16) for nubia NX789J — 红魔 10S Pro / 10S Pro+

"只换系统侧"的卡刷包：它解析 super 的 LP 元数据，只覆盖 system_a /
system_ext_a / product_a 所属的字节区间。GPT、super 元数据、vbmeta、boot、
init_boot、vendor_boot、dtbo、recovery 全部不碰。

因此它与底包无关 —— 施 的澎湃 OS 包 包、ZTE 原厂包，都能直接刷。

刷入步骤
  1. 把本 zip 放到 /sdcard
  2. 重启进 OrangeFox recovery
  3. 安装 -> 选择本 zip -> 滑动确认
  4. 返回主菜单 -> 清除 -> 格式化 Data 分区（输入 yes）
  5. 重启系统，首次启动 3-10 分钟

回滚
  fastbootd 刷回底包的 system/system_ext/product，或直接跑底包
  rawprogram0-5 的 EDL 全量恢复。
'''


def inspect_images():
    for name in ('system', 'system_ext', 'product'):
        path = os.path.join(IMAGES, name + '.img')
        with open(path, 'rb') as f:
            head = f.read(4096)
        size = os.path.getsize(path)
        magic = struct.unpack_from('<I', head, 1024)[0]
        blocks = struct.unpack_from('<I', head, 1024 + 36)[0]
        print(f'{name:<11} {size:>12} B  erofs={"yes" if magic == EROFS_MAGIC else hex(magic)}  '
              f'blocks={blocks} ({blocks * 4096} B)  multiple_of_4096={size % 4096 == 0}')


def main():
    if '--inspect' in sys.argv:
        inspect_images()
        return

    ub_dir = os.path.join(STAGE, 'META-INF', 'com', 'google', 'android')
    os.makedirs(ub_dir, exist_ok=True)
    with open(os.path.join(ub_dir, 'update-binary'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(UPDATE_BINARY)
    with open(os.path.join(ub_dir, 'updater-script'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(UPDATER_SCRIPT)
    with open(os.path.join(STAGE, 'README.txt'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(README)

    imgs = {n: os.path.join(IMAGES, n + '.img') for n in ('system', 'system_ext', 'product')}
    for name, path in imgs.items():
        if not os.path.isfile(path):
            raise SystemExit(f'missing image: {path}')

    if os.path.exists(OUTZIP):
        os.remove(OUTZIP)
    with zipfile.ZipFile(OUTZIP, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for root, _dirs, files in os.walk(STAGE):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, STAGE).replace('\\', '/')
                if rel.endswith('update-binary'):
                    zi = zipfile.ZipInfo(rel)
                    zi.external_attr = 0o100755 << 16   # keep the exec bit
                    zi.compress_type = zipfile.ZIP_STORED
                    with open(full, 'rb') as src:
                        z.writestr(zi, src.read())
                else:
                    z.write(full, rel)
        for name, path in imgs.items():
            z.write(path, 'images/' + name + '.img')
    print(f'wrote {OUTZIP} ({os.path.getsize(OUTZIP) / 1024**2:.0f} MB)')


if __name__ == '__main__':
    main()
