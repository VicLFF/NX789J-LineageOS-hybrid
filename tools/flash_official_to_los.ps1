<#
.SYNOPSIS
    从「官方 RedMagicOS 底包」刷到 LineageOS —— 在本机实测通过的一键脚本。

.DESCRIPTION
    做的事（严格按 docs/17 的三条铁律）：
      1. 从设备当前 super 里读出 LP 元数据（磁盘上的真实布局），算出 system_a / system_ext_a / product_a
         的绝对起止扇区，生成 fh_loader XML；
      2. 把去 avb 的 vendor_boot 写进 vendor_boot_a 与 vendor_boot_b（官方底包必须做，否则 /system 挂不上）；
      3. 把三个 LineageOS 逻辑分区镜像写进 super 内对应位置；
      4. 清 userdata 前 64 MB 与 metadata 前 16 MB（换 ROM 必做，否则报 init_user0_failed）；
      5. EDL 写入后断电复位。

    绝不触碰：vbmeta / vbmeta_system / boot / init_boot / dtbo。

.PARAMETER ImageDir
    存放 system.img / system_ext.img / product.img 目录（默认 .\release）
.PARAMETER VendorBoot
    去 avb 后的 vendor_boot 镜像（默认 .\release\vendor_boot_noverity.img）
.PARAMETER ToolDir
    QSaharaServer.exe / qcedlcmdhelper.exe / fh_loader.exe 所在目录
.PARAMETER Programmer
    firehose programmer（*.elf）。留空则按顺序自动探测。
.PARAMETER ComPort
    设备管理器里 QDLoader 9008 的端口号，例如 COM6
.PARAMETER SuperHead
    可选的 super 镜像（或官方备份里的 super.img）。给了就直接读它前 512 KB 当 LP 元数据，
    不依赖设备在线。官方底包刷机时推荐用它，偏移会按官方布局算。

.PARAMETER SkipVendorBoot
    已经刷过去 avb 的 vendor_boot 时跳过它
.PARAMETER SkipWipe
    不清 userdata/metadata
.PARAMETER Check
    只做检查与 XML 生成，不写设备

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\flash_official_to_los.ps1 -Check
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\flash_official_to_los.ps1 -ComPort COM6
#>
[CmdletBinding()]
param(
    [string]$ImageDir   = '',
    [string]$VendorBoot = '',
    [string]$ToolDir    = 'C:\Users\Administrator\Desktop\zte\bin\tool\Win',
    [string]$Programmer = '',
    [string]$ComPort    = '',
    [string]$SuperHead  = '',
    [switch]$SkipVendorBoot,
    [switch]$SkipWipe,
    [switch]$Check
)

# ===== 来源与致谢 / Credits =====
# 官方底包备份与 EDL 恢复工具 ZTE 工具箱（ZTEToolBox）作者：酷安 @某贼
# 本脚本只使用 LineageOS 编译产物 + 官方备份里的文件，不使用任何第三方 ROM 包的内容。
# ================================

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $PSCommandPath
if (-not $ImageDir)   { $ImageDir   = Join-Path $here '..\release' }
if (-not $VendorBoot) { $VendorBoot = Join-Path $ImageDir 'vendor_boot_noverity.img' }
function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }
function Ok($m)  { Say "  [OK] $m" 'Green' }
function Bad($m) { Say "  [!!] $m" 'Red' }
function Step($m){ Say "`n== $m" 'Cyan' }

# ---------- 0. 路径与工具 ----------
Step '0. 检查工具与镜像'

$need = @('QSaharaServer.exe', 'qcedlcmdhelper.exe', 'fh_loader.exe')
$toolOk = $true
foreach ($t in $need) {
    $full = Join-Path $ToolDir $t
    if (Test-Path $full) { Ok "$t" } else { Bad "缺少 $t（-ToolDir $ToolDir）"; $toolOk = $false }
}

if (-not $Programmer) {
    $cands = @(
        (Join-Path $here 'firehose.elf'),
        (Join-Path $here 'prog_firehose_ddr.elf'),
        'C:\Users\Administrator\Desktop\zte\bin\res\NX789J\devprg\prog_firehose_ddr.elf'
    )
    $Programmer = $cands | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ($Programmer -and (Test-Path $Programmer)) { Ok "programmer: $Programmer" }
else { Bad '找不到 firehose programmer（用 -Programmer 指定；必须与本机型号匹配）'; $toolOk = $false }

$imgs = @{
    system_a     = Join-Path $ImageDir 'system.img'
    system_ext_a = Join-Path $ImageDir 'system_ext.img'
    product_a    = Join-Path $ImageDir 'product.img'
}
$imgOk = $true
foreach ($k in $imgs.Keys) {
    $f = $imgs[$k]
    if (Test-Path $f) {
        $len = (Get-Item $f).Length
        $fh = [IO.File]::OpenRead($f)
        $buf = New-Object byte[] 4
        [void]$fh.Read($buf, 0, 4)
        $fh.Close()
        # EROFS 超级块魔数在 +1024
        $fh = [IO.File]::OpenRead($f)
        [void]$fh.Seek(1024, 'Begin')
        $m = New-Object byte[] 4
        [void]$fh.Read($m, 0, 4)
        $fh.Close()
        $isErofs = ($m[0] -eq 0xE2 -and $m[1] -eq 0xE1 -and $m[2] -eq 0xF5 -and $m[3] -eq 0xE0)
        if ($isErofs) { Ok ("{0,-13} {1,12:N0} B  EROFS" -f $k, $len) }
        else { Bad ("{0,-13} 不是 EROFS 镜像" -f $k); $imgOk = $false }
    } else { Bad "缺少 $($imgs[$k])"; $imgOk = $false }
}

$vbOk = $true
if (-not $SkipVendorBoot) {
    if (Test-Path $VendorBoot) {
        $len = (Get-Item $VendorBoot).Length
        if ($len -eq 100663296) { Ok ("vendor_boot   {0,12:N0} B  (100663296 = 分区大小)" -f $len) }
        else { Bad "vendor_boot 大小 $len 与分区 100663296 不符"; $vbOk = $false }
    } else { Bad "缺少 $VendorBoot"; $vbOk = $false }
}

if (-not ($toolOk -and $imgOk -and $vbOk)) { Say "`n检查未通过，退出。" 'Red'; exit 1 }

# ---------- 1. 读设备 super 的 LP 元数据 ----------
Step '1. 读取设备 super 分区布局（LP metadata）'
$adb = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb -and (Test-Path 'C:\platform-tools\adb.exe')) { $adb = 'C:\platform-tools\adb.exe' }
if (-not $adb) { Bad '找不到 adb'; exit 1 }

$devs = & $adb devices | Select-String 'device$'
if (-not $devs) { Bad '没有已授权的 adb 设备（先在系统里打开 USB 调试并授权）'; exit 1 }
Ok "adb 设备 $(($devs | Measure-Object).Count) 台"

$head = Join-Path $ImageDir 'super_head.bin'
if ($SuperHead -and (Test-Path $SuperHead)) {
    $fs = [IO.File]::OpenRead($SuperHead)
    $buf = New-Object byte[] 524288
    [void]$fs.Read($buf, 0, 524288)
    $fs.Close()
    [IO.File]::WriteAllBytes($head, $buf)
    Ok "使用外部 super 头部：$SuperHead（按它的布局算偏移）"
} else {
& $adb root 2>&1 | Out-Null
Start-Sleep -Seconds 2
& $adb shell 'dd if=/dev/block/by-name/super of=/data/local/tmp/super_head.bin bs=4096 count=128 2>/dev/null'
& $adb pull /data/local/tmp/super_head.bin $head 2>&1 | Out-Null
& $adb shell 'rm -f /data/local/tmp/super_head.bin' 2>&1 | Out-Null
if (-not (Test-Path $head) -or (Get-Item $head).Length -lt 65536) { Bad '拉取 super 头部失败'; exit 1 }
}
Ok "super 头部 $((Get-Item $head).Length) B"

$xmlPath = Join-Path $ImageDir 'flash_los.xml'
$py = 'python'
& $py (Join-Path $here 'make_edl_los_xml.py') $head 8968 $xmlPath `
    ('system_a=' + $imgs.system_a) ('system_ext_a=' + $imgs.system_ext_a) ('product_a=' + $imgs.product_a)
if ($LASTEXITCODE -ne 0) { Bad '生成 XML 失败（镜像放不进分区？）'; exit 1 }

# 追加 vendor_boot 与清零项
$extra = @()
if (-not $SkipVendorBoot) {
    $vbRel = [IO.Path]::GetFileName($VendorBoot)
    $extra += "  <program SECTOR_SIZE_IN_BYTES=`"4096`" label=`"vendor_boot_a`" physical_partition_number=`"4`" start_sector=`"282982`" num_partition_sectors=`"24576`" filename=`"$vbRel`" />"
    $extra += "  <program SECTOR_SIZE_IN_BYTES=`"4096`" label=`"vendor_boot_b`" physical_partition_number=`"4`" start_sector=`"635296`" num_partition_sectors=`"24576`" filename=`"$vbRel`" />"
}
if (-not $SkipWipe) {
    $z64 = if (Test-Path (Join-Path $ImageDir 'zeros64m.img')) { Join-Path $ImageDir 'zeros64m.img' } else { Join-Path $here '..\edl\zeros64m.img' }
    $z16 = if (Test-Path (Join-Path $ImageDir 'zeros16m.img')) { Join-Path $ImageDir 'zeros16m.img' } else { Join-Path $here '..\edl\zeros16m.img' }
    if ((Test-Path $z64) -and (Test-Path $z16)) {
        $r64 = [IO.Path]::GetFileName($z64)
        $r16 = [IO.Path]::GetFileName($z16)
        $extra += "  <program SECTOR_SIZE_IN_BYTES=`"4096`" label=`"userdata_head`" physical_partition_number=`"0`" start_sector=`"4350760`" num_partition_sectors=`"16384`" filename=`"$r64`" />"
        $extra += "  <program SECTOR_SIZE_IN_BYTES=`"4096`" label=`"metadata_head`" physical_partition_number=`"0`" start_sector=`"4203304`" num_partition_sectors=`"4096`" filename=`"$r16`" />"
        Ok '已加入 userdata(64MB) / metadata(16MB) 清零项'
    } else { Bad '缺少 edl\zeros64m.img / zeros16m.img，跳过清数据（首次开机需手动 Factory reset）' }
}

if ($extra.Count -gt 0) {
    $txt = Get-Content $xmlPath -Raw
    $txt = $txt -replace '</data>', (($extra -join "`r`n") + "`r`n</data>")
    [IO.File]::WriteAllText($xmlPath, $txt, (New-Object Text.UTF8Encoding($false)))
}

Ok "XML: $xmlPath"

if ($Check) {
    Say "`n-Check 模式：只检查不写设备。XML 已生成，确认无误后去掉 -Check 再跑。" 'Yellow'
    exit 0
}

# ---------- 2. 进 EDL ----------
Step '2. 进入 EDL'
if (-not $ComPort) { Bad '需要 -ComPort COMx（设备管理器里 Qualcomm HS-USB QDLoader 9008）'; exit 1 }
Say "  如果设备还在系统里，先执行： adb reboot edl" 'DarkGray'
Say "  然后等设备管理器出现 QDLoader 9008 ($ComPort)" 'DarkGray'

# ---------- 3. Sahara + configure + write ----------
Step '3. 写入（Sahara → configure → fh_loader）'
$port = "\\.\$ComPort"
& (Join-Path $ToolDir 'QSaharaServer.exe') -p $port -s "13:$Programmer"
if ($LASTEXITCODE -ne 0) { Bad 'Sahara 失败（programmer 与本机不匹配会报 Invalid status field 41）'; exit 1 }

$cfg = '<?xml version="1.0" encoding="UTF-8" ?><data><configure MemoryName="ufs" Verbose="0" AlwaysValidate="0" MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" ZlpAwareHost="1" SkipStorageInit="0" Oem="ZTE"/></data>'
$cfgOut = & (Join-Path $ToolDir 'qcedlcmdhelper.exe') -p $ComPort -m xml -d $cfg 2>&1
if (($cfgOut -join "`n") -notmatch 'value="ACK"') { Bad "configure 未返回 ACK：`n$cfgOut"; exit 1 }
Ok 'configure ACK'

Push-Location $ImageDir
& (Join-Path $ToolDir 'fh_loader.exe') "--port=$port" --memoryname=ufs --search_path=. "--sendxml=$([IO.Path]::GetFileName($xmlPath))" --showpercentagecomplete --noprompt --skip_config
$rc = $LASTEXITCODE
& (Join-Path $ToolDir 'fh_loader.exe') "--port=$port" --memoryname=ufs --reset --noprompt --skip_config
Pop-Location
if ($rc -ne 0) { Bad '写入失败，检查 XML 的 SECTOR_SIZE_IN_BYTES 拼写与镜像大小'; exit 1 }

Say "`n完成。手机应自动开机（50–90 秒后 adb 出现）。首次开机若弹 Factory data reset 就点一下。" 'Green'
Say "验证： adb shell getprop ro.lineage.version" 'DarkGray'
