# ===== 来源与致谢 / Credits =====
# ZTE 工具箱（ZTEToolBox，官方全分区备份与 EDL 整机恢复）作者：酷安 @某贼
# 本机当前 boot 链与 vendor/odm 分区来自 施（QQ 2233209163）制作的澎湃 OS 移植包；
# 本脚本不使用该包的任何文件。
# ================================
param(
    [Parameter(Mandatory = $true)][string]$BackupDir,   # ZTE 官方备份里的 images 目录（含 rawprogram0..5.xml 与全部 .img）
    [string]$ComPort = '',
    [string]$ToolDir = 'C:\Users\Administrator\Desktop\zte\bin\tool\Win',
    [string]$Programmer = '',
    [switch]$Check,
    [switch]$NoReset
)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here

function Step($msg) { Write-Host ''; Write-Host "==> $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "    [OK] $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "    [!]  $msg" -ForegroundColor Yellow }
function Die($msg)  { Write-Host "    [X]  $msg" -ForegroundColor Red; exit 1 }

Write-Host '=============================================' -ForegroundColor White
Write-Host ' 官方底包整机恢复（ZTE 工具箱备份 / EDL）' -ForegroundColor White
Write-Host '=============================================' -ForegroundColor White

# ------------------------------------------------------------------ 1. 工具
Step '检查 EDL 工具链'
$sahara   = Join-Path $ToolDir 'QSaharaServer.exe'
$helper   = Join-Path $ToolDir 'qcedlcmdhelper.exe'
$fhloader = Join-Path $ToolDir 'fh_loader.exe'
foreach ($f in @($sahara, $helper, $fhloader)) {
    if (Test-Path $f) { Ok (Split-Path -Leaf $f) } else { Die "缺少 $f（用 -ToolDir 指向 ZTE 官方工具箱的 tool\Win）" }
}
if (-not $Programmer) {
    $cands = @(
        (Join-Path $here 'firehose.elf'),
        (Join-Path $here 'prog_firehose_ddr.elf'),
        'C:\Users\Administrator\Desktop\zte\bin\res\NX789J\devprg\prog_firehose_ddr.elf'
    )
    $Programmer = ($cands | Where-Object { Test-Path $_ } | Select-Object -First 1)
}
if (-not $Programmer -or -not (Test-Path $Programmer)) { Die '缺少与设备匹配的 firehose programmer（见 tools/README.md 的说明）' }
Ok ("programmer: {0} ({1:N0} 字节)" -f (Split-Path -Leaf $Programmer), (Get-Item $Programmer).Length)

# ------------------------------------------------------------------ 2. 备份内容
Step "检查官方备份目录 $BackupDir"
if (-not (Test-Path $BackupDir)) { Die "目录不存在：$BackupDir" }
$xmls = @()
foreach ($i in 0..5) {
    $p = Join-Path $BackupDir "rawprogram$i.xml"
    if (Test-Path $p) { $xmls += "rawprogram$i.xml" } else { Warn "缺少 rawprogram$i.xml（跳过）" }
}
if ($xmls.Count -eq 0) { Die '一个 rawprogram*.xml 都没有，这不是 ZTE 官方备份的 images 目录' }
Ok ("XML: " + ($xmls -join ', '))

# 统计 XML 里引用到的镜像是否都在（跳过空 filename 的擦除项）
$missing = @()
$totalMB = 0
foreach ($x in $xmls) {
    [xml]$doc = Get-Content (Join-Path $BackupDir $x) -Raw
    foreach ($pg in $doc.data.program) {
        $fn = $pg.filename
        if (-not $fn -or $fn -eq 'DISK') { continue }
        $fp = Join-Path $BackupDir $fn
        if (-not (Test-Path $fp)) { $missing += "$x -> $fn" }
        else { $totalMB += (Get-Item $fp).Length / 1MB }
    }
}
if ($missing.Count -gt 0) {
    $missing | ForEach-Object { Write-Host "    [X] $_" -ForegroundColor Red }
    Die '备份不完整，缺上面这些镜像'
}
Ok ("镜像齐全，合计 {0:N0} MB" -f $totalMB)

if ($Check) { Write-Host ''; Write-Host ' -Check 模式：到此为止，未动设备。' -ForegroundColor Yellow; exit 0 }

# ------------------------------------------------------------------ 3. 端口
Step '定位 EDL 串口'
if (-not $ComPort) {
    $dev9 = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -match 'QDLoader 9008' } | Select-Object -First 1
    if ($dev9 -and $dev9.Name -match '(COM\d+)') { $ComPort = $Matches[1] }
}
if (-not $ComPort) { Die '没找到 QDLoader 9008：先在系统里 adb reboot edl，或关机后按住 音量+ 和 音量- 再插 USB' }
Ok "使用 $ComPort"

# ------------------------------------------------------------------ 4. Sahara + configure
Step 'Sahara 下载 firehose programmer'
& $sahara -p "\\.\$ComPort" -s "13:$Programmer" 2>&1 | Select-Object -Last 6 | ForEach-Object { Write-Host "    $_" }
if ($LASTEXITCODE -ne 0) { Die 'Sahara 失败' }
Ok 'programmer 已加载'

Step '发送 configure（完整 XML 文档）'
$cfg = '<?xml version="1.0" encoding="UTF-8" ?><data><configure MemoryName="ufs" Verbose="0" AlwaysValidate="0" MaxDigestTableSizeInBytes="8192" MaxPayloadSizeToTargetInBytes="1048576" ZlpAwareHost="1" SkipStorageInit="0" Oem="ZTE"/></data>'
$cfgOut = (& $helper -p $ComPort -m xml -d $cfg 2>&1 | Out-String)
if ($cfgOut -notmatch 'value="ACK"') { Write-Host $cfgOut; Die 'configure 没拿到 ACK' }
Ok 'configure ACK'

# ------------------------------------------------------------------ 5. 写入
Step '开始整机写入（GPT + 全部分区，约 1-2 分钟）'
$sendArg = '--sendxml=' + ($xmls -join ',')
Push-Location $BackupDir
& $fhloader --port="\\.\$ComPort" --memoryname=ufs --search_path=. $sendArg --showpercentagecomplete --noprompt --skip_config 2>&1 |
    Select-String -Pattern 'Finished|percent|ERROR|FAIL|MBps' | Select-Object -Last 12 | ForEach-Object { Write-Host "    $_" }
$rc = $LASTEXITCODE
Pop-Location
if ($rc -ne 0) { Die 'fh_loader 写入失败（看上面输出）' }
Ok '写入完成'

# ------------------------------------------------------------------ 6. 重启
if (-not $NoReset) {
    Step '重启设备'
    & $fhloader --port="\\.\$ComPort" --memoryname=ufs --reset --noprompt --skip_config 2>&1 | Select-Object -Last 3 | ForEach-Object { Write-Host "    $_" }
    Ok '已发送 reset'
}

Write-Host ''
Write-Host '注意：官方底包的 vbmeta_system 回滚索引（1772323200）可能低于设备已记录值，' -ForegroundColor Yellow
Write-Host '      若恢复后卡在 fastboot，说明被回滚保护拒绝；详见 docs/17。' -ForegroundColor Yellow
