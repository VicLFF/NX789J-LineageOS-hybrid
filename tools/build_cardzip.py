#!/usr/bin/env python3
"""build_cardzip.py —— 打一个「官方底包通用」的 LineageOS 卡刷包（nubia NX789J）。

设计要点
--------
1. **只写 system / system_ext / product**（super 里的三个逻辑分区）。
   `update-binary` 自己在设备上解析 LP 元数据，按 extent 覆盖对应字节区间，
   所以偏移永远与手机当前底包一致 —— 换个底包版本也不用改包。

2. **vendor_boot 按底包版本自动选**。
   官方底包的 `first_stage_ramdisk/fstab.qcom` 对这三个分区带 `avb=vbmeta_system`
   + `avb_keys=...`，内核会做 dm-verity 校验；写入自编镜像必然校验失败，
   表现是「亮 logo 就重启」。所以必须换成去掉 avb 的 vendor_boot。
   不同官方底包的 vendor_boot 内容不同（ramdisk/dtb 都不一样），因此包里带两份，
   安装时用**当前 vendor_boot_a 的 md5** 判断该用哪份：

       5d427b57cecc7f32a19e041ee0550bde -> 官方 11.0.14
       ccea408082a8b28b6d402ebf4a972f85 -> 官方 11.0.13
       03e9b98ad9328ec8a57a85ddcf799608 -> 已经是 11.0.14 的去 avb 版（跳过）
       e75b05fc8b79ec7969e1189ad9e05e50 -> 已经是 11.0.13 的去 avb 版（跳过）
       其它                              -> 未知底包，abort

3. **容量兜底**。写之前先比对镜像与分区配额，不够直接 abort，绝不半截写入。

用法
----
    python build_cardzip.py --inspect
    python build_cardzip.py --images <目录> --vb-1113 <img> --vb-1114 <img> --out <zip>
"""

import os
import struct
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE = os.path.join(HERE, 'cardzip')
IMAGES = os.path.join(HERE, 'los')
VB_DIR = os.path.join(HERE, 'vb')
OUTZIP = os.path.join(HERE, 'LineageOS-23.2-NX789J-cardslot.zip')

EROFS_MAGIC = 0xE0F5E1E2

# 官方底包 vendor_boot 的 md5（用于自动识别底包版本）
BASE_MD5 = {
    '5d427b57cecc7f32a19e041ee0550bde': ('images/vendor_boot_1114.img', '官方 RedMagicOS 11.0.14'),
    'ccea408082a8b28b6d402ebf4a972f85': ('images/vendor_boot_1113.img', '官方 RedMagicOS 11.0.13'),
    '03e9b98ad9328ec8a57a85ddcf799608': ('', '已经是 11.0.14 的去 avb 版本'),
    'e75b05fc8b79ec7969e1189ad9e05e50': ('', '已经是 11.0.13 的去 avb 版本'),
}

UPDATE_BINARY = r'''#!/sbin/sh
# LineageOS 23.2 (NX789J) system 侧安装脚本
OUTFD=$2
ZIPFILE=$3

ui_print() { echo "ui_print $1" >&$OUTFD; echo "ui_print" >&$OUTFD; }
abort() { ui_print "  ! 错误: $1"; ui_print "  ! 已中止，未改动任何分区"; exit 1; }

SUPER=$(readlink -f /dev/block/by-name/super 2>/dev/null)
if [ ! -b "$SUPER" ]; then
  SUPER=$(readlink -f /dev/block/bootdevice/by-name/super 2>/dev/null)
fi
[ -b "$SUPER" ] || abort "找不到 super 分区"

ui_print "========================"
ui_print " LineageOS 23.2  NX789J"
ui_print " 官方底包 11.0.13 / 11.0.14 通用"
ui_print "========================"
ui_print "  super -> $SUPER"

# ---- 小工具：从 super 里读小端整数 -------------------------------------
u32() { dd if="$SUPER" bs=1 skip=$1 count=4 2>/dev/null | od -An -tu4 | tr -d " \n"; }
u64() { echo $(( $(u32 "$1") + $(u32 $(( $1 + 4 ))) * 4294967296 )); }

# ---- 定位 LP 元数据头 --------------------------------------------------
META=""
for off in 12288 8192 16384 4096; do
  m=$(dd if="$SUPER" bs=1 skip=$off count=4 2>/dev/null | od -An -tx1 | tr -d " \n")
  if [ "$m" = "30504c41" ]; then META=$off; break; fi
done
[ -n "$META" ] || abort "找不到 LP 元数据（super 头异常）"
ui_print "  元数据头 @ $META"

HDRSZ=$(u32 $(( META + 8 )))
P_OFF=$(u32 $(( META + 80 ))); P_NUM=$(u32 $(( META + 84 ))); P_ESZ=$(u32 $(( META + 88 )))
E_OFF=$(u32 $(( META + 92 ))); E_NUM=$(u32 $(( META + 96 ))); E_ESZ=$(u32 $(( META + 100 )))
BASE=$(( META + HDRSZ ))
ui_print "  分区表 n=$P_NUM esz=$P_ESZ / extent 表 n=$E_NUM esz=$E_ESZ"

TMP=/tmp/loszip
rm -rf "$TMP"; mkdir -p "$TMP/images" || abort "无法创建临时目录"
ui_print "  解压镜像 ..."
unzip -o -q "$ZIPFILE" "images/*" -d "$TMP" || abort "解压失败"
for p in system system_ext product; do
  [ -f "$TMP/images/$p.img" ] || abort "缺少 images/$p.img"
done

umount /system_root /system /vendor /product /system_ext /odm 2>/dev/null

# ---- 写一个逻辑分区 ----------------------------------------------------
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

  # 配额用 4096 字节块为单位，避开 32 位 shell 算术溢出
  cap=0; k=0
  while [ $k -lt "$num" ]; do
    eb=$(( BASE + E_OFF + (first + k) * E_ESZ ))
    cap=$(( cap + $(u64 $eb) / 8 ))
    k=$(( k + 1 ))
  done
  isz=$(stat -c %s "$img")
  need=$(( (isz + 4095) / 4096 ))
  ui_print "  $want_a: 镜像 $(( isz / 1048576 ))MB / 配额 $(( cap / 256 ))MB ($num 段)"
  [ "$need" -le "$cap" ] || abort "$want_a 镜像大于配额 ($need > $cap 块) —— 底包不对"

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
ui_print "  三个逻辑分区已写入"

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

# ---- vendor_boot：按当前底包版本自动选 ---------------------------------
ui_print ""
ui_print "  vendor_boot 处理 ..."
VB_A=$(readlink -f /dev/block/by-name/vendor_boot_a 2>/dev/null)
[ -b "$VB_A" ] || VB_A=$(readlink -f /dev/block/bootdevice/by-name/vendor_boot_a 2>/dev/null)
if [ -b "$VB_A" ]; then
  cur=$(md5sum "$VB_A" 2>/dev/null | cut -d" " -f1)
  ui_print "    当前 md5 = $cur"
  pick=""; basename=""
  case "$cur" in
    5d427b57cecc7f32a19e041ee0550bde) pick="images/vendor_boot_1114.img"; basename="官方 RedMagicOS 11.0.14" ;;
    ccea408082a8b28b6d402ebf4a972f85) pick="images/vendor_boot_1113.img"; basename="官方 RedMagicOS 11.0.13" ;;
    03e9b98ad9328ec8a57a85ddcf799608) pick="" ;;
    e75b05fc8b79ec7969e1189ad9e05e50) pick="" ;;
    *) abort "vendor_boot 的 md5 不在已知列表：$cur
  ! 本包只支持官方 11.0.13 / 11.0.14 底包，其它底包请自行处理" ;;
  esac
  if [ -z "$pick" ]; then
    ui_print "    已是去 avb 版本，跳过"
  else
    [ -f "$TMP/$pick" ] || abort "包里缺少 $pick"
    ui_print "    识别为 $basename，写入去 avb 版本到两槽"
    for slot in a b; do
      p=$(readlink -f /dev/block/by-name/vendor_boot_$slot 2>/dev/null)
      [ -b "$p" ] || continue
      dd if="$TMP/$pick" of="$p" bs=4096 2>/dev/null || abort "写 vendor_boot_$slot 失败"
      ui_print "    vendor_boot_$slot OK"
    done
  fi
else
  ui_print "    找不到 vendor_boot 分区，跳过（系统可能起不来）"
fi

sync
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

官方 RedMagicOS 11.0.13 / 11.0.14 底包通用。

这个包做什么
  1) 解析 super 的 LP 元数据，只覆盖 system_a / system_ext_a / product_a
     所属的字节区间。GPT、super 元数据、vbmeta、boot、init_boot、dtbo、
     recovery 全部不碰。
  2) 用「当前 vendor_boot_a 的 md5」判断你的底包版本，自动写入对应的
     「去掉 avb 校验」的 vendor_boot（a/b 两槽）。

为什么要换 vendor_boot
  官方底包的 first_stage_ramdisk/fstab.qcom 里，system / system_ext / product
  三条都带 avb=vbmeta_system 和 avb_keys=...，内核会用 dm-verity 校验这三个
  分区。写入自己编译的镜像必然校验失败，init 挂不上 /system，表现就是
  「亮 logo 然后重启」。去掉这些参数（8154 -> 7062 字节）才能起。

刷入步骤
  1. 把本 zip 放到 /sdcard
  2. 重启进 OrangeFox（或 TWRP）
  3. 安装 -> 选择本 zip -> 滑动确认
     安装日志里会打印「识别为 官方 RedMagicOS 11.0.14」这类字样
  4. 返回主菜单 -> 清除 -> 格式化 Data 分区（输入 yes）
  5. 重启系统，首次启动 3-10 分钟

如果安装直接 abort
  * 「镜像大于配额」或「vendor_boot 的 md5 不在已知列表」
    -> 你的底包不是官方 11.0.13 / 11.0.14。本包不支持，请先恢复成官方底包。
  * 「找不到 super 分区」
    -> 不是 NX789J，或者 recovery 太老（需要能读 /dev/block/by-name）。

回滚
  用 ZTE 工具箱的官方全分区备份跑 rawprogram0-5 全量恢复（约 60 秒），
  或只把 system/system_ext/product/vendor_boot 换回官方镜像。
'''


def inspect_images(images_dir):
    for name in ('system', 'system_ext', 'product'):
        path = os.path.join(images_dir, name + '.img')
        if not os.path.isfile(path):
            print(f'{name:<11} MISSING ({path})')
            continue
        with open(path, 'rb') as f:
            head = f.read(2048)
        size = os.path.getsize(path)
        magic = struct.unpack_from('<I', head, 1024)[0]
        print(f'{name:<11} {size:>12} B  erofs={"yes" if magic == EROFS_MAGIC else hex(magic)}  '
              f'multiple_of_4096={size % 4096 == 0}')
    for tag in ('1113', '1114'):
        p = os.path.join(VB_DIR, f'vendor_boot_{tag}.img')
        if os.path.isfile(p):
            print(f'vb {tag:<8} {os.path.getsize(p):>12} B')
        else:
            print(f'vb {tag:<8} (缺)')


def arg(argv, flag, default=None):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return default


def main():
    argv = sys.argv[1:]
    images_dir = arg(argv, '--images', IMAGES)
    vb_dir = arg(argv, '--vb-dir', VB_DIR)
    outzip = arg(argv, '--out', OUTZIP)

    if '--inspect' in argv:
        inspect_images(images_dir)
        globals()['VB_DIR'] = vb_dir
        return

    ub_dir = os.path.join(STAGE, 'META-INF', 'com', 'google', 'android')
    os.makedirs(ub_dir, exist_ok=True)
    with open(os.path.join(ub_dir, 'update-binary'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(UPDATE_BINARY)
    with open(os.path.join(ub_dir, 'updater-script'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(UPDATER_SCRIPT)
    with open(os.path.join(STAGE, 'README.txt'), 'w', newline='\n', encoding='utf-8') as f:
        f.write(README)

    imgs = {n: os.path.join(images_dir, n + '.img') for n in ('system', 'system_ext', 'product')}
    for name, path in imgs.items():
        if not os.path.isfile(path):
            raise SystemExit(f'missing image: {path}')

    vbs = {}
    for tag in ('1113', '1114'):
        p = os.path.join(vb_dir, f'vendor_boot_{tag}.img')
        if os.path.isfile(p):
            vbs[tag] = p
    if len(vbs) < 2:
        print('! 警告: vendor_boot_1113/1114 没有同时提供，包里会缺一份，'
              '对应底包会 abort')

    if os.path.exists(outzip):
        os.remove(outzip)
    with zipfile.ZipFile(outzip, 'w', zipfile.ZIP_STORED, allowZip64=True) as z:
        for root, _dirs, files in os.walk(STAGE):
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, STAGE).replace('\\', '/')
                if rel.endswith('update-binary'):
                    zi = zipfile.ZipInfo(rel)
                    zi.external_attr = 0o100755 << 16   # 保留可执行位
                    zi.compress_type = zipfile.ZIP_STORED
                    with open(full, 'rb') as src:
                        z.writestr(zi, src.read())
                else:
                    z.write(full, rel)
        for name, path in imgs.items():
            z.write(path, 'images/' + name + '.img')
        for tag, path in sorted(vbs.items()):
            z.write(path, f'images/vendor_boot_{tag}.img')

    print(f'wrote {outzip} ({os.path.getsize(outzip) / 1024**2:.0f} MB)')


if __name__ == '__main__':
    main()
