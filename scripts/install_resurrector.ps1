param(
    [string]$ResDir = 'D:\resurrector-v1.1.4-windows-amd64',
    [string]$ProjectDir = 'D:\ConsPlus',
    [string]$EntryName = 'ConsPlus Server',
    [string]$TaskName = 'ConsPlus_Resurrector',
    [switch]$Unregister,
    [switch]$NoStart
)
# Wire the ConsPlus HTTP server into Resurrector (restarter) and make it start
# automatically:
#   1) add/replace the monitored entry ["ConsPlus Server"] in
#      %USERPROFILE%\.config\resurrector\config.toml (atomic write, Resurrector
#      watches the file with fsnotify and requires atomic renames);
#   2) register the scheduled task "$TaskName": starts resurrector.exe in the
#      interactive desktop session at every logon, restart-on-failure enabled,
#      no execution time limit, runs with highest privileges (UI Automation
#      needs to be able to drive the ConsultantPlus client window);
#   3) remove HKCU\...\Run\Resurrector so Resurrector is not launched twice
#      (its single-instance mutex would pop an error dialog at logon);
#   4) run the task right now and check http://127.0.0.1:8000/health.
# Interactive session on purpose: the server drives the ConsultantPlus desktop
# client, so a Session-0 Windows service (nssm/sc) would have no desktop.

$ErrorActionPreference = 'Stop'
$exe = Join-Path $ResDir 'resurrector.exe'
if (-not (Test-Path -LiteralPath $exe)) { throw "not found: $exe" }
$bat = Join-Path $ProjectDir 'run_server.bat'
if (-not (Test-Path -LiteralPath $bat)) { throw "not found: $bat" }

$cfgDir = Join-Path $env:USERPROFILE '.config\resurrector'
$cfg = Join-Path $cfgDir 'config.toml'
$rlog = Join-Path $ProjectDir 'logs\resurrector.log'
$runKey = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
$whoami = "$env:USERDOMAIN\$env:USERNAME"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Remove-ItemProperty -Path $runKey -Name 'Resurrector' -ErrorAction SilentlyContinue
    Stop-Process -Name 'resurrector' -Force -ErrorAction SilentlyContinue
    Write-Output "removed task $TaskName and HKCU Run value; entry '$EntryName' is still in $cfg"
    exit 0
}

# --- 1. monitored entry in config.toml --------------------------------------
New-Item -ItemType Directory -Path $cfgDir -Force | Out-Null
New-Item -ItemType Directory -Path (Split-Path $rlog) -Force | Out-Null

$toml = @"
["$EntryName"]
command = 'cmd.exe'
args = ['/c', '$bat']
cwd = '$ProjectDir'
hide_window = true
restart_delay_sec = 5
max_retries = -1
healthy_timeout_sec = 120
"@

$old = ''
if (Test-Path -LiteralPath $cfg) { $old = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 }
# drop an entry with the same name if it exists, then append the fresh one
$old = [regex]::Replace($old, '(?ms)^\["' + [regex]::Escape($EntryName) + '"\].*?(?=^\[|\z)', '')
if (Test-Path -LiteralPath $cfg) { Copy-Item -LiteralPath $cfg -Destination "$cfg.bak" -Force }
$newText = $old.TrimEnd() + "`r`n`r`n" + $toml.Trim() + "`r`n"
[System.IO.File]::WriteAllText("$cfg.tmp", $newText, (New-Object System.Text.UTF8Encoding($false)))
Move-Item -LiteralPath "$cfg.tmp" -Destination $cfg -Force
Write-Output "1) config entry written into $cfg (backup $cfg.bak)"

# --- 2. scheduled task: autostart at logon + restarter at supervisor level ---
$action = New-ScheduledTaskAction -Execute $exe `
    -Argument ('-log-file "' + $rlog + '"') -WorkingDirectory $ResDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $whoami
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $whoami -LogonType Interactive -RunLevel Highest
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Force -Description ("Resurrector supervisor for the ConsPlus HTTP server (" + $bat + ")") | Out-Null
Write-Output "2) task registered: $TaskName (at logon of $whoami, highest privileges, no time limit)"

# --- 3. no double autostart via the Run key ----------------------------------
Remove-ItemProperty -Path $runKey -Name 'Resurrector' -ErrorAction SilentlyContinue
Write-Output '3) HKCU\...\Run\Resurrector cleared (the task is the single autostart)'

# --- 4. start it now ---------------------------------------------------------
if ($NoStart) { exit 0 }
Stop-Process -Name 'resurrector' -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2
Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 10

$sup = @(Get-Process -Name 'resurrector' -ErrorAction SilentlyContinue)
Write-Output ("4) resurrector PIDs: " + (($sup | ForEach-Object { $_.Id }) -join ','))
$listen = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($listen) { Write-Output ("   port 8000 owned by PID " + ($listen.OwningProcess -join ',')) }
try {
    $h = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 20
    Write-Output ('   /health -> ' + ($h | ConvertTo-Json -Depth 4 -Compress))
} catch {
    Write-Output ('   /health FAILED: ' + $_.Exception.Message)
    if (Test-Path -LiteralPath $rlog) { Get-Content -LiteralPath $rlog -Tail 15 | ForEach-Object { Write-Output ('   log: ' + $_) } }
}
