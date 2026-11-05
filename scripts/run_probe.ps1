# Run a GUI probe module at BELOW_NORMAL priority with a hard kill-switch.
# Usage: powershell -File scripts\run_probe.ps1 -Mod server.probe_results_uia -Mode volume -TimeoutSec 300
param(
    [string]$Mod = "server.probe_results_uia",
    [string]$Mode = "",
    [string]$Query = "",
    [int]$TimeoutSec = 300
)
$ErrorActionPreference = "Stop"
Set-Location D:\ConsPlus
$py = "D:\ConsPlus\venv\Scripts\python.exe"
$outFile = "D:\ConsPlus\logs\probe_run.txt"
Remove-Item $outFile -ErrorAction SilentlyContinue
if ($Mode) { $env:PROBE_MODE = $Mode }
if ($Query) { $env:PROBE_QUERY = $Query }
$p = Start-Process -FilePath $py -ArgumentList @("-m", $Mod) `
    -RedirectStandardOutput $outFile -RedirectStandardError "D:\ConsPlus\logs\probe_err.txt" `
    -NoNewWindow -PassThru
try { $p.PriorityClass = "BelowNormal" } catch { }
Write-Output ("pid=" + $p.Id + " mod=" + $Mod + " mode=" + $Mode + " limit=" + $TimeoutSec + "s")
if (-not $p.WaitForExit($TimeoutSec * 1000)) {
    Write-Output "TIMEOUT - killing"
    try { $p.Kill() } catch { }
}
Write-Output ("exit=" + $p.ExitCode)
