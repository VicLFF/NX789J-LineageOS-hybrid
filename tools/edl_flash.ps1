# ===== 来源与致谢 / Credits =====
# ZTE 工具箱（ZTEToolBox，官方全分区备份与 EDL 整机恢复）作者：酷安 @某贼
# 本机当前 boot 链与 vendor/odm 分区来自 施（QQ 2233209163）制作的澎湃 OS 移植包；
# 本脚本不使用该包的任何文件。
# ================================
param(
    [string]$ComPort = '',                       # 例如 COM6，留空则自动探测 QDLoader 9008
    [string]$Images  = '',                       # 默认 <本脚本目录>\edl\raw
    [string]$ToolDir = 'C:\Users\Administrator\Desktop\zte\bin\tool\Win',  # ZTE 官方工具箱的 tool\Win（含 QSaharaServer / qcedlcmdhelper / fh_loader）
    [string]$Programmer = '',                    # 与设备匹配的 firehose programmer；留空则自动找
    [int]$SuperStartSector = 8968,               # super 在 UFS LUN0 的起始 4096B 扇区
    [switch]$Check,                              # 只做检查与 XML 生成，不刷
    [switch]$NoReset
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

function Step($msg) { Write-Host ''; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "    [X]  $msg" -ForegroundColor Red; exit 1 }

if (-not $Images) { $Images = Join-Path $here 'edl\raw' }

Write-Host '=============================================' -ForegroundColor White
Write-Host ' LineageOS / NX789J  EDL 定点刷写 (firehose)' -ForegroundColor White
Write-Host '=============================================' -ForegroundColor White

# ---------------------------------------------------------------- 1. 工具
Step '检查 EDL 工具链'
$sahara   = Join-Path $ToolDir 'QSaharaServer.exe'
$helper   = Join-Path $ToolDir 'qcedlcmdhelper.exe'
$fhloader = Join-Path $ToolDir 'fh_loader.exe'
foreach ($f in @($sahara, $helper, $fhloader)) {
    if (Test-Path $f) { Ok (Split-Path -Leaf $f) } else { Die "缺少 $f（用 -ToolDir 指向 ZTE 官方工具箱的 tool\Win）" }
}

# firehose programmer 必须与设备 SoC 匹配（高通签名，不含任何 ROM 内容）。
# 注意机型不能随便套：实测把 NX809J 的 prog_firehose_ddr.elf 用在 NX789J 上，
# Sahara 报 "is_ack_successful:1387 Invalid status field 41"。
if (-not $Programmer) {
    $cands = @(
        (Join-Path $here 'firehose.elf'),
        (Join-Path $here 'prog_firehose_ddr.elf'),
        'C:\Users\Administrator\Desktop\zte\bin\res\NX789J\devprg\prog_firehose_ddr.elf',
        'C:\Users\Administrator\Desktop\zte\bin\res\NX789J\devprg\prog_firehose.elf'
    )
    $Programmer = ($cands | Where-Object { Test-Path $_ } | Select-Object -First 1)
}
if (-not $Programmer -or -not (Test-Path $Programmer)) {
    Write-Host ''
    Write-Host '    缺少 firehose programmer（prog_firehose_ddr.elf / firehose.elf）' -ForegroundColor Red
    Write-Host '    它是高通的引导程序，不是任何人的 ROM；但必须与本机 SoC 匹配。' -ForegroundColor Yellow
    Write-Host '    获取方式：用 ZTE 官方工具箱对 NX789J 跑一次官方下载/救砖，工具会把' -ForegroundColor Yellow
    Write-Host '    配套 devprg 下载到 zte\bin\res\NX789J\devprg\ ；把它复制到本脚本同目录' -ForegroundColor Yellow
    Write-Host '    并命名 firehose.elf，或用 -Programmer 指定路径。' -ForegroundColor Yellow
    exit 1
}
Ok ("programmer: {0} ({1:N0} 字节)" -f (Split-Path -Leaf $Programmer), (Get-Item $Programmer).Length)

# ---------------------------------------------------------------- 2. 镜像
Step "检查镜像目录 $Images"
$need = @{ 'system' = 'system_a'; 'system_ext' = 'system_ext_a'; 'product' = 'product_a' }
$raw = @{}
foreach ($n in $need.Keys) {
    $img = Join-Path $Images "$n.img"
    $simg = Join-Path $Images "$n.simg"
    if (-not (Test-Path $img) -and (Test-Path $simg)) {
        Warn "$n.img 不存在，从 $n.simg 转换"
        & python (Join-Path $here 'sparse2raw.py') $simg $img | Out-Null
    }
    if (-not (Test-Path $img)) { Die "缺少镜像 $img" }
    $len = (Get-Item $img).Length
    if ($len -lt 100MB) { Die "$n.img 只有 $([math]::Round($len/1MB,1))MB，不像完整镜像" }
    Ok ("{0,-12} {1,10:N0} 字节" -f "$n.img", $len)
    $raw[$need[$n]] = $img
}

# ---------------------------------------------------------------- 3. LP 元数据
Step '读取设备 super 的 LP 分区表'
$head = Join-Path $here 'device_super_head.bin'
$adb  = (Get-Command adb -ErrorAction SilentlyContinue).Source
if (-not $adb) { $adb = 'C:\platform-tools\adb.exe' }
$gotFresh = $false
if (Test-Path $adb) {
    $dev = (& $adb devices 2>&1 | Out-String)
    if ($dev -match '\tdevice') {
        & $adb root 2>&1 | Out-Null
        Start-Sleep -Seconds 3
        & $adb shell 'dd if=/dev/block/by-name/super of=/data/local/tmp/superhead.bin bs=4096 count=128' 2>&1 | Out-Null
        & $adb pull /data/local/tmp/superhead.bin $head 2>&1 | Out-Null
        if ((Test-Path $head) -and (Get-Item $head).Length -ge 262144) {
            Ok "已从设备现拉 LP 表（$((Get-Item $head).Length) 字节）"
            $gotFresh = $true
        }
    }
}
if (-not $gotFresh) {
    if (Test-Path $head) { Warn "用本地缓存的 LP 表（可能已过期；分区被 resize 过就不准了）" }
    else { Die '没有 LP 表：要么手机连着 adb，要么先手动拉一份 device_super_head.bin' }
}

# ---------------------------------------------------------------- 4. 生成 XML
Step '生成 firehose XML（只写 system_a / system_ext_a / product_a）'
$xml = Join-Path $here 'edl\los_now.xml'
$args = @('make_edl_los_xml.py', $head, "$SuperStartSector", $xml)
foreach ($k in $raw.Keys) { $args += "$k=$($raw[$k])" }
$out = & python $args 2>&1
$out | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Die '生成 XML 失败（多半是镜像比分区容量大，需要先 resize 或编更小的 system）' }
Ok "XML: $xml"
if ($Check) { Write-Host ''; Write-Host ' -Check 模式：到此为止，未动设备。' -ForegroundColor Yellow; exit 0 }

# ---------------------------------------------------------------- 5. 端口
Step '定位 EDL 串口'
if (-not $ComPort) {
    $dev9 = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match 'QDLoader 9008' } | Select-Object -First 1
    if ($dev9 -and $dev9.Name -match '(COM\d+)') { $ComPort = $Matches[1] }
}
if (-not $ComPort) { Die '没找到 QDLoader 9008：先在系统里 adb reboot edl，或关机后按住 音量+ 和 音量- 再插 USB' }
Ok "使用 $ComPort"

# ---------------------------------------------------------------- 6. Sahara + configure
Step 'Sahara 下载 firehose programmer'
& $sahara -p "\\.\$ComPort" -s "13:$Programmer" 2>&1 | Select-Object -Last 6 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Die 'Sahara 失败（端口被占用？线没插好？programmer 机型不匹配？请重新进 EDL）' }
Ok 'programmer 已加载'

Step '发送 configure（必须是完整 XML 文档，否则 fh_loader 会报 Tool doesn''t come from ZTE）'
$cfg = '<?xml version="1.0" encoding="UTF-8" ?><data><configure MemoryName="ufs" Verbose="0" AlwaysValidate="0" MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" ZlpAwareHost="1" SkipStorageInit="0" Oem="ZTE"/></data>'
$cfgOut = (& $helper -p $ComPort -m xml -d $cfg 2>&1 | Out-String)
if ($cfgOut -notmatch 'value="ACK"') {
    Write-Host $cfgOut
    Die 'configure 没拿到 ACK（XML 必须是完整文档，不能只发裸 <configure/>）'
}
Ok 'configure ACK'

# ---------------------------------------------------------------- 7. 写入
Step '开始写入三个逻辑分区'
$rel = 'edl\los_now.xml'
& $fhloader --port="\\.\$ComPort" --memoryname=ufs --search_path=$here --sendxml=$rel --showpercentagecomplete --noprompt --skip_config 2>&1 |
    Select-String -Pattern 'Finished|percent|ERROR|FAIL|MBps' | Select-Object -Last 12 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Die 'fh_loader 写入失败（看上面输出）' }
Ok '写入完成'

# ---------------------------------------------------------------- 8. 重启
if (-not $NoReset) {
    Step '重启设备'
    & $fhloader --port="\\.\$ComPort" --memoryname=ufs --reset --noprompt --skip_config 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }
    Ok '已发送 reset（若表现为彻底断电，长按电源键开机即可）'
}

Write-Host ''
Write-Host '完成。首次开机较慢（要重建 dalvik），约 50-90 秒后 adb 才会出现，可用 sys.boot_completed 确认。' -ForegroundColor White
