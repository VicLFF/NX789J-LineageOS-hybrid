$ErrorActionPreference = 'Continue'
$adb = 'C:\platform-tools\adb.exe'
$out = 'C:\Users\Administrator\Documents\deepseek-harness\default-workspace\porting'
function Say($m, $c='Cyan') { Write-Host $m -ForegroundColor $c }
function Act { (& $adb shell 'dumpsys activity activities 2>/dev/null | grep -m1 topResumedActivity') }

Say '=== 1/6 唤醒屏幕 ==='
& $adb shell 'input keyevent 224' | Out-Null
Start-Sleep -Milliseconds 900

Say '=== 2/6 确保 PIN 是 1234 ==='
$v = (& $adb shell 'locksettings verify --old 1234' 2>&1) -join ' '
if ($v -notmatch 'success') { & $adb shell 'locksettings set-pin 1234' | Out-Null }
Say "    Pin 就绪"

Say '=== 3/6 打开指纹录入 ==='
& $adb shell 'am force-stop com.android.settings' | Out-Null
Start-Sleep -Milliseconds 800
& $adb shell 'am start -a android.settings.FINGERPRINT_ENROLL' | Out-Null
Start-Sleep -Seconds 4

Say '=== 4/6 自动导航到「轻触并按住指纹传感器」 ==='
$reached = $false
for ($i = 0; $i -lt 12; $i++) {
  $a = Act
  if ($a -match 'FingerprintEnrollEnrolling') { $reached = $true; break }
  if ($a -match 'ConfirmLockPassword') {
    & $adb shell 'input tap 400 700' | Out-Null
    Start-Sleep -Milliseconds 500
    & $adb shell 'input text 1234' | Out-Null
    Start-Sleep -Milliseconds 500
    & $adb shell 'input keyevent 66' | Out-Null
    Start-Sleep -Seconds 2
    continue
  }
  & $adb shell 'uiautomator dump /data/local/tmp/u.xml >/dev/null 2>&1' | Out-Null
  & $adb pull /data/local/tmp/u.xml "$out\_nav.xml" 2>&1 | Out-Null
  $t = Get-Content "$out\_nav.xml" -Raw -ErrorAction SilentlyContinue
  $done = $false
  foreach ($w in @('我同意','开始','下一步','确定','继续','更多')) {
    if (-not $t) { break }
    $n = ($t -split '<node ' | Where-Object { $_ -match ('text="' + $w + '"') } | Select-Object -First 1)
    if ($n -and $n -match 'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"') {
      $cx = [int]((([int]$matches[1]) + ([int]$matches[3])) / 2)
      $cy = [int]((([int]$matches[2]) + ([int]$matches[4])) / 2)
      Say "    点 [$w] @ ($cx,$cy)"
      & $adb shell "input tap $cx $cy" | Out-Null
      $done = $true
      break
    }
  }
  if (-not $done) {
    Say '    盲点主按钮'
    & $adb shell 'input tap 1054 2493' | Out-Null
  }
  Start-Sleep -Seconds 2
}
if (-not $reached) { Say '!!! 没能自动进入录入页，请在手机上手动进到「轻触并按住指纹传感器」' 'Yellow' }

Say '=== 5/6 重启触摸协处理器服务（对齐帧计数）==='
& $adb root | Out-Null
Start-Sleep -Seconds 2
& $adb shell 'pkill -f "vendor/bin/odm_tsc"' | Out-Null
Start-Sleep -Seconds 3
& $adb shell 'cat /proc/touchscreen/tp_report_rate 2>/dev/null; echo 4 > /proc/touchscreen/tp_report_rate 2>/dev/null; cat /proc/touchscreen/tp_report_rate' | Out-Null
Say '=== 5/6 初始化屏下指纹服务 ==='
& $adb logcat -c | Out-Null
& $adb shell 'am start -n com.nx.fpb/.Main --ei msg 6 --ei info 0 --ei color -16777216' | Out-Null
Start-Sleep -Seconds 1

Write-Host ''
Write-Host '###############################################################' -ForegroundColor Green
Write-Host '#                                                             #' -ForegroundColor Green
Write-Host '#   现 在 开 始 按 ！                                        #' -ForegroundColor Green
Write-Host '#                                                             #' -ForegroundColor Green
Write-Host '#   把手指按进屏幕下方那个圈里：                              #' -ForegroundColor Green
Write-Host '#   按住 1 秒 -> 抬起 -> 再按，连续按 20 次左右。            #' -ForegroundColor Green
Write-Host '#   下方会显示进度，录满会自动完成。                          #' -ForegroundColor Green
Write-Host '#                                                             #' -ForegroundColor Green
Write-Host '###############################################################' -ForegroundColor Green
[Console]::Beep(1400,250); Start-Sleep -Milliseconds 200; [Console]::Beep(1800,400)
Write-Host ''

$job = Start-Job -ScriptBlock { param($a,$o) & $a logcat -b all -v time > "$o\fp_manual.log" 2>&1 } -ArgumentList $adb,$out
Start-Sleep -Seconds 75
Stop-Job $job -ErrorAction SilentlyContinue
Remove-Job $job -Force -ErrorAction SilentlyContinue

Say '=== 6/6 结果 ==='
$l = Get-Content "$out\fp_manual.log" -ErrorAction SilentlyContinue
$map = [ordered]@{
  '帧校验错误 uwFrameIndex'   = 'uwFrameIndex'
  'enroll 会话建立'           = 'enrollWithContext'
  'HAL 收到手指按下'           = 'onEnrollFingerDown'
  'HAL 开始取图'              = 'gf_fpcore'
  '高亮圈亮起'                = 'setHighLightWindowVisible'
  'HAL 报错 notifyErrorInfo'  = 'notifyErrorInfo'
  '错误码3(超时)'             = 'FINGERPRINT_ERROR'
  '指纹库变化通知'            = 'Count of enroll'
}
foreach ($k in $map.Keys) { Write-Host ("  {0,-24} {1}" -f $k, (($l | Select-String -SimpleMatch $map[$k]).Count)) }
Write-Host ''
& $adb shell 'dumpsys fingerprint | head -3'
Write-Host ''
Say "日志: $out\fp_manual.log"
Say '把上面这张表截图或念给我。按任意键关闭...' 'Yellow'
$null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')