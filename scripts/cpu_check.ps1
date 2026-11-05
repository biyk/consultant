# Read-only CPU sampler: two snapshots, delta of TotalProcessorTime per process.
$ErrorActionPreference = 'Stop'

function Snap {
    Get-Process | ForEach-Object {
        try { [pscustomobject]@{ Id = $_.Id; Name = $_.ProcessName; T = $_.TotalProcessorTime.TotalMilliseconds } } catch {}
    }
}

$s1 = Snap
Start-Sleep -Seconds 3
$s2 = Snap

$map1 = @{}
foreach ($p in $s1) { $map1[$p.Id] = $p.T }

$rows = foreach ($p in $s2) {
    if ($map1.ContainsKey($p.Id)) {
        $d = $p.T - $map1[$p.Id]
        if ($d -ge 50) {
            [pscustomobject]@{ Id = $p.Id; Name = $p.Name; PctCPU = [math]::Round($d / 30, 1) }
        }
    }
}

Write-Output ("LogicalProcs=" + (Get-CimInstance -ClassName Win32_ComputerSystem).NumberOfLogicalProcessors)
Write-Output "=== top instantaneous CPU (percent of one core) ==="
$rows | Sort-Object -Descending PctCPU | Select-Object -First 15 | Format-Table -AutoSize | Out-String -Width 200

Write-Output "=== python / consultant / resurrector / office processes present now ==="
Get-Process python, pythonw, winword, wordpad, Write, Consultant, Consult, resurrector -ErrorAction SilentlyContinue |
    Select-Object Id, ProcessName, @{n='CPU_s';e={[math]::Round($_.CPU,1)}}, @{n='Mem_MB';e={[math]::Round($_.WorkingSet64/1MB,0)}}, StartTime |
    Format-Table -AutoSize | Out-String -Width 200
