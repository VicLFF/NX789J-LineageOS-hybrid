# 03 · device tree 适配方案（NX789J / LineageOS 23.2）

> 目标：把 `IronShing/android_device_nubia_NX789J@lineage-23.2` 这棵现成的 hybrid 设备树，
> 适配到本机官方底包（ZTE 工具箱全分区备份）并编译出可刷的 system 侧镜像。
>
> **标注约定**
> - 【已验证】= 本会话中通过网络抓取原文或本地二进制解析确认
> - 【需核实】= 逻辑推断或来自移植者描述，必须在 VM / 真机上执行后确认
> - **TODO** = 尚无结论，必须补做的动作

---

## 0. 事实基线（这次适配的全部依据）

【已验证】官方底包解析结果（`ZTEToolBoxParBak/images/`）：

| 项目 | 实测值 |
|---|---|
| boot.img | header v4，kernel_size=38729088（36.9 MB），ramdisk=0 |
| 内核串 | `Linux 6.6.143-android15-8-zte-1006-4k (kleaf@build-host) ... clang 18.0.0` |
| vendor_boot.img | v4，page=4096，header=2128，vendor_ramdisk=8634117，dtb=4488371 |
| init_boot.img | v4，ramdisk=2481974 |
| recovery.img | v4，ramdisk=19861170 |
| dtbo.img | 37 个 entry，总计 14028740 |
| super.img | 17179869184（16 GiB），start_sector=8968 |
| 动态分区 | system_a≈1058M / system_ext_a≈844M / product_a≈4017M / vendor_a≈2619M / odm_a≈93M / vendor_dlkm_a≈32M / system_dlkm_a≈7M |
| vendor FS | **EROFS**（偏移 0x400 处魔数 `e2 e1 f5 e0`） |
| vbmeta 指纹 | system/product/system_ext → `:16/`（**A16/SDK36**）；vendor/odm/vendor_dlkm/dtbo/init_boot/vendor_boot → `:15/`（**A15/SDK35**） |

【已验证】IronShing 设备树原文（`raw.githubusercontent.com/.../lineage-23.2/`），仓库**只有 8 个文件**：
`.gitignore`、`AndroidProducts.mk`、`BoardConfig.mk`、`README.md`、`device.mk`、`lineage_NX789J.mk`、`prebuilts/Image`（36596224 B）、`system.prop`，另有目录 `rootdir/`、`prebuilts/`。

**关键结论（已验证）**：`device.mk` 与 `lineage_NX789J.mk` 里**没有任何** `inherit-product vendor/<oem>/<device>/…-vendor.mk`，
也没有 `PRODUCT_COPY_FILES` 指向 proprietary 目录。也就是说这棵树**不需要 blob 仓库即可编译**（详见第 3 节）。

---

## 1. 仓库获取与放置

### 1.1 克隆到源码树内

```bash
cd ~/android/lineage
mkdir -p device/nubia
git clone https://github.com/IronShing/android_device_nubia_NX789J -b lineage-23.2 device/nubia/NX789J
ls device/nubia/NX789J
```

预期看到：`AndroidProducts.mk  BoardConfig.mk  README.md  device.mk  lineage_NX789J.mk  prebuilts  rootdir  system.prop`。

> 若 GitHub 直连/代理仍不通（本会话遇到的情况），克隆这一步同样会失败。
> 变通：在能访问 GitHub 的环境下载 ZIP 后拷进 VM，或暂时用代理完成这一步。
> 注意 `prebuilts/Image` 有 34.9 MB，会一并拉下来（反正第 4 节要替换它）。

### 1.2 product / lunch 名称（【已验证】原文）

`AndroidProducts.mk` 内容：

```
COMMON_LUNCH_CHOICES := \
    lineage_NX789J-bp4a-user \
    lineage_NX789J-bp4a-userdebug \
    lineage_NX789J-bp4a-eng
```

`lineage_NX789J.mk` 关键行：

```
PRODUCT_NAME := lineage_NX789J
PRODUCT_DEVICE := NX789J
PRODUCT_MANUFACTURER := nubia
PRODUCT_BRAND := nubia
PRODUCT_MODEL := NX789J
PRODUCT_GMS_CLIENTID_BASE := android-zte
```

所以：

```bash
lunch lineage_NX789J-bp4a-userdebug
```

**注意三个容易踩的点：**

1. lunch 名里带 `bp4a`（TARGET_RELEASE 段），不是常见的 `lineage_NX789J-userdebug`。写错会报 `Invalid lunch combo`。
2. `PRODUCT_DEVICE := NX789J` 是全大写，输出目录就是 `out/target/product/NX789J/`。
3. 别名 `breakfast NX789J` 在 LineageOS 里通常也能工作，但它会尝试去拉依赖清单；本树无 `lineage.dependencies`（【已验证】该文件 404），所以**以 `lunch` 为准**。

### 1.3 是否要登记到 local manifest

**TODO（需核实）**：如果把该目录交给 `repo sync` 管理，需要在 `.repo/local_manifests/nx789j.xml` 里登记，否则 `repo sync` 不会更新它（但也不会删除它，手工 clone 的目录可以直接用）。

先按“手工 clone 目录”走最简单，等仓库跑通再决定要不要纳入 `repo` 管理。

---

## 2. BoardConfig 与参考固件逐项对账

### 2.1 对账表

| 项 | IronShing BoardConfig | 参考固件实测 | 判定 |
|---|---|---|---|
| `BOARD_BOOTIMAGE_PARTITION_SIZE` | 100663296 | boot.img 100663296 | ✅ 一致 |
| `BOARD_INIT_BOOT_IMAGE_PARTITION_SIZE` | 8388608 | init_boot.img 8388608 | ✅ 一致 |
| `BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE` | 100663296 | vendor_boot.img 100663296 | ✅ 一致 |
| `BOARD_DTBOIMG_PARTITION_SIZE` | 25165824 | dtbo.img 25165824 | ✅ 一致 |
| `BOARD_RECOVERYIMAGE_PARTITION_SIZE` | 104857600 | recovery.img 104857600 | ✅ 一致 |
| `BOARD_SUPER_PARTITION_SIZE` | 17179869184 | super.img 17179869184 | ✅ 一致 |
| `BOARD_QTI_DYNAMIC_PARTITIONS_SIZE` | 17175674880 | super − 4 MiB = 17175674880 | ✅ 自洽 |
| `BOARD_FLASH_BLOCK_SIZE` | 262144 | = 4096 × 64 | ✅ 自洽 |
| boot header version | 4 | 实测 v4 | ✅ 一致 |
| init_boot header version | 4 | 实测 v4 | ✅ 一致 |
| 页大小 | `BOARD_KERNEL_PAGESIZE := 4096` | vendor_boot page=4096（boot v3/v4 固定 4096） | ✅ 一致 |
| vendor FS | `BOARD_VENDORIMAGE_FILE_SYSTEM_TYPE := erofs` | 实测 EROFS | ✅ 一致 |
| system/system_ext/product FS | 均 `erofs` | 未解析这三个分区的魔数 | ⚠️ **需核实** |
| `AB_OTA_PARTITIONS` | odm product system system_dlkm system_ext vendor vendor_dlkm | super 内同名 7 个 | ✅ 一致 |
| `BOARD_USES_METADATA_PARTITION` | true | metadata 分区 64 MB | ✅ 一致 |
| `PRODUCT_SHIPPING_API_LEVEL` | 35 | vendor 侧 A15/SDK35 | ✅ 一致 |
| **内核** | `prebuilts/Image` 36596224 B（stock 6.6.92） | boot.img 内核 38729088 B（**6.6.143**） | ❌ **不一致，必须替换** |
| `VENDOR_SECURITY_PATCH` | `2026-05-01` | 未读取 vendor 安全补丁 | ⚠️ **需核实** |
| 构建指纹 incremental | `20260606.180913` | vbmeta_system 指纹 `20260606.121727` | ⚠️ **不一致** |
| `BOARD_SHIPPING_API_LEVEL` | 202404（GRF） | 无直接可读证据 | ⚠️ 保留原值，出错再调 |

### 2.2 三处不一致的处理方式

**① 内核文件大小/版本不一致（唯一必须动手的一项）**

`prebuilts/Image` 是 36596224 字节的 stock 6.6.92，我们包里是 38729088 字节的 6.6.143。
由于 hybrid 方案**不重编内核**，且 super 里的 `vendor_dlkm`/`system_dlkm` 是随 6.6.143 一起编译的，
所以必须用**我们包里的内核**，否则模块 vermagic/CRC 对不上、开机阶段直接 kernel panic。
→ 执行第 4 节的抽取脚本。

**② `VENDOR_SECURITY_PATCH`**

设备树里写死 `2026-05-01`，来源是原作者手上的 RedMagicOS 11.0.13MR。
我们依据的是另一个固件包，这个值可能不同。
→ **TODO**：挂载 vendor 读 `ro.vendor.build.security_patch`，把设备树里的值改成实际值（第 3.3 节给命令）。
不过该值只影响构建侧的 `ro.vendor.build.security_patch` 属性与 OTA 校验，**不影响首次开机**，可以先不动。

**③ 构建指纹 incremental 不一致（`180913` vs `121727`）**

`lineage_NX789J.mk` 用 `PRODUCT_BUILD_PROP_OVERRIDES` 写死了：

```
BuildFingerprint=nubia/NX789J/NX789J:16/BQ2A.250705.001-BP2A.250605.031.A3/20260606.180913:user/release-keys
```

而我们包内 `vbmeta_system.img` 的指纹是 `.../20260606.121727:user/release-keys`。
两者只差最后的时间戳，属于同一条 `BQ2A.250705.001-BP2A.250605.031.A3` 基线。
→ 建议**保持设备树原值**，首次开机后用 `getprop ro.build.fingerprint` 比对；若 Play 认证异常再对齐。

**④ system 分区 FS 类型待确认**

vendor 已确认 EROFS；system/system_ext/product 我们只解析了 LP 元数据，没有读文件系统魔数。
→ **TODO**：按 3.3 节方法对 `system_a.img` 也查一次 0x400 偏移的魔数。
若也是 EROFS，则 BoardConfig 现状正确；若是 ext4，需要把对应 `BOARD_*IMAGE_FILE_SYSTEM_TYPE` 改回 `ext4`。

---

## 3. proprietary blobs 策略

### 3.1 结论：**构建上不需要任何 blob**

【已验证】依据：

- `lineage_NX789J.mk` 只 inherit 了 `core_64_bit_only.mk`、`full_base_telephony.mk`、`device/nubia/NX789J/device.mk`、`vendor/lineage/config/common_full_phone.mk`——**没有** vendor blob 的 `-vendor.mk`。
- `device.mk` 里 `PRODUCT_PACKAGES` 全部是 AOSP/LineageOS 源码包（`fastbootd`、`update_engine`、`libwifi-hal-qcom` 等），`PRODUCT_COPY_FILES` 只拷本树 `rootdir/` 下的两个文件。
- 仓库里根本没有 `extract-files.sh`、`proprietary/`、`vendor/nubia/` 这类东西。

原因很直白：hybrid 方案**不生成 vendor/odm/vendor_dlkm/system_dlkm**，这四个分区原样保留在设备的 super 里，
blob 本来就在设备上，编译时无从谈起“塞进镜像”。

> 结论：**不要**去跑 `extract-files.sh`，也不要去建 `vendor/nubia/NX789J` 仓库。多此一举，还会把 stock 与 LOS 的 HAL 来源搞混。

### 3.2 但“只读核对”仍然要做

虽然不打包，我们仍需从 vendor 分区读出几个属性，用来填第 2 节那几个 ⚠️ 项：

- `ro.vendor.build.version.release` / `.sdk` —— 确认 vendor 真的是 A15/SDK35
- `ro.vendor.build.security_patch` —— 填 `VENDOR_SECURITY_PATCH`
- `ro.board.platform` —— 应为 `sun`
- `ro.boot.hardware` —— 用于确认硬件族
- `ro.vendor.product.device` —— 应为 NX789J

### 3.3 抽取 + 挂载 EROFS 的完整命令

**① 先从 super.img 抽出单个分区**

在 Windows 侧我们已有 `porting/extract_vendor.py` 验证过解析逻辑；VM 里没有这个脚本，用下面这个自包含版本（等价逻辑，已按 LP metadata v10.2 / extent 24 字节格式实现）：

```bash
cat > ~/lpextract.py <<'PY'
import struct, sys, os
super_img, out_dir = sys.argv[1], sys.argv[2]
blob = open(super_img, 'rb').read(2*1024*1024)
idx = blob.find(b'\x30PLA')                      # LP_METADATA_HEADER_MAGIC, LE
assert idx >= 0, "not an LP super image"
hs = struct.unpack_from('<I', blob, idx+8)[0]
meta = idx + hs
po, pn, pe = struct.unpack_from('<III', blob, idx+80)
eo, en, ee = struct.unpack_from('<III', blob, idx+92)
parts, exts = [], []
for i in range(pn):
    b = meta + po + i*pe
    name = blob[b:b+36].split(b'\x00')[0].decode()
    _, first, num, _ = struct.unpack_from('<IIII', blob, b+36)
    parts.append((name, first, num))
for i in range(en):
    b = meta + eo + i*ee
    if ee == 24:
        ns, tt = struct.unpack_from('<QI', blob, b); td = struct.unpack_from('<Q', blob, b+12)[0]
    else:
        ns, tt = struct.unpack_from('<QI', blob, b); td = struct.unpack_from('<Q', blob, b+16)[0]
    exts.append((ns, tt, td))
os.makedirs(out_dir, exist_ok=True)
src = open(super_img, 'rb')
for name, first, num in parts:
    if num == 0 or not name.endswith('_a'):
        continue
    total = sum(exts[first+k][0] for k in range(num))
    dst = open(os.path.join(out_dir, name + '.img'), 'wb')
    for k in range(num):
        ns, tt, td = exts[first+k]
        src.seek(td*512); remain = ns*512
        while remain > 0:
            c = src.read(min(remain, 8*1024*1024))
            if not c: break
            dst.write(c); remain -= len(c)
    dst.close()
    print(f"{name}: {total*512/1024/1024:.1f} MB")
src.close()
PY

python3 ~/lpextract.py /path/to/Firmware/super.img ~/super_parts
ls -lh ~/super_parts
```

预期产出 `system_a.img / system_ext_a.img / product_a.img / vendor_a.img / odm_a.img / vendor_dlkm_a.img / system_dlkm_a.img`。

**② 挂载 EROFS 只读查看**

```bash
sudo apt install -y erofs-utils          # 提供 fsck.erofs / dump.erofs / mkfs.erofs
sudo mkdir -p /mnt/vendor

# 方式 A：内核原生挂载（Ubuntu 6.x 内核默认带 erofs）
sudo mount -t erofs -o loop,ro ~/super_parts/vendor_a.img /mnt/vendor

# 方式 B：内核不支持时，用 fsck.erofs 直接解包
# sudo fsck.erofs --extract=/mnt/vendor ~/super_parts/vendor_a.img

# 方式 C：fuse 挂载（装 erofs-utils 后若有 erofsfuse）
# sudo erofsfuse ~/super_parts/vendor_a.img /mnt/vendor
```

挂上之后读关键属性：

```bash
sudo grep -E 'ro\.vendor\.build\.(version|security_patch)|ro\.board\.platform|ro\.boot\.hardware|ro\.vendor\.product\.device' /mnt/vendor/build.prop
sudo umount /mnt/vendor
```

**③ 顺手确认 system 侧 FS 类型**

```bash
for p in system_a system_ext_a product_a; do
  printf '%-16s ' "$p"
  printf '\x53\xef' >/dev/null  # 占位，见下
  python3 - "$HOME/super_parts/$p.img" <<'PY'
import sys
f = open(sys.argv[1],'rb'); f.seek(0x400); m = f.read(4); f.close()
print('EROFS' if m == b'\xe2\xe1\xf5\xe0' else ('EXT4' if m[0:2]==b'\x53\xef' else '其他: '+m.hex()))
PY
done
```

（EROFS 魔数在 0x400；EXT4 的 `53 ef` 在 0x438，上面脚本对 EXT4 的判断是近似的，仅作快速筛查。**TODO**：结果出来后把 BoardConfig 的 FS 类型对齐。）

### 3.4 如果将来确实要保留某类文件

只有一种情况需要往 system 侧塞 vendor 的东西：**某个 HAL 的 AIDL 接口必须由 system 提供而 stock 只给了二进制**。
届时按下列目录取（仅作参考，当前不需要）：

| 分区 | 通常需要保留的目录 |
|---|---|
| vendor_a | `firmware/`、`lib/modules/`、`lib64/hw/`、`bin/hw/`、`etc/vintf/`、`etc/init/` |
| odm_a | `lib64/`、`bin/hw/`、`etc/`、`firmware/`、`overlay/` |
| vendor_dlkm_a | `lib/modules/`（内核模块，约 280 个 .ko） |
| system_dlkm_a | `lib/modules/`（GKI 公共模块） |

当前 hybrid 方案完全不动它们，所以表里内容**不需要执行**。

---

## 4. 内核策略

### 4.1 为什么走“预编译 stock 内核”而不是 `TARGET_KERNEL_SOURCE`

| 维度 | IronShing/现实 | 说明 |
|---|---|---|
| 构建系统 | LineageOS 用 Makefile + `TARGET_KERNEL_CONFIG`；ZTE 用 **Kleaf/Bazel**（GKI 2.0） | 两者不兼容，硬接等于把 Kleaf 塞进 make 流程 |
| 公开源码 | ZTE 开源站放的是 **6.6.30**（`NX789S_Android15_kernel(6.6.30).tar.gz`） | 设备实际跑 **6.6.143** |
| 模块耦合 | super 里 `vendor_dlkm` 约 280 个 `.ko`，带 vermagic / symbol CRC / CFI 校验 | 换内核必须**同批重编**这 280 个模块，否则 `insmod` 全部失败 |
| 结论 | 用设备原 boot.img 里的 `Image` | 与 vendor_dlkm 天然匹配，零风险 |

【已验证】设备树原文：

```
BOARD_KERNEL_IMAGE_NAME := Image
TARGET_KERNEL_ARCH := arm64
TARGET_KERNEL_CONFIG := gki_defconfig
TARGET_PREBUILT_KERNEL := $(DEVICE_PATH)/prebuilts/Image
TARGET_FORCE_PREBUILT_KERNEL := true
BOARD_USES_GENERIC_KERNEL_IMAGE := true
TARGET_HAS_GENERIC_KERNEL_IMAGE_HEADERS := true
```

### 4.2 从 boot.img 抽出 `Image`（替换现成的 6.6.92）

Android boot header v4 布局：`header(1580B，按页对齐到 4096) → kernel(kernel_size) → ramdisk(0) → …`。

```bash
cat > ~/extract_kernel.py <<'PY'
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, 'rb') as f:
    h = f.read(4096)
assert h[:8] == b'ANDROID!', "不是 Android boot 镜像"
ksize, rsize = struct.unpack_from('<II', h, 8)
hsize = struct.unpack_from('<I', h, 20)[0]
hver  = struct.unpack_from('<I', h, 40)[0]
page  = 4096
off   = (hsize + page - 1) // page * page
print(f"header_version={hver} hdr_size={hsize} kernel={ksize} ramdisk={rsize} kernel_off={off}")
with open(src, 'rb') as f, open(dst, 'wb') as o:
    f.seek(off)
    o.write(f.read(ksize))
print("written:", dst)
PY

python3 ~/extract_kernel.py /path/to/Firmware/boot.img ~/Image
ls -l ~/Image          # 期望 38729088 字节
```

替换到设备树（**先备份原文件**）：

```bash
cd ~/android/lineage/device/nubia/NX789J
cp prebuilts/Image prebuilts/Image.stock-6.6.92.bak
cp ~/Image prebuilts/Image
ls -l prebuilts/
```

**验证点（【已验证】数值）**：换完后 `prebuilts/Image` 应为 **38729088** 字节，且能在里面搜到内核串：

```bash
grep -a -o 'Linux version 6\.6\.[0-9]*-[a-z0-9-]*' prebuilts/Image | head -1
# 期望输出形如：Linux version 6.6.143-android15-8-zte-1006-4k
```

如果输出的版本不是 6.6.143，说明抽错了偏移，回到上一步检查 `kernel_off`。

### 4.3 （可选）从 vendor_boot 抽 dtb

只有当需要自己打包 vendor_boot 时才用得上；hybrid 方案沿用 stock vendor_boot，**通常不需要**。
记录方法备查：

```bash
cat > ~/extract_dtb.py <<'PY'
import struct, sys
src, dst = sys.argv[1], sys.argv[2]
with open(src, 'rb') as f:
    h = f.read(4096)
assert h[:8] == b'VNDRBOOT'
page = struct.unpack_from('<I', h, 12)[0]
vra  = struct.unpack_from('<I', h, 24)[0]
hsz  = struct.unpack_from('<I', h, 2096)[0]
dtbs = struct.unpack_from('<I', h, 2100)[0]
off  = (hsz + page - 1)//page*page + (vra + page - 1)//page*page
print(f"page={page} hdr={hsz} ramdisk={vra} dtb={dtbs} dtb_off={off}")
with open(src,'rb') as f, open(dst,'wb') as o:
    f.seek(off); o.write(f.read(dtbs))
PY
python3 ~/extract_dtb.py /path/to/Firmware/vendor_boot.img ~/dtb.img   # 期望 4488371 字节
```

---

## 5. 构建与产物

### 5.1 编译前的一次性检查

```bash
cd ~/android/lineage
# 确认源码树分支
repo info 2>/dev/null | head -5 || cat .repo/manifest.xml | head -20
# 确认设备树到位
ls device/nubia/NX789J/prebuilts/Image && stat -c '%s' device/nubia/NX789J/prebuilts/Image
# 期望 38729088
```

### 5.2 标准流程（推荐）

```bash
cd ~/android/lineage
source build/envsetup.sh
lunch lineage_NX789J-bp4a-userdebug
m systemimage systemextimage productimage
```

> `m` 是 AOSP envsetup 自带命令。若你的环境没有 `mka`，用 `m` 即可；
> 想并行加速可加 `-j8`（15 GB 内存的机器别超过 8，见风险清单）。

### 5.3 设备树 README 给的等价 soong_ui 调用

```bash
cd ~/android/lineage
export TARGET_PRODUCT=lineage_NX789J
export TARGET_BUILD_VARIANT=userdebug
export TARGET_RELEASE=bp4a
export LINEAGE_BUILD=NX789J
export LLVM_AOSP_PREBUILTS_VERSION="$(build/soong/scripts/get_clang_version.py)"
build/soong/soong_ui.bash --make-mode systemimage systemextimage productimage
```

两种方式等价，`lunch` 那条更不容易漏环境变量。

### 5.4 产物路径

```
out/target/product/NX789J/system.img
out/target/product/NX789J/system_ext.img
out/target/product/NX789J/product.img
```

（若 FS 类型为 erofs，文件名相同，只是内部格式是 EROFS。可用 `file` 或看大小判断。）

### 5.5 hybrid 方案下到底替换哪几块

**只替换 super 里的 3 个逻辑分区**：

| 逻辑分区 | 动作 |
|---|---|
| `system_a` | **用 LOS 的 system.img 覆盖** |
| `system_ext_a` | **用 LOS 的 system_ext.img 覆盖** |
| `product_a` | **用 LOS 的 product.img 覆盖** |
| `vendor_a` | 保留 stock |
| `odm_a` | 保留 stock |
| `vendor_dlkm_a` | 保留 stock |
| `system_dlkm_a` | 保留 stock |

`boot / init_boot / vendor_boot / dtbo / vbmeta / recovery` **全部不动**（沿用设备上现有的）。

---

## 6. 刷入与验证

### 6.1 前置：必须先有 EDL 全盘备份

没有备份不要刷。备份方法见 `porting/01-参考固件分析报告.md` 与路线图第 0 节。

### 6.2 刷入（fastbootd，只动 logical partition）

```bash
# 进 userspace fastboot（动态分区必须用 fastbootd，不能用 bootloader 的 fastboot）
adb reboot fastboot
fastboot devices

# 确认当前槽位（本机 stock 为 A 槽）
fastboot getvar current-slot

# 刷三个逻辑分区（fastbootd 会在空间允许时自动 resize）
fastboot flash system      out/target/product/NX789J/system.img
fastboot flash system_ext  out/target/product/NX789J/system_ext.img
fastboot flash product     out/target/product/NX789J/product.img

fastboot reboot
```

**注意三点：**

1. `fastboot flash <logical>` 只在 **fastbootd**（userspace fastboot）里可用；在 bootloader 的 fastboot 里刷会报 `unknown partition`。
2. 三个新镜像的总大小如果超过 stock 里对应分区占用 + 空闲空间，会报 `Not enough space to resize partition`。这时改为**整包重做 super** 再刷 `super`（需要 `lpmake`，见 6.4）。
3. **不要刷 vbmeta**。stock vbmeta 已经是允许自定义的状态；动它容易进 bootloop。

### 6.3 首次开机验证

```bash
adb wait-for-device
adb shell getprop ro.build.version.sdk        # 期望 36
adb shell getprop ro.build.version.release    # 期望 16
adb shell getprop ro.product.device           # 期望 NX789J
adb shell getprop ro.lineage.version          # 期望有值（形如 23.2-…）
adb shell getprop ro.build.fingerprint        # 与 lineage_NX789J.mk 里的覆盖值比对
```

日志侧观察：

```bash
adb logcat -b all | grep -E 'AndroidRuntime|FATAL|avc: denied|init: .*failed' | head -50
adb shell dmesg | grep -iE 'vendor_dlkm|module|vermagic|avc' | head -50
```

判读：

| 现象 | 含义 |
|---|---|
| 卡开机动画、logcat 有 `avc: denied` 刷屏 | SELinux 策略问题（第 7 节风险 3） |
| `vendor_dlkm` 模块 insmod 失败 / vermagic 不匹配 | 内核换错（第 4 节没做对） |
| 反复重启、logcat 起不来 | 大概率 fstab/分区不对，回 6.2 检查是不是刷错分区 |
| 能进桌面但相机/指纹不通 | HAL 未绑定，属正常 bring-up 阶段问题 |

### 6.4 失败回退

| 情况 | 回退方式 |
|---|---|
| 能进 fastbootd | `fastboot flash system` 换回 stock 镜像（需你事先从 super 里 dump 出来） |
| 进不了系统但能进 bootloader | `fastboot reboot fastboot` 重试，或 EDL |
| 彻底黑屏 / 只出 MemoryDump | EDL/9008，用参考固件里的 firehose 流程恢复 |

> **强烈建议**：刷之前先用 3.3 节的脚本把 stock 的 `system_a.img / system_ext_a.img / product_a.img` dump 出来存好，
> 这样回退时不需要依赖 EDL。

### 6.5 整包重做 super（6.2 空间不足时的逃生方案）

**TODO（需核实）**：`lpmake` 的具体参数需要按实测的 dynamic partition 元数据填，不能照抄。
先执行 `lpdump` 取得 stock 的分区列表：

```bash
sudo apt install -y android-sdk-libsparse-utils 2>/dev/null || true
lpdump ~/super_parts/super_meta_dump 2>/dev/null || echo "lpdump 不可用，用 lpextract.py 的元数据部分替代"
```

拿到 group/分区名/尺寸后再组装。**这一步在首次编译成功前不要展开**，先按 6.2 的最小改动路径走。

---

## 7. 风险清单与 TODO

| # | 风险 / 未决项 | 影响 | 处理 |
|---|---|---|---|
| 1 | **vendor 基线未知**：设备树针对 RedMagicOS 11.0.13MR；我们只有 施 的澎湃 OS 包 包 | 若 vendor 不是同基线，HAL 接口可能对不上 | **TODO**：按 3.3 读 `ro.vendor.build.*`，与 `11.0.13MR` 比对 |
| 2 | `VENDOR_SECURITY_PATCH := 2026-05-01` 写死 | 仅属性/OTA 层面 | 读实际值后改；不影响首启 |
| 3 | `TARGET_USES_PREBUILT_VENDOR_SEPOLICY := true` + `include device/qcom/sepolicy_vndr/SEPolicy.mk` | 若 vendor sepolicy 与我们的 vendor 版本不匹配 → 首启 avc 刷屏 | **TODO**：确认 `device/qcom/sepolicy_vndr` 已随源码同步；必要时按实际 vendor 调整 |
| 4 | system 侧 FS 类型未确认（只有 vendor 验证是 EROFS） | FS 类型写错 → 镜像无法挂载 | **TODO**：3.3 节 ③ |
| 5 | APEX 与 A15 vendor 的兼容性 | A16 system 的 APEX 版本高于 vendor 预期时可能启动失败 | 观察首启日志；必要时回退 APEX 版本 |
| 6 | super 空间：LOS 的 system+system_ext+product 可能大于 stock 占用 | `fastboot flash` resize 失败 | 预案：6.4 整包重做 super |
| 7 | erofs 镜像构建路径需要 `PRODUCT_USE_DYNAMIC_PARTITION_SIZE` | 缺了会 `KeyError: 'partition_size'` | 已由 `device.mk` 默认值覆盖；若仍报错，需移植 NX809J 时代的 `build_image.py` canned_fs_config 补丁（**TODO**：该补丁不在本仓库 8 个文件内，需另行找） |
| 8 | 构建机 Ubuntu 26.04 / Python 3.14 过新 | AOSP 构建脚本兼容性 | 已识别；编译期报错优先怀疑此处 |
| 9 | 内存 15 GB + 4 GB swap | 编译 OOM | 先扩到 32 GB swap，`-j8` |
| 10 | GitHub 拉取受阻（本会话实测） | clone/sync 中断 | 代理修好或换网络；源码 sync 完成前不要开始编译 |
| 11 | 设备树无 `lineage.dependencies`（已验证 404） | `breakfast` 可能拉不到依赖 | 用 `lunch`，不依赖该文件 |
| 12 | `device.mk` 引用 `$(LOCAL_PATH)/overlay`，但仓库无 `overlay/` 目录 | 可能有 overlay 缺失告警 | 一般无害；若构建报错，建空目录或补 overlay |
| 13 | 该树从未被公开验证可开机（原作者 README 自称 Bring-up） | 首次开机失败是预期内 | 按 6.3 逐条排查，不要一次改多处 |

---

## 附录 A · 关键文件与命令索引

| 用途 | 路径 / 命令 |
|---|---|
| 设备树 | `device/nubia/NX789J/` |
| 预编译内核 | `device/nubia/NX789J/prebuilts/Image`（替换后应为 38729088 B） |
| product 名 | `lineage_NX789J` |
| lunch | `lunch lineage_NX789J-bp4a-userdebug` |
| 构建目标 | `systemimage systemextimage productimage` |
| 产物 | `out/target/product/NX789J/` |
| 抽分区脚本 | `~/lpextract.py` |
| 抽内核脚本 | `~/extract_kernel.py` |
| 刷机 | `adb reboot fastboot` → `fastboot flash system/system_ext/product` |

## 附录 B · 一页速查（把本方案压成执行顺序）

```bash
# 1. 设备树
cd ~/android/lineage && mkdir -p device/nubia
git clone https://github.com/IronShing/android_device_nubia_NX789J -b lineage-23.2 device/nubia/NX789J

# 2. 换内核（6.6.143）
python3 ~/lpextract.py      /path/to/Firmware/super.img   ~/super_parts   # 备用
python3 ~/extract_kernel.py /path/to/Firmware/boot.img    ~/Image
cp device/nubia/NX789J/prebuilts/Image{,.stock-6.6.92.bak}
cp ~/Image device/nubia/NX789J/prebuilts/Image

# 3. 核对 vendor 版本（填第 2 节的 ⚠️）
sudo mount -t erofs -o loop,ro ~/super_parts/vendor_a.img /mnt/vendor
sudo grep -E 'ro\.vendor\.build\.(version|security_patch)' /mnt/vendor/build.prop
sudo umount /mnt/vendor

# 4. 编译
source build/envsetup.sh && lunch lineage_NX789J-bp4a-userdebug
m systemimage systemextimage productimage

# 5. 刷入
adb reboot fastboot
fastboot flash system     out/target/product/NX789J/system.img
fastboot flash system_ext out/target/product/NX789J/system_ext.img
fastboot flash product    out/target/product/NX789J/product.img
fastboot reboot
```

---

## 附录 C · 本文档中所有【需核实】项汇总

1. system / system_ext / product 三个分区的实际文件系统类型
2. `vendor_a` 的 `ro.vendor.build.version.release` / `.sdk` / `.security_patch`
3. `ro.board.platform` 是否为 `sun`、`ro.vendor.product.device` 是否为 `NX789J`
4. `BOARD_SHIPPING_API_LEVEL := 202404` 是否与本机 GRF 冻结版本一致
5. 构建指纹 incremental（`180913` vs `121727`）是否需要对齐
6. `fastboot flash <logical>` 在本机 fastbootd 上能否自动 resize（取决于分区剩余空间）
7. `device/qcom/sepolicy_vndr` 是否已在本地源码树中（`ls device/qcom/`）
