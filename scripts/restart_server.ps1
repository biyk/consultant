$ErrorActionPreference = 'SilentlyContinue'

Write-Output "=== before: server.app processes ==="
$old = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
       Where-Object { $_.CommandLine -match 'server\.app' })
$old | ForEach-Object { "PID={0} {1}" -f $_.ProcessId, $_.CommandLine }

# cmd shell from run_server.bat may predate the bat edit -> stale env block.
Write-Output "=== kill stale run_server.bat cmd shells FIRST, then python ==="
Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run_server.bat*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "killed cmd " + $_.ProcessId }

Write-Output "=== kill server.app pythons (Resurrector restarts) ==="
$old | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "killed " + $_.ProcessId }

$ok = $false
for ($i = 1; $i -le 30; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 4
        if ($r.ok) { $ok = $true; Write-Output ("up after " + ($i * 2) + "s"); $r | ConvertTo-Json -Compress; break }
    } catch { Start-Sleep -Seconds 1 }
}
if (-not $ok) { Write-Output "SERVER NOT UP within 60s" }

Write-Output "=== after: process tree ==="
Get-CimInstance Win32_Process | Where-Object {
    ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'server\.app') -or
    ($_.Name -eq 'cmd.exe' -and $_.CommandLine -like '*run_server.bat*') } |
    ForEach-Object { "PID={0} parent={1} start={2} cmd={3}" -f $_.ProcessId, $_.ParentProcessId, $_.CreationDate, $_.CommandLine }

Write-Output "=== final health (expect index_as_of from env) ==="
try { (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 6) | ConvertTo-Json -Compress } catch { "err: " + $_.Exception.Message }
