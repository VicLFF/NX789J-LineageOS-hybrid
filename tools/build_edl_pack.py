#!/usr/bin/env python3
"""build_edl_pack.py —— 打一个「官方 11.0.13 / 11.0.14 底包通用」的 EDL 线刷包（NX789J）。

包里同时带两个版本的「去 avb」vendor_boot，`flash.bat` 让你选底包版本：

    1) 官方 RedMagicOS 11.0.14
    2) 官方 RedMagicOS 11.0.13

选完它就写对应的 vendor_boot，并写 system / system_ext / product，
最后清零 /data 与 metadata 的头部（换 ROM 必须清，FBE 密钥变了）。

用法
----
    python build_edl_pack.py \
        --images <目录: system.img system_ext.img product.img
                       vendor_boot_1113.img vendor_boot_1114.img> \
        --super-head <自己底包 super 的前 512KB> \
        --out LOS-EDL.zip [--zip-store]

为什么需要 super 头: 逻辑分区在 super 里的位置由 LP 元数据决定，而元数据随底包版本
变化（11.0.13 是 53 个 extent，11.0.14 是 61 个）。用自己手机当前底包的 super 头
来算，生成的偏移才对得上。

包里不含私有工具：QSaharaServer / qcedlcmdhelper / fh_loader 以及本机匹配的
firehose loader，需要你从 ZTE 工具箱放进 tools\\。
"""

import argparse
import os
import shutil
import sys
import tempfile
import zipfile

# NX789J GPT 常量（4096B 扇区）
SUPER_START_SECTOR = 8968                                    # LUN0 上 super 的起始扇区
VENDOR_BOOT_SLOTS = [(4, 282982, 24576), (4, 635296, 24576)]  # vendor_boot_a / _b
USERDATA_ENTRY = (0, 4350760, 16384)                          # /data 前 64 MB 清零
METADATA_ENTRY = (0, 4203304, 4096)                           # metadata 前 16 MB 清零

LOGICAL = {"system_a": "system.img", "system_ext_a": "system_ext.img", "product_a": "product.img"}
BASES = [("1114", "官方 RedMagicOS 11.0.14"), ("1113", "官方 RedMagicOS 11.0.13")]

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

echo ==========================================================
echo   LineageOS 23.2  -  nubia NX789J  -  EDL flash
echo   writes: system / system_ext / product / vendor_boot(a,b)
echo           + wipes first 64MB of data and 16MB of metadata
echo ==========================================================
echo.

set "TOOL=%~dp0tools"
if not exist "%TOOL%\QSaharaServer.exe" goto :notools

echo Which STOCK base is on your phone right now?
echo.
echo   1) official RedMagicOS 11.0.14
echo   2) official RedMagicOS 11.0.13
echo.
echo   (unsure? boot it, check Settings - About phone - Build number)
echo.
set /p VER=Enter 1 or 2:
if "%VER%"=="1" (set "XML=rawprogram_los_1114.xml" & set "BASE=RedMagicOS 11.0.14") else (
if "%VER%"=="2" (set "XML=rawprogram_los_1113.xml" & set "BASE=RedMagicOS 11.0.13") else (
echo [X] please enter 1 or 2 & pause & exit /b 1 ))

echo.
echo Selected base: %BASE%
echo.
echo Put the phone into EDL first:
echo   power off, hold Volume+ AND Volume- , then plug USB
echo   device manager must show Qualcomm HS-USB QDLoader 9008 (COMn)
echo.
set /p COM=COM port number (e.g. 6):
if "%COM%"=="" goto :badcom

echo.
echo [1/3] Sahara (upload firehose loader) ...
"%TOOL%\QSaharaServer.exe" -p \\.\COM%COM% -s 13:"%~dp0tools\firehose.elf"
if errorlevel 1 echo   Sahara failed - if the loader is already running, configure may still work

echo.
echo [2/3] configure ...
"%TOOL%\qcedlcmdhelper.exe" -p COM%COM% -m xml -f "%~dp0configure.xml"
echo   (expect: response value="ACK")

echo.
echo [3/3] writing partitions ...
"%TOOL%\fh_loader.exe" --port=\\.\COM%COM% --memoryname=ufs --search_path="%~dp0" --sendxml=%XML% --showpercentagecomplete --noprompt --skip_config
if errorlevel 1 goto :fail

echo.
echo ==========================================================
echo   done, resetting ...
echo ==========================================================
"%TOOL%\fh_loader.exe" --port=\\.\COM%COM% --memoryname=ufs --reset --noprompt --skip_config
echo.
echo First boot reformats /data. Wait 1-3 minutes.
pause
exit /b 0

:notools
echo [X] tools\QSaharaServer.exe not found.
echo     Copy QSaharaServer.exe / qcedlcmdhelper.exe / fh_loader.exe and a
echo     firehose loader for THIS model (rename to firehose.elf) into tools\.
pause
exit /b 1

:badcom
echo [X] no COM port given
pause
exit /b 1

:fail
echo.
echo [X] write failed. Common reasons:
echo     - "ERROR: Tool doesn't come from ZTE" -^> configure failed, run again
echo     - "Could not access ... with acess mode 'rb'" -^> path has non-ASCII chars
echo     - Sahara/programmer mismatch -^> use the firehose loader for NX789J
pause
exit /b 1
"""

README_TXT = r"""LineageOS 23.2 (nubia NX789J) —— EDL 线刷包（官方 11.0.13 / 11.0.14 通用）
================================================================================

【包里有什么】
  flash.bat                   双击就刷；先让你选底包是 11.0.14 还是 11.0.13
  configure.xml               configure 负载
  rawprogram_los_1114.xml     底包是 11.0.14 时用这份
  rawprogram_los_1113.xml     底包是 11.0.13 时用这份
  images\system.img           722,042,880 B
  images\system_ext.img       252,579,840 B
  images\product.img          327,704,576 B
  images\vendor_boot_1114.img 100,663,296 B（11.0.14 的去 avb 版本）
  images\vendor_boot_1113.img 100,663,296 B（11.0.13 的去 avb 版本）
  images\zeros64m.img         /data 前 64 MB 清零
  images\zeros16m.img         metadata 前 16 MB 清零
  tools\                      需要你自己放（见下）

【先确认你的底包】
  设置 -> 关于手机 -> 版本号
    20260813.164726  ->  11.0.14
    更早的日期        ->  11.0.13
  选错版本的 vendor_boot 写进去会起不来（或触摸失灵），但不会变砖 ——
  用官方全分区备份恢复即可。

【准备 tools\（必须）】
  从 ZTE 工具箱（ZTEToolBox，作者 酷安 @某贼）复制：
    QSaharaServer.exe   qcedlcmdhelper.exe   fh_loader.exe
  再放一个与 NX789J 匹配的 firehose loader，命名 firehose.elf
  （体积通常 1.5-2 MB；别的机型的 devprg 会报 Invalid status field 41）

【操作步骤】
  1. 手机彻底关机
  2. 按住 音量+ 和 音量- 不放，插 USB
  3. 设备管理器出现 Qualcomm HS-USB QDLoader 9008 (COMn) 才算成功
  4. 双击 flash.bat，先选底包版本，再输入那个 n
  5. 等 percent files transferred 100.00% 与 All Finished Successfully
  6. 脚本会自动复位；首次开机重新格式化 /data，等 1-3 分钟

【为什么要写 vendor_boot】
  官方底包的 first_stage_ramdisk/fstab.qcom 里，system / system_ext / product
  三条都带 avb=vbmeta_system 和 avb_keys=...，内核会用 dm-verity 校验它们。
  写入自己编的镜像必然校验失败，init 挂不上 /system，表现是「亮 logo 就重启」。
  去掉这些参数（8154 -> 7062 字节）才能起来。

【绝对不要做的事】
  * 不要刷 vbmeta / vbmeta_system（自签名会被 bootloader 拒绝，直接起不来）
  * 不要刷 boot / init_boot / dtbo（本方案不动它们）
  * 不要用其它机型的 firehose loader

【出问题怎么退】
  用 ZTE 工具箱的官方全分区备份跑 rawprogram0-5 全量恢复（约 60 秒）。

【已知限制】
  * 屏下指纹不可用（vendor 层私有触摸/TSA 帧格式，system 侧改不到）
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


def build_xml(base_tag, vb_name, img_dir, parts, exts):
    lines = []
    for name, fname in LOGICAL.items():
        first, num = parts[name]
        _ns, tdata = exts[first]
        abs_sector = SUPER_START_SECTOR + tdata // 8
        capacity = sum(exts[first + k][0] for k in range(num)) * 512
        size = os.path.getsize(os.path.join(img_dir, fname))
        if size > capacity:
            sys.exit(f"[X] {fname} {size:,} B 超过 {name} 容量 {capacity:,} B")
        nsec = (size + 4095) // 4096
        lines.append(f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                     f'filename="images\\{fname}" label="{name}" num_partition_sectors="{nsec}" '
                     f'physical_partition_number="0" start_sector="{abs_sector}" />')
        print(f"  [{base_tag}] {name:14} -> LUN0 @{abs_sector:<8} {nsec:<7} sec  "
              f"cap {capacity/1048576:.1f} MB ({num} extents)")

    vb = os.path.join(img_dir, vb_name)
    vb_sec = (os.path.getsize(vb) + 4095) // 4096
    for i, (lun, start, nsec) in enumerate(VENDOR_BOOT_SLOTS):
        if vb_sec > nsec:
            sys.exit(f"[X] vendor_boot {vb_sec} 扇区超过分区 {nsec} 扇区")
        lines.append(f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                     f'filename="images\\{vb_name}" label="vendor_boot_{"ab"[i]}" '
                     f'num_partition_sectors="{nsec}" physical_partition_number="{lun}" '
                     f'start_sector="{start}" />')
    for (lun, start, nsec), zname in ((USERDATA_ENTRY, "zeros64m.img"),
                                      (METADATA_ENTRY, "zeros16m.img")):
        lines.append(f'  <program SECTOR_SIZE_IN_BYTES="4096" file_sector_offset="0" '
                     f'filename="images\\{zname}" label="{zname.split(".")[0]}" '
                     f'num_partition_sectors="{nsec}" physical_partition_number="{lun}" '
                     f'start_sector="{start}" />')
    return '<?xml version="1.0" ?>\n<data>\n' + "\n".join(lines) + "\n</data>\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--images", required=True)
    ap.add_argument("--super-head", required=True, help="自己底包 super 的前 512KB（也可直接给 super.img）")
    ap.add_argument("--out", default="LOS-EDL.zip")
    ap.add_argument("--zip-store", action="store_true")
    args = ap.parse_args()

    img_dir = os.path.abspath(args.images)
    for n in ("system.img", "system_ext.img", "product.img"):
        p = os.path.join(img_dir, n)
        if not os.path.exists(p):
            sys.exit(f"[X] 缺文件: {p}")
        if not erofs_ok(p):
            sys.exit(f"[X] {p} 不是 erofs 镜像（+1024 处魔数不对）")

    bases = []
    for tag, label in BASES:
        name = f"vendor_boot_{tag}.img"
        if os.path.exists(os.path.join(img_dir, name)):
            bases.append((tag, label, name))
        else:
            print(f"! 跳过 {label}：缺 {name}")
    if not bases:
        sys.exit("[X] 至少要有一份 vendor_boot_<1113|1114>.img")

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import make_edl_los_xml as mk  # noqa: E402
    parts, exts = mk.load_meta(args.super_head)

    tmp = tempfile.mkdtemp(prefix="los_edl_")
    try:
        stage = os.path.join(tmp, "LOS-EDL")
        os.makedirs(os.path.join(stage, "images"))
        os.makedirs(os.path.join(stage, "tools"), exist_ok=True)

        for tag, label, vb_name in bases:
            xml = build_xml(tag, vb_name, img_dir, parts, exts)
            with open(os.path.join(stage, f"rawprogram_los_{tag}.xml"), "w",
                      encoding="utf-8", newline="\r\n") as f:
                f.write(xml)

        with open(os.path.join(stage, "configure.xml"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(CONFIGURE_XML)
        with open(os.path.join(stage, "flash.bat"), "w", encoding="ascii", newline="\r\n") as f:
            f.write(FLASH_BAT)
        with open(os.path.join(stage, "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write(README_TXT)
        with open(os.path.join(stage, "tools", "README.txt"), "w", encoding="utf-8", newline="\r\n") as f:
            f.write("把 QSaharaServer.exe / qcedlcmdhelper.exe / fh_loader.exe 和本机匹配的\n"
                    "firehose loader（改名 firehose.elf）放到这个目录。\n")

        def put(src, dst_name):
            dst = os.path.join(stage, "images", dst_name)
            try:
                os.link(src, dst)
            except OSError:
                shutil.copy2(src, dst)

        for n in ("system.img", "system_ext.img", "product.img"):
            put(os.path.join(img_dir, n), n)
        for _tag, _label, vb_name in bases:
            put(os.path.join(img_dir, vb_name), vb_name)
        with open(os.path.join(stage, "images", "zeros64m.img"), "wb") as f:
            f.truncate(64 * 1024 * 1024)
        with open(os.path.join(stage, "images", "zeros16m.img"), "wb") as f:
            f.truncate(16 * 1024 * 1024)

        comp = zipfile.ZIP_STORED if args.zip_store else zipfile.ZIP_DEFLATED
        out = os.path.abspath(args.out)
        print(f"\npacking {out} ...")
        with zipfile.ZipFile(out, "w", comp, compresslevel=1 if comp == zipfile.ZIP_DEFLATED else None) as z:
            for root, _dirs, files in os.walk(stage):
                for name in files:
                    full = os.path.join(root, name)
                    z.write(full, os.path.relpath(full, tmp))
        print(f"[OK] {out}  {os.path.getsize(out):,} B")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
