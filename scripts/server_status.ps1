$ErrorActionPreference = 'SilentlyContinue'
# Quick check: is the Resurrector supervisor alive, is the server listening, what does /health say.
Write-Output '=== ConsPlus server status ==='
$sup = @(Get-CimInstance Win32_Process -Filter "Name='resurrector.exe'")
if ($sup.Count -eq 0) { Write-Output 'Resurrector: NOT RUNNING (start: Start-ScheduledTask -TaskName ConsPlus_Resurrector)' } else {
    $sup | ForEach-Object { Write-Output ("Resurrector : PID=" + $_.ProcessId + "  since " + $_.CreationDate) }
}
$mon = @(Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'run_server\.bat' })
$mon | ForEach-Object { Write-Output ("monitor bat : PID=" + $_.ProcessId + " PPID=" + $_.ParentProcessId + " " + $_.Name) }
foreach ($c in @(Get-NetTCPConnection -LocalPort 8000 -State Listen)) {
    $o = Get-CimInstance Win32_Process -Filter ("ProcessId=" + $c.OwningProcess)
    Write-Output ("listener 8000 : PID=" + $o.ProcessId + "  " + $o.Name)
}
$t = Get-ScheduledTaskInfo -TaskName 'ConsPlus_Resurrector'
Write-Output ("task          : " + $t.State + "  last run " + $t.LastRunTime + "  last result " + $t.LastTaskResult)
Write-Output '--- GET /health ---'
try { (Invoke-RestMethod -Uri 'http://127.0.0.1:8000/health' -TimeoutSec 20) | ConvertTo-Json -Depth 4 -Compress | Write-Output }
catch { Write-Output ('health error: ' + $_.Exception.Message) }
Write-Output '--- Resurrector log (last 10) ---'
Get-Content -LiteralPath 'D:\ConsPlus\logs\resurrector.log' -Tail 10 | Write-Output
