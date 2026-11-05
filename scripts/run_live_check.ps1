# Gentle runner for the live GUI validation. ASCII only, low priority, hard kill.
$p = Start-Process -FilePath "D:\ConsPlus\venv\Scripts\python.exe" `
    -ArgumentList "D:\ConsPlus\scripts\live_check.py" -PassThru -WindowStyle Hidden
$p.PriorityClass = "BelowNormal"
Write-Output ("started PID=" + $p.Id + " priority=" + $p.PriorityClass)
if (-not $p.WaitForExit(420000)) {
    Write-Output "TIMEOUT 420s - killing"
    $p.Kill()
}
Write-Output ("exit code = " + $p.ExitCode)
Write-Output "=== tail of logs\live_check.txt ==="
Get-Content "D:\ConsPlus\logs\live_check.txt" -Encoding UTF8 -Tail 40
