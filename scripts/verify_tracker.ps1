# Tracker sanity check after the fix pass. ASCII only.
$base = "http://127.0.0.1:8000"
$open = Invoke-RestMethod -Uri ($base + "/issues?status=open") -TimeoutSec 30
$all = Invoke-RestMethod -Uri ($base + "/issues") -TimeoutSec 30
Write-Output ("total=" + $all.total + "  open=" + $open.count + "  by_status=" + ($all.by_status | Out-String).Trim())
Write-Output "=== open queue ==="
foreach ($i in $open.issues) {
    Write-Output ("{0} | {1,-6} | {2,-9} | {3}" -f $i.id, $i.severity, $i.status, $i.title.Substring(0, [Math]::Min(80, $i.title.Length)))
}
Write-Output "=== last closed (history note present?) ==="
$fixed = Invoke-RestMethod -Uri ($base + "/issues?status=fixed") -TimeoutSec 30
$sample = $fixed.issues | Where-Object { $_.resolution_note } | Select-Object -First 2
foreach ($s in $sample) {
    Write-Output ("{0} history={1} note_len={2}" -f $s.id, $s.history.Count, $s.resolution_note.Length)
}
Write-Output ("closed with note: " + (@($fixed.issues | Where-Object { $_.resolution_note }).Count) + " of " + $fixed.count)
