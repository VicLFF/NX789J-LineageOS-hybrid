**中文摘要** · [English](#english)

# 工具说明（中文）

移植过程中写的一次性小工具，全部只依赖 Python 3 标准库（两个 `.ps1` 是 Windows 侧的 EDL 驱动）。

| 分组 | 用途 |
|---|---|
| 动态分区 | `extract_super.py` 从 `super.img` 抠出整分区；`patch_super.py` 按 extent 写回；`check_fs.py` 报告每个逻辑分区大小与文件系统；`make_edl_los_xml.py` 生成直写 `super` 内逻辑分区的 EDL XML；`sparse2raw.py` sparse → raw |
| Boot 镜像 | `vb_unpack.py` / `vb_repack.py` 解包重打包 `vendor_boot`（去掉三个分区上 `,avb=vbmeta_system` 校验）；`extract_kernel.py` 从 boot 抽内核；`avb_info.py` 读 AVB 头与描述符；`build_cardzip.py` 做不绑定底包的卡刷包 |
| EDL | `edl_flash.ps1` 刷三张镜像；`edl_restore_official.ps1` 用 ZTE 官方工具箱（**ZTEToolBox**，作者 **酷安 @某贼**）导出的备份整机恢复（GPT + 全部分区） |
| 指纹调试 | `fp_try.ps1/.cmd` 自动跑完整录入流程并抓日志；`patch_tsa_in_vendor.py` 是**已证明无效**的 vendor 补丁实验，仅留档；`../fpbridge/` 是那个把中兴指纹状态机推出 IDLE 的小 APK |

下面几点是踩坑换来的，务必先看：

- 两个 EDL 脚本都需要**本机型配套的 firehose programmer**（`prog_firehose_ddr.elf` / `firehose.elf`）。它是高通引导程序、不含任何 ROM 内容，但**必须与本机型号匹配** —— 拿同 SoC 其他机型（如 NX809J）的 devprg 会立刻报 `ERROR: is_ack_successful:1387 Invalid status field 41`。获取方式：用 ZTE 工具箱对 NX789J 跑一次官方下载，工具会把 devprg 放到 `zte\bin\res\NX789J\devprg\`；用 `-Programmer` 指定，或放到脚本旁命名 `firehose.elf`。本仓库不含该文件。
- `fh_loader` 的 `filename` 按**当前工作目录**解析，不跟 `--search_path`。
- `qcedlcmdhelper -d` 必须是**完整 XML 文档**（`<?xml … ?><data><configure …/></data>`），只给 `<configure/>` 会被静默丢弃，之后每次写入都报 `ERROR: Tool doesn't come from ZTE.`
- PowerShell 里 `--sendxml=(... -join ',')` 会被拆成两个参数，要拼成单个 token。
- `SECTOR_SIZE_IN_BYTES` 拼错一个字母，写入会在分区中途失败。
- `fh_loader --reset` 是断电重启，手机会从 USB 消失约 15 秒，属正常现象。

---

<a id="english"></a>

# tools

Small self-contained helpers used while porting. They only need Python 3 (no third
party packages) except where noted; the two PowerShell scripts are Windows-side EDL
drivers.

## Super / dynamic partitions

| Script | What it does |
|---|---|
| `extract_super.py` | Parse `super.img` LP metadata and carve out a whole logical partition (`system_a`, `vendor_a`, …) to a raw file. Handles multi-extent partitions. |
| `patch_super.py` | Same parser, but writes an image **into** an existing `super.img` in place, following the extent list. |
| `check_fs.py` | Walk the LP metadata and report each logical partition's size / filesystem (EROFS magic check). |
| `make_edl_los_xml.py` | Produce a `fh_loader` XML that writes images directly to the logical partitions inside `super` over EDL (`abs_sector = super_start + extent_offset/8`). |
| `sparse2raw.py` | Convert an Android sparse image to raw — EDL cannot write sparse, fastboot prefers it. |

## Boot images

| Script | What it does |
|---|---|
| `vb_unpack.py` | Unpack a `vendor_boot` v4 image: header, LZ4-legacy vendor ramdisk, cpio archive (~320 entries). |
| `vb_repack.py` | Repack it — the only change is stripping `,avb=vbmeta_system` / `,avb=v` / `avb_keys=` from `first_stage_ramdisk/fstab.qcom` for `system`, `system_ext`, `product`. |
| `extract_kernel.py` | Pull the kernel `Image` out of a boot v4 image with **no** ramdisk (this device's `boot.img`). |
| `avb_info.py` | Read an AVB image (header, algorithm, rollback index, descriptors). Use this instead of hand-rolling — the algorithm field is easy to misread. |
| `build_cardzip.py` | Build a recovery-flashable zip whose `update-binary` parses the LP metadata *on the device* and writes only the three logical partitions (works on any base layout). |

## EDL (Windows)

| Script | What it does |
|---|---|
| `edl_flash.ps1` | Sahara → firehose configure → `fh_loader` write of system/system_ext/product, using the offsets computed from the device's live `super`. |
| `edl_restore_official.ps1` | Full restore from an **official ZTE-toolbox backup**: replays that backup's `rawprogram0..5.xml`, so GPT and every partition come back (1–2 minutes). |

Both need a **firehose programmer** (`prog_firehose_ddr.elf` / `firehose.elf`). It is Qualcomm's
bootloader helper: it contains no ROM content, but it **must match this exact model**. A programmer for
another NX-series device with the same SoC fails immediately with
`ERROR: is_ack_successful:1387 Invalid status field 41`. To obtain it, let the ZTE toolbox perform one
official download for NX789J — it stores the matching devprg under `zte\bin\res\NX789J\devprg\`. Then
pass it with `-Programmer`, or drop it next to the scripts as `firehose.elf`. It is not in this repository.

Gotchas that cost hours, in one place:

- `fh_loader` resolves `filename` relative to the **current directory**, not
  `--search_path`.
- `qcedlcmdhelper -d` needs a **complete XML document**
  (`<?xml … ?><data><configure …/></data>`). A bare `<configure/>` is dropped
  silently and every subsequent write fails with `ERROR: Tool doesn't come from ZTE.`
- In PowerShell, `--sendxml=(... -join ',')` splits into two arguments; build one
  token: `$arg = '--sendxml=' + ($xmls -join ',')`.
- `SECTOR_SIZE_IN_BYTES` — one typo (`SECTOR_SIZE_BYTES`) and the write aborts
  halfway through the partition.
- `fh_loader --reset` power-cycles rather than reboots; the phone disappears from USB
  for ~15 s. That is expected.

## Fingerprint debug

| Script | What it does |
|---|---|
| `fp_try.ps1` / `fp_try.cmd` | Drive the AOSP enrollment flow by itself (wake, PIN, uiautomator text navigation, fire the bridge APK's `sendMessageInfo(6)`, beep twice, capture 75 s of logcat, print a result table). Exists because the Goodix HAL aborts enrollment 60 s after the sensor screen opens — faster than a human round-trip. |
| `patch_tsa_in_vendor.py` | Locate `libgdix_tsa.so` inside a `vendor_a.img` by signature and patch one instruction. **Documented as a dead end** — see the README's known issues. Kept for reference. |
| `../fpbridge/` | The tiny APK that pokes ZTE's UDFPS state machine out of IDLE. |
