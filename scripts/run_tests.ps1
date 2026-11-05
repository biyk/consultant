$ErrorActionPreference = 'Stop'
Set-Location 'D:\ConsPlus'
$out = 'D:\ConsPlus\logs\tests_out.txt'
$err = 'D:\ConsPlus\logs\tests_err.txt'
Remove-Item $out, $err -ErrorAction SilentlyContinue

$p = Start-Process -FilePath 'D:\ConsPlus\venv\Scripts\python.exe' `
    -ArgumentList '-m','unittest','discover','-s','tests','-v' `
    -WorkingDirectory 'D:\ConsPlus' -PassThru -NoNewWindow `
    -RedirectStandardOutput $out -RedirectStandardError $err

try { $p.PriorityClass = 'BelowNormal' } catch { Write-Output 'priority: not set' }
Write-Output ("started PID=" + $p.Id + " priority=" + $p.PriorityClass)

if (-not $p.WaitForExit(150000)) {
    Write-Output 'TIMEOUT 150s -> killing test process only'
    Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
} else {
    Write-Output ("exit code = " + $p.ExitCode)
}
Write-Output '=== tail of stderr ==='
Get-Content $err -Tail 40 -ErrorAction SilentlyContinue
