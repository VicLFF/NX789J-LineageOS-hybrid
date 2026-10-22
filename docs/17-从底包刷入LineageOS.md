# 从官方底包刷入 LineageOS（NX789J / 红魔 10S Pro+）

> 全部步骤都是**实测流程**，最后更新：2026-10-22。

> **实测记录**
> * 2026-10-22：官方 **11.0.14** 底包上跑完整条链路（EDL 刷 OrangeFox → 橙狐内刷卡刷包 → 清 data → 开机），
>   `sys.boot_completed=1`，SIM/通话/数据/刷新率/自动亮度/传感器/Wi-Fi 全部正常。
>   卡刷包底包校验输出：`system 8275MB(16 段) / system_ext 2427MB(7 段) / product 1006MB(13 段)`。
> * 更早版本在官方 **11.0.13** 上跑通过。
> * **其它底包一概未验证**，属于自测范围，风险自负（详见仓库 README「测试范围」一节）。
> 配套脚本：`tools/edl_flash.ps1`（EDL 刷三镜像）、`tools/edl_restore_official.ps1`（官方底包整机恢复）、
> `tools/vb_unpack.py` / `tools/vb_repack.py`（改 vendor_boot 的 first-stage fstab）、
> `tools/sparse2raw.py`、`tools/make_edl_los_xml.py`。

前提：**Bootloader 已解锁**，并且手上有这台机器的 **ZTE 官方工具箱全分区备份**（工具箱即 **ZTEToolBox**，作者 **酷安 @某贼**，用它对 NX789J 做一次官方下载即可得到本机备份与配套 programmer）（`ZTEToolBoxParBak_*/images`，含 `rawprogram0..5.xml` 与全部分区镜像）。这个备份既是底包来源，也是唯一的救砖退路。

---

## 0. 三条铁律

| # | 铁律 | 为什么 |
|---|---|---|
| 1 | **只刷 `system` / `system_ext` / `product`** 三个逻辑分区 | vendor 侧约 280 个内核模块与全部 HAL 都是按内核 `6.6.92-android15` 编的；换内核必须同批重编全部 vendor 模块（vermagic / CRC / CFI 全要对上） |
| 2 | **绝不刷 `vbmeta` / `vbmeta_system`** | 这两个分区里挂着 system 系的 dm-verity 哈希树。换成任何自签、或手工改 flags 的版本都会破坏 RSA 签名 → bootloader 直接拒绝引导（实测：8 秒内弹回 fastboot，连 recovery 都进不去） |
| 3 | **bootloader 里的 fastboot 是只读的** | `fastboot flash` 报 `remote: 'unknown command'`。能写的只有 **fastbootd**（`is-userspace: yes`）或 **EDL** |

---

## 1. 官方底包 vs LineageOS：差一个文件

官方 `vendor_boot` 的 `first_stage_ramdisk/fstab.qcom` 里，system 三分区带着完整 avb 链：

```
system      /system      erofs  ro  wait,slotselect,avb=vbmeta_system,logical,first_stage_mount,avb_keys=/avb/q-gsi.avbpubkey:/avb/r-gsi.avbpubkey:...:/avb/v-gsi.avbpubkey
system_ext  /system_ext  erofs  ro  wait,slotselect,avb=vbmeta_system,logical,first_stage_mount
product     /product     erofs  ro  wait,slotselect,avb=vbmeta_system,logical,first_stage_mount
```

（这三行取自 2026-07-07 官方备份里 `vendor_boot_a.img` 的实测原文，该文件共 8154 字节。）

init 会拿 `vbmeta_system` 里的哈希树去校验写进去的内容 —— 校验的是**官方原系统**，换成 LineageOS 必然失败 →
`/system` 挂不上 → 现象是**亮 LOGO 几秒自动重启、USB 全程不出现**（死在 USB gadget 初始化之前，所以既没有 adb 也没有 fastboot）。

**所以：必须先把 `vendor_boot` 换成一个「去 avb」的版本。**

---

## 2. 做「去 avb」的 vendor_boot

```bash
# 1) 解包官方 vendor_boot（纯 python，不需要 lz4 命令）
python3 tools/vb_unpack.py  官方备份/vendor_boot.img  work/

# 2) 编辑 work/first_stage_ramdisk/fstab.qcom
#    把 system / system_ext / product 三行里的这两类参数删掉：
#      ,avb=vbmeta_system      （以及可能出现的 ,avb=vbmeta）
#      avb_keys=/avb/...       整段删到空格为止
#    改完约 8154 → 7062 字节

# 3) 重新打包（其余部分不变，只重算 LZ4 ramdisk 与 header）
python3 tools/vb_repack.py  work/  官方备份/vendor_boot.img  vendor_boot_noverity.img
```

写回两个槽（A/B 都要），LUN4、4096 B 扇区：

| 分区 | start_sector | num_partition_sectors |
|---|---|---|
| `vendor_boot_a` | 282982 | 24576（= 100,663,296 B） |
| `vendor_boot_b` | 635296 | 24576 |

**注意回滚索引**：官方备份里 `vbmeta_system` 的 rollback index 是 `1772323200`。
如果这台机器以前刷过别的 ROM 把该索引抬高了（设备 RPMB 会记住最大值），再写回低索引的 `vbmeta_system` 会被回滚保护拒绝，同样卡在 fastboot。
这种情况下**不要动 vbmeta 系列**，保持设备上现在那一对（厂商签名、签名链合法），只换 `vendor_boot` 即可。

---

## 2.5 双底包：11.0.13 与 11.0.14 各要一份 vendor_boot

这一步用脚本就自动了，但得知道原理，否则会误判。

两个底包的 `vendor_boot` 不一样（`fstab.qcom` 之外还有 dtb 与 vendor ramdisk 的差异），所以「去 avb」的成品也必须各做一份：

| 底包 | 官方 `vendor_boot_a` md5 | 去 avb 后 md5 |
|---|---|---|
| RedMagicOS 11.0.14 | `5d427b57cecc7f32a19e041ee0550bde` | `03e9b98ad9328ec8a57a85ddcf799608` |
| RedMagicOS 11.0.13 | `ccea408082a8b28b6d402ebf4a972f85` | `e75b05fc8b79ec7969e1189ad9e05e50` |

```bash
python tools/vb_repack.py 11.0.13/vendor_boot_a.img vendor_boot_1113.img   # -> e75b05fc…
python tools/vb_repack.py 11.0.14/vendor_boot_a.img vendor_boot_1114.img   # -> 03e9b98a…
```

打包时两份都塞进包里，`update-binary` 在设备上按 md5 三选一：

1. 命中官方 md5（左列）→ 写对应那份去 avb 版到 `vendor_boot_a` + `vendor_boot_b`；
2. 命中去 avb md5（右列）→ 已经是了，跳过（可重复刷、幂等）；
3. 其它 md5 → abort，提示只支持官方 11.0.13 / 11.0.14。

**为什么用 md5 而不是版本号字符串**：`ro.build.display.id` / OTA 版本号会被第三方包改写，而 `vendor_boot` 的字节是底包自带的，用户改不动，比字符串可靠得多。

EDL 包里对应两份 `rawprogram_los_1114.xml` / `rawprogram_los_1113.xml`，只有 `vendor_boot` 那两条的 `filename` 不同，其余偏移完全一样（super 布局与 userdata/metadata 位置在两个底包上一致）。
## 3. 需要准备的镜像

本移植的产物（三张逻辑分区镜像）：

| 文件 | 大小 | md5 |
|---|---|---|
| `system.img` | 722,042,880 B | `34a6420577e6ec0d1abec74e012dbc10` |
| `system_ext.img` | 252,579,840 B | `c9807edf5315fe2869611e3e402ac991` |
| `product.img` | 327,704,576 B | `784e63b8c9149e3c5f0d9d9fd667b4d0` |

放进 `tools/edl/raw/`（脚本默认读这个目录）。

**另外还需要一个 firehose programmer**（同样由 ZTE 工具箱自动取得，见上）（`prog_firehose_ddr.elf` / `firehose.elf`）。
它是高通的引导程序，不含任何 ROM 内容，但**必须与本机 SoC 匹配** ——
实测把同 SoC 但不同机型的 programmer 拿来用，Sahara 直接报
`ERROR: is_ack_successful:1387 Invalid status field 41` 并复位。

获取方式：用 ZTE 官方工具箱对 NX789J 跑一次官方下载/救砖，工具会把配套的 devprg 下载到
`zte\bin\res\NX789J\devprg\`；把它复制到 `tools/` 下命名 `firehose.elf`，或用 `-Programmer` 指定路径。

---

## 4. 刷入流程（EDL 主线）

### 4.1 先检查

```powershell
powershell -ExecutionPolicy Bypass -File tools\edl_flash.ps1 -Check
```

会依次检查：工具箱三件套、programmer、三镜像大小与 EROFS 魔数、从设备现拉 super 的 LP 元数据、
算出三个逻辑分区的绝对起止扇区、校验「镜像 ≤ 分区容量」，最后生成 XML。

预期输出（本机 2026-10-22 实测）：

```
system_a      -> abs_start_sector=33288    sectors=176280   fits=True
system_ext_a  -> abs_start_sector=306184   sectors=61665    fits=True
product_a     -> abs_start_sector=522504   sectors=80006    fits=True
```

### 4.2 进 EDL

```powershell
adb reboot edl
```

等设备管理器出现 `Qualcomm HS-USB QDLoader 9008 (COMx)`（5–10 秒）。
若系统已经起不来：关机后**同时按住 音量+ 和 音量−** 再插 USB。

### 4.3 刷

```powershell
powershell -ExecutionPolicy Bypass -File tools\edl_flash.ps1 -ComPort COM6
```

脚本内部（也可手工照做）：

```powershell
QSaharaServer.exe  -p \\.\COM6 -s 13:firehose.elf
qcedlcmdhelper.exe -p COM6 -m xml -d '<完整 XML 文档，configure MemoryName="ufs" Oem="ZTE"/>'
fh_loader.exe --port=\\.\COM6 --memoryname=ufs --search_path=. --sendxml=edl\los_now.xml --showpercentagecomplete --noprompt --skip_config
fh_loader.exe --port=\\.\COM6 --memoryname=ufs --reset --noprompt --skip_config
```

成功标志：`{All Finished Successfully}` + `percent files transferred 100.00%`，约 0.6–3 秒 / 350–390 MBps。

> ⚠️ `qcedlcmdhelper -d` 必须是**完整 XML 文档**（`<?xml version="1.0" encoding="UTF-8" ?><data><configure .../></data>`）。
> 只发裸 `<configure/>` 会被静默丢弃，随后所有写入都报 `ERROR: Tool doesn't come from ZTE.`

### 4.4 清数据（换 ROM 必做）

data 加密密钥不同，不清会卡在 `Try again / Factory data reset`。

推荐在刷机时顺手清掉两个分区的头部，让 vold 开机自己格式化（这样**不会**弹重置界面）：

```xml
<program SECTOR_SIZE_IN_BYTES="4096" physical_partition_number="0" start_sector="4350760" num_partition_sectors="16384" filename="edl\zeros64m.img" />
<program SECTOR_SIZE_IN_BYTES="4096" physical_partition_number="0" start_sector="4203304" num_partition_sectors="4096"  filename="edl\zeros16m.img" />
```

（前一条清 userdata 前 64 MB，后一条清 metadata 前 16 MB。）

也可以不清，第一次开机在手机上点 `Factory data reset`，同样能起来。

### 4.5 开机

`--reset` 后若设备在 USB 上彻底消失（是断电不是重启），长按电源键开机即可。
正常情况 **50–90 秒**后 `adb devices` 出现设备。

---

## 5. 刷完验证

```bash
adb shell getprop ro.lineage.version        # 23.2-*-UNOFFICIAL-NX789J
adb shell getprop ro.build.version.release  # 16
adb shell getprop sys.boot_completed        # 1
adb shell getprop ro.boot.slot_suffix       # _a
adb shell cat /proc/version                 # 6.6.92-android15-8-g3637f4904cf5...
adb shell dumpsys sensorservice | grep Total      # Total 37 h/w sensors, 37 running
adb shell dumpsys wifi | grep -m1 'Wi-Fi is'      # Wi-Fi is enabled
adb shell settings get system peak_refresh_rate   # 显示设置里应能看到 144Hz 选项
```

完整功能表见 `README.md` 的「完成度」。

---

## 6. 出问题怎么退

| 现象 | 原因 | 处理 |
|---|---|---|
| 亮 LOGO 几秒重启，USB 全程无设备 | `/system` 挂不上（avb 校验失败 / 镜像坏） | 按 §2 换 vendor_boot；或先恢复官方底包 |
| 开机弹 `Try again / Factory data reset` | data 加密密钥不匹配 | 点 reset，或按 §4.4 清 userdata/metadata |
| 卡在 fastboot，`slot-unbootable: yes` | bootloader 拒绝引导 | EDL 跑 `tools/edl_restore_official.ps1` 整机恢复官方 |
| 触摸失灵 | 触摸芯片 ISP 卡死（反复 kill `odm_tsc` 会出现） | EDL `fh_loader --reset` 硬断电复位（不写任何分区）即可 |
| EDL 报 `Tool doesn't come from ZTE` | configure 没发完整 XML | 重发完整 configure，回 `zte download tool: 1` 即恢复 |
| Sahara 报 `Invalid status field 41` | programmer 与机型不匹配 | 换本机对应的 firehose programmer |

**兜底**：`tools/edl_restore_official.ps1 -BackupDir <官方备份>\images`
—— 用 ZTE 官方工具箱的备份整机恢复（GPT + 全部分区），约 1–2 分钟，`{All Finished Successfully}`。

---

## 7. 这套流程刷过多少次

2026-10-19 至 10-22，用同一套流程（官方底包 + 去 avb 的 vendor_boot + 三张镜像）反复刷写多轮，
覆盖 IMS 通话栈、HBM 背光、音频厂商参数兜底、刷新率与自动亮度、指纹协商应用等修复，**每次都能起来，无一次刷坏**。
唯一一次「手机不见了」是 `fh_loader --reset` 执行成了关机，长按电源即恢复。

---

## English TL;DR

1. Prerequisite: **unlocked bootloader** + a full official ZTE-toolbox backup of every partition.
2. **Patch `vendor_boot` first.** The stock first-stage fstab carries `avb=vbmeta_system` + `avb_keys=…` on the `system` / `system_ext` / `product` lines; any non-stock content fails verification and `/system` never mounts (the device reboots right after the logo and USB never appears). Strip those parameters with `tools/vb_unpack.py` + `tools/vb_repack.py` and flash the result to **both** `vendor_boot_a` and `vendor_boot_b`.
3. **Only flash `system`, `system_ext`, `product`** into the logical partitions inside `super`. Never flash `vbmeta` / `vbmeta_system` / `boot` / `dtbo`.
4. You need a **firehose programmer matching this SoC** – it is Qualcomm's bootloader helper, not part of anyone's ROM; a programmer for a different model fails Sahara with `Invalid status field 41`.
5. Wipe the first 64 MB of `userdata` and the first 16 MB of `metadata` (or tap “Factory data reset” on first boot), otherwise you get `init_user0_failed`.
6. Rollback: `tools/edl_restore_official.ps1 -BackupDir <backup>\images` restores the whole official firmware in 1–2 minutes.
