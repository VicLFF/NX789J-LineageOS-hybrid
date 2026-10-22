#!/usr/bin/env python3
"""
build_edl_pack.py —— 把 LineageOS 的三个分区镜像 + 去 avb 的 vendor_boot 打成
一个「解压就能跑」的 EDL 线刷包（NX789J）。

用法:
    python build_edl_pack.py \
        --images  <目录: system.img system_ext.img product.img vendor_boot_noverity.img> \
        --super-head <super 前 512KB 的 bin，可为 super.img 本身> \
        --out  LOS-EDL.zip \
        [--tool-dir "<ZTE 工具箱 tool\\Win 目录，用于写进 README>"] \
        [--zip-store]

为什么需要 super 头: 逻辑分区在 super 里的位置由 LP 元数据决定，而元数据随底包版本变化
（11.0.13 是 53 个 extent，11.0.14 是 61 个）。用自己手机当前底包的 super 头来算，
生成的偏移才对得上。

生成物:
    flash.bat                双击即刷（需要 ZTE 工具箱的 QSaharaServer/qcedlcmdhelper/fh_loader）
    configure.xml            qcedlcmdhelper 的 configure 负载（完整 XML 文档，Oem="ZTE"）
    rawprogram_los.xml       fh_loader 的分区写入清单
    images/                  system.img system_ext.img product.img vendor_boot.img zeros64m.img zeros16m.img
    README.txt               操作说明 + 风险提示

注意: 包里不含任何厂商文件 —— vendor_boot 请用 tools/vb_repack.py 从自己手机的官方
vendor_boot_a.img 现场生成，火候(firehose loader)也用自己工具箱里的。
"""

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

# NX789J（与 NX789J 的 GPT 一致）:
#   0 号 LUN 的 super 起始扇区 8968（4096B 扇区）
#   4 号 LUN 的 vendor_boot_a @282982、vendor_boot_b @635296（各 24576 扇区）
SUPER_START_SECTOR = 8968
VENDOR_BOOT_ENTRIES = [
    ("vendor_boot_a", 4, 282982, 24576),
    ("vendor_boot_b", 4, 635296, 24576),
]

# 逻辑分区名 -> (镜像文件名)
LOGICAL = {
    "system_a": "system.img",
    "system_ext_a": "system_ext.img",
    "product_a": "product.img",
}

ZEROS64 = "zeros64m.img"
ZEROS16 = "zeros16m.img"
USERDATA_ENTRY = ("userdata", 0, 4350760, 16384)   # 前 64 MB 清零
METADATA_ENTRY = ("metadata", 0, 4203304, 4096)    # 前 16 MB 清零

CONFIGURE_XML = (
    '<?xml version="1.0" encoding="UTF-8" ?><data>'
    '<configure MemoryName="ufs" Verbose="0" AlwaysValidate="0" '
    'MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" '
    'ZlpAwareHost="1" SkipStorageInit="0" Oem="ZTE"/></data>'
)

FLASH_BAT = r"""@echo off
setlocal
chcp 437 >nul
title LineageOS 23.2 - nubia NX789J - EDL

echo ============================================
echo  LineageOS 23.2  -  nubia NX789J  -  EDL
echo  writes: system / system_ext / product / vendor_boot(a,b) + wipes data head
echo ============================================
echo.

set "TOOL=%~dp0tools"
if not exist "%TOOL%\QSaharaServer.exe" goto :notools

echo Put the phone into EDL first:
echo   power off, hold Volume+ AND Volume- , then plug USB
echo   device manager must show Qualcomm HS-USB QDLoader 9008 (COMn)
echo.
set /p COM=COM port number (e.g. 6):
if "%COM%"=="" goto :badcom

echo.
echo [1/3] Sahara (upload firehose loader) ...
"%TOOL%\QSaharaServer.exe" -p \\.\COM%COM% -s 13:"%~dp0tools\firehose.elf"
if errorlevel 1 echo   Sahara failed - if loader is already running, configure below may still work

echo.
echo [2/3] configure ...
"%TOOL%\qcedlcmdhelper.exe" -p COM%COM% -m xml -f "%~dp0configure.xml"
echo   (expect: response value="ACK")

echo.
echo [3/3] writing partitions ...
"%TOOL%\fh_loader.exe" --port=\\.\COM%COM% --memoryname=ufs --search_path="%~dp0" --sendxml=rawprogram_los.xml --showpercentagecomplete --noprompt --skip_config
if errorlevel 1 goto :fail

echo.
echo ============================================
echo  done, resetting ...
echo ============================================
"%TOOL%\fh_loader.exe" --port=\\.\COM%COM% --memoryname=ufs --reset --noprompt --skip_config
echo.
echo First boot reformats /data, wait 1-2 minutes.
pause
exit /b 0

:notools
echo [X] tools\QSaharaServer.exe not found.
echo     Copy QSaharaServer.exe / qcedlcmdhelper.exe / fh_loader.exe and a matching
echo     firehose loader (rename to firehose.elf) into the tools\ folder.
pause
exit /b 1

:badcom
echo [X] no COM port given
pause
exit /b 1

:fail
echo.
echo [X] write failed. Common reasons:
echo     - "ERROR: Tool doesn't come from ZTE"  -^> configure failed, run again
echo     - "Could not access ... with acess mode 'rb'" -^> path has non-ASCII chars
echo     - Sahara/programmer mismatch -^> use the firehose loader for this model
pause
exit /b 1
"""

README_TXT = r"""LineageOS 23.2 (nubia NX789J) —— EDL 线刷包
================================================

这个包用 EDL（高通 9008）直接写分区，不依赖 fastboot，也不依赖 recovery。

【先看这个：适用范围】
  只在这两个官方底包上真机验证过：
    * RedMagicOS 11.0.14   (BQ2A.250705.001-BP2A.250605.031.A3 / 20260813.164726)
    * RedMagicOS 11.0.13   (更早的验证版本)
  其它底包（别的官方版本、第三方移植包、OTA 后没清数据的混合状态）都是「自测」，
  风险自负。EDL 包不挑底包容量，所以不会拦你 —— 但这不代表它能跑。

【包里有什么】
  flash.bat                双击就刷（需要 tools\ 里的工具箱）
  configure.xml            configure 负载
  rawprogram_los.xml       分区清单（偏移是按生成的 super 头算的）
  images\system.img        722,042,880 B
  images\system_ext.img    252,579,840 B
  images\product.img       327,704,576 B
  images\vendor_boot.img   100,663,296 B（去掉了 avb 校验的版本）
  images\zeros64m.img      /data 前 64 MB 清零
  images\zeros16m.img      metadata 前 16 MB 清零
  tools\                   你需要自己放进来（见下）

【准备 tools 目录（必须）】
  从 ZTE 工具箱（ZTEToolBox，作者 酷安 @某贼）复制：
    QSaharaServer.exe
    qcedlcmdhelper.exe
    fh_loader.exe
  再放一个与本机匹配的 firehose loader，命名 firehose.elf
  （体积通常 1.5-2 MB；别的机型的 devprg 会报 Invalid status field 41）

【操作步骤】
  1. 手机彻底关机
  2. 按住 音量+ 和 音量- 不放，插 USB
  3. 设备管理器出现 Qualcomm HS-USB QDLoader 9008 (COMn) 才算成功
  4. 双击 flash.bat，输入那个 n
  5. 等 percent files transferred 100.00% 和 All Finished Successfully
  6. 脚本会自动复位；首次开机重新格式化 /data，等 1-2 分钟

【为什么会写 vendor_boot】
  官方底包的 first_stage_ramdisk/fstab.qcom 里，system/system_ext/product 三条都带
  avb=vbmeta_system 和 avb_keys=...，内核会用 dm-verity 校验这三个分区；写入自己编的
  镜像必然校验失败，init 挂不上 /system，表现是「亮 logo 就重启」。
  去掉这些参数后（8154 -> 7062 字节）才能起来。这个改动只碰 ramdisk 里的 fstab。

【绝对不要做的事】
  * 不要刷 vbmeta / vbmeta_system（校验链会拒自签名的 vbmeta，直接起不来）
  * 不要刷 boot / init_boot / dtbo（这套方案不动它们）
  * 不要用其它机型的 firehose loader

【出问题怎么退】
  1. 按官方整机备份恢复（ZTE 工具箱全分区 rawprogram0-5），60 秒回到官方系统
  2. 需要保留数据就别清零 userdata，但换 ROM 时必须清（FBE 密钥变了）

【已知限制】
  * 屏下指纹不可用（vendor 层触摸/TSA 私有帧格式，system 侧改不到）
  * 人脸解锁不可用（原厂私有锁屏服务）
  * 风扇 / 肩键 / 后盖氛围灯不工作（私有系统服务）
  * 供电分离（旁路供电）未测试
"""


def erofs_ok(path):
    try:
        with open(path, "rb") as f:
            f.seek(1024)
            return f.read(4) == b"\xe2\xe1\xf5\xe0"
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True, help="含 system.img/system_ext.img/product.img/vendor_boot_noverity.img 的目录")
    ap.add_argument("--super-head", required=True, help="super 前 512KB 的 bin（也可以直接给 super.img）")
    ap.add_argument("--out", default="LOS-EDL.zip")
    ap.add_argument("--vendor-boot-name", default="vendor_boot_noverity.img")
    ap.add_argument("--zip-store", action="store_true", help="不压缩打包（镜像本来就压不动）")
    args = ap.parse_args()

    img_dir = os.path.abspath(args.images)
    need = ["system.img", "system_ext.img", "product.img", args.vendor_boot_name]
    for n in need:
        p = os.path.join(img_dir, n)
        if not os.path.exists(p):
            sys.exit(f"[X] 缺文件: {p}")

    # 三个逻辑分区必须是从我们这套源码编出来的 erofs
    for n in ["system.img", "system_ext.img", "product.img"]:
        p = os.path.join(img_dir, n)
        if not erofs_ok(p):
            sys.exit(f"[X] {p} 不是 erofs 镜像（+1024 处魔数不对）")

    tmp = tempfile.mkdtemp(prefix="los_edl_")
    try:
        # 1. 读 LP 元数据（复用 make_edl_los_xml 的解析）
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        import make_edl_los_xml as mk  # noqa: E402

        parts, exts = mk.load_meta(args.super_head)
        lines = []
        for name, fname in LOGICAL.items():
            if name not in parts:
                sys.exit(f"[X] super 元数据里没有 {name}（super 头不对？）")
            first, num = parts[name]
            _ns, tdata = exts[first]
            abs_sector = SUPER_START_SECTOR + tdata // 8
            capacity_bytes = sum(exts[first + k][0] for k in range(num)) * 512
            img = os.path.join(img_dir, fname)
            size = os.path.getsize(img)
            nsec = (size + 4095) // 4096
            if size > capacity_bytes:
                sys.exit(f"[X] {fname} {size:,} B 超过 {name} 容量 {capacity_bytes:,} B")
            lines.append(
                f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                f'filename="images\\{fname}" label="{name}" num_partition_sectors="{nsec}" '
                f'physical_partition_number="0" start_sector="{abs_sector}" />'
            )
            print(f"  {name:14} -> LUN0 @{abs_sector:<8} {nsec:<7} sec   capacity {capacity_bytes/1048576:.1f} MB ({num} extents)")

        vb = os.path.join(img_dir, args.vendor_boot_name)
        vb_sec = (os.path.getsize(vb) + 4095) // 4096
        for (label, lun, start, nsec) in VENDOR_BOOT_ENTRIES:
            if vb_sec > nsec:
                sys.exit(f"[X] vendor_boot {vb_sec} 扇区超过分区 {nsec} 扇区")
            lines.append(
                f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                f'filename="images\\vendor_boot.img" label="{label}" '
                f'num_partition_sectors="{nsec}" physical_partition_number="{lun}" '
                f'start_sector="{start}" />'
            )
            print(f"  {label:14} -> LUN{lun} @{start:<8} {nsec:<7} sec   (whole partition)")

        for (label, lun, start, nsec), zname in ((USERDATA_ENTRY, ZEROS64), (METADATA_ENTRY, ZEROS16)):
            lines.append(
                f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                f'filename="images\\{zname}" label="{label}" num_partition_sectors="{nsec}" '
                f'physical_partition_number="{lun}" start_sector="{start}" />'
            )
            print(f"  {label:14} -> LUN{lun} @{start:<8} {nsec:<7} sec   (zero-fill)")

        xml = '<?xml version="1.0" ?>\n<data>\n' + "\n".join(lines) + "\n</data>\n"

        # 2. 组装目录
        stage = os.path.join(tmp, "LOS-EDL")
        os.makedirs(os.path.join(stage, "images"))
        with open(os.path.join(stage, "rawprogram_los.xml"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(xml)
        with open(os.path.join(stage, "configure.xml"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(CONFIGURE_XML)
        with open(os.path.join(stage, "flash.bat"), "w", encoding="ascii", newline="\r\n") as f:
            f.write(FLASH_BAT)
        with open(os.path.join(stage, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(README_TXT)
        os.makedirs(os.path.join(stage, "tools"), exist_ok=True)
        with open(os.path.join(stage, "tools", "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write("把 QSaharaServer.exe / qcedlcmdhelper.exe / fh_loader.exe 和本机匹配的\n"
                    "firehose loader（改名 firehose.elf）放到这个目录。\n")

        # 3. 镜像（用硬链接省空间，打包时按内容读）
        def put(src, dst_name):
            dst = os.path.join(stage, "images", dst_name)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        put(os.path.join(img_dir, "system.img"), "system.img")
        put(os.path.join(img_dir, "system_ext.img"), "system_ext.img")
        put(os.path.join(img_dir, "product.img"), "product.img")
        put(vb, "vendor_boot.img")
        with open(os.path.join(stage, "images", ZEROS64), "wb") as f:
            f.truncate(64 * 1024 * 1024)
        with open(os.path.join(stage, "images", ZEROS16), "wb") as f:
            f.truncate(16 * 1024 * 1024)

        # 4. 打包
        comp = zipfile.ZIP_STORED if args.zip_store else zipfile.ZIP_DEFLATED
        out = os.path.abspath(args.out)
        print(f"\npacking {out} ...")
        with zipfile.ZipFile(out, "w", comp, compresslevel=1 if comp == zipfile.ZIP_DEFLATED else None) as z:
            for root, _dirs, files in os.walk(stage):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, tmp)
                    z.write(full, rel)
        print(f"[OK] {out}  {os.path.getsize(out):,} B")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
