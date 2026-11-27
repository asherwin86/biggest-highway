# Installs dist\BiggestHighway.apk on a running emulator (or a phone with USB debugging),
# starts it, then saves its log and a screenshot to shots\android.log / shots\android.png.
#
#   powershell -ExecutionPolicy Bypass -File android\test_on_emulator.ps1 [-Seconds 40] [-Fresh]
#
# adb must be on PATH (it is in the Android SDK's platform-tools folder).
param([int]$Seconds = 40, [switch]$Fresh, [switch]$NoInstall)
$ErrorActionPreference = 'Continue'
$root = Split-Path -Parent $PSScriptRoot
$pkg = 'io.github.asherwin86.biggesthighway'
if (-not (Get-Command adb -ErrorAction SilentlyContinue)) { throw 'adb was not found on PATH' }

if (-not $NoInstall) {
    adb install -r (Join-Path $root 'dist\BiggestHighway.apk')
    if ($LASTEXITCODE) { throw 'adb install failed' }
}
adb shell am force-stop $pkg
if ($Fresh) { adb shell pm clear $pkg | Out-Null }
adb logcat -c
adb shell monkey -p $pkg -c android.intent.category.LAUNCHER 1 | Out-Null
Start-Sleep $Seconds
$log = Join-Path $root 'shots\android.log'
adb logcat -d -v time 'Panda3D:V' 'python.stdout:V' 'python.stderr:V' 'threaded_app:W' 'AndroidRuntime:E' `
    'linker:W' 'DEBUG:V' 'libc:F' 'ActivityManager:W' '*:S' | Out-File -Encoding utf8 $log
adb shell screencap -p /sdcard/bh_shot.png
adb pull /sdcard/bh_shot.png (Join-Path $root 'shots\android.png') | Out-Null    # (piping PNG bytes through PowerShell would corrupt them)
$pid2 = (adb shell pidof $pkg) -join ''
Write-Host ("App process: " + $(if ($pid2) { "running (pid $pid2)" } else { 'NOT running' }))
Write-Host "Log: $log"
Get-Content $log -Tail 40
