**中文摘要** · [English](#english)

# 本仓库故意不包含的文件（中文）

下面这些东西都属于 ZTE / nubia / 高通 / Goodix，**不允许再分发**。你要从自己拥有的机器（或官方服务固件包）里提取，放到 `device/nubia/NX789J/` 下对应的路径，否则编译会因为模块/文件缺失停下。

| 类别 | 来源分区 | 用途 |
|---|---|---|
| **IMS 组件**<br>`prebuilts/ims/system_ext/...` | 官方 `system_ext` | VoLTE / VoNR。8 个 APK（ims、QtiTelephony、qcrilmsgtunnel、imssettings、QtiTelephonyService、ImsRcsService、ImsDataChannelService、uceShimService）+ 2 个 `libims*_jni.so` + 约 15 个 `vendor.qti.ims.*` / `com.qualcomm.qti.uceservice-*` jar + `qcrilhook` 与其权限 xml |
| **指纹用户态**<br>`prebuilts/fp/...` | 官方 `system` | `FingerprintSensorUi_ZTE`(=`com.fingerprint.sensorservice`)、`FingerprintService_ZTE`、`FingerPrintSettings_ZTE` + 3 个 privapp 白名单 xml。注意：**装了也修不好指纹**，原因见主 README 的已知问题 |
| **内核 Image**（可选）<br>`prebuilts/Image` | 官方 `boot.img` | 只有你要编 `boot.img` 时才用到。本移植不刷 boot，可以保留上游的。若替换，必须用**你自己**机器上那颗内核 —— vendor_dlkm 里每个模块都和它的 vermagic / CRC / CFI 绑定 |

两个必须踩的坑：

1. **删掉 APK 里自指向的 overlay 节点。** 那 5 个 IMS APK 的 `AndroidManifest.xml` 里有一个 `<overlay android:targetPackage="<自己包名>" android:requiredSystemPropertyName="ro.boot.vendor.qspa.modem" .../>`，PM 会把它当 RRO，于是**整个包被丢弃**（日志：`overlay ignored due to required system property`）。删掉这个元素（120 字节）即可。
2. **用平台密钥重签，但不要加 `-w`。** `signapk -w` 是给整包 OTA 用的，产出的 APK **既无 v1 也无 v2 签名**，装不上。

提取方式只写了命令行，见下。

---

<a id="english"></a>

# Files this repository intentionally does not contain

Everything listed here belongs to ZTE / nubia / Qualcomm / Goodix and **must not be
redistributed**. Extract them from a device you own (or from an official service
firmware package) and drop them into the paths shown, relative to
`device/nubia/NX789J/`.

The device tree patches in `patches/0001-*` reference these paths, so the build will
fail with a missing-module / missing-file error until they are in place.

---

## 1. IMS stack (from the stock `system_ext` partition)

Needed for VoLTE / VoNR. The APKs are re-signed with the AOSP *platform* key by the
build, so the copies you pull keep their original signature and are re-signed during
the build — do not sign them yourself.

```
prebuilts/ims/system_ext/priv-app/ims/ims.apk                     # org.codeaurora.ims
prebuilts/ims/system_ext/priv-app/QtiTelephony/QtiTelephony.apk    # com.qti.phone
prebuilts/ims/system_ext/priv-app/qcrilmsgtunnel/qcrilmsgtunnel.apk
prebuilts/ims/system_ext/priv-app/imssettings/imssettings.apk      # com.qualcomm.qti.ims
prebuilts/ims/system_ext/app/QtiTelephonyService/QtiTelephonyService.apk
prebuilts/ims/system_ext/app/ImsRcsService/ImsRcsService.apk       # vendor.qti.imsrcs
prebuilts/ims/system_ext/app/ImsDataChannelService/ImsDataChannelService.apk
prebuilts/ims/system_ext/app/uceShimService/uceShimService.apk
prebuilts/ims/system_ext/lib64/libimsmedia_jni.so
prebuilts/ims/system_ext/lib64/libimscamera_jni.so
```

Plus these prebuilt jars / permission XMLs from the stock `system_ext`
(the jars for `qti-telephony-utils`, `qti-telephony-hidl-wrapper`, `extphonelib` and
`ims-ext-common` are **not** needed — they are built from source at
`vendor/codeaurora/telephony`):

```
prebuilts/ims/system_ext/framework/vendor.qti.ims.*-java.jar        # ~10 files
prebuilts/ims/system_ext/framework/com.qualcomm.qti.uceservice-V2.{0,1,2,3}-java.jar
prebuilts/ims/system_ext/framework/qcrilhook.jar
prebuilts/ims/system_ext/etc/permissions/{qcrilhook,vendor.qti.ims.rcsservice}.xml
```

Two things must be done to the APKs or the package manager will refuse them:

1. **Strip the self-targeting overlay node** from `AndroidManifest.xml`. Those five
   APKs carry
   `<overlay android:targetPackage="<own package>" android:requiredSystemPropertyName="ro.boot.vendor.qspa.modem" android:requiredSystemPropertyValue="enabled"/>`
   as a child of `<manifest>`, so PM treats them as RROs and silently drops the whole
   package. Removing the element (120 bytes) fixes it.
2. **Re-sign with the platform key**, without `-w`:

   ```
   java -Djava.library.path=out/host/linux-x86/lib64 \
        -jar out/host/linux-x86/framework/signapk.jar \
        build/make/target/product/security/platform.x509.pem \
        build/make/target/product/security/platform.pk8 in.apk out.apk
   ```

   `-w` is for whole-file OTA signing and produces an APK with **neither** v1 nor v2
   signatures, which will not install.

## 2. ZTE fingerprint UI stack (from the stock `system` partition)

Only needed if you want the ZTE fingerprint user-space (it is installed but the
sensor still does not work — see the known-issues section of the main README).

```
prebuilts/fp/apk/FingerprintSensorUi_ZTE.apk       # com.fingerprint.sensorservice
prebuilts/fp/apk/FingerprintService_ZTE.apk        # com.ztefingerprint.service
prebuilts/fp/apk/FingerPrintSettings_ZTE.apk       # com.zte.fingerprints
prebuilts/fp/permissions/privapp_whitelist_com.fingerprint.sensorservice.xml
prebuilts/fp/permissions/privapp_whitelist_com.ztefingerprint.service.xml
prebuilts/fp/permissions/privapp_whitelist_com.zte.fingerprints.xml
```

## 3. Kernel image (optional)

`prebuilts/Image` is only consumed if you build `boot.img`. This port does **not**
flash `boot`, so it can stay as shipped upstream. If you do replace it, use the
kernel from **your own** stock `boot.img`, and remember that every `vendor_dlkm`
module is built against that exact kernel (same vermagic / CRC / CFI).

---

## How to extract on the device

```bash
adb root
adb shell 'mkdir -p /data/local/tmp/out'
adb shell 'cp -r /system_ext/priv-app/ims /data/local/tmp/out/'
adb pull /data/local/tmp/out/ims ./ims
```

or from a firmware image:

```bash
python tools/extract_super.py super.img out system_ext_a 0x3000
fsck.erofs --path=/priv-app/ims --extract=./ims out/system_ext_a.img
```

(`tools/extract_super.py --help` for the extent walking, `fsck.erofs` ships with
`erofs-utils`.)
