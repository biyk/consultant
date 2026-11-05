# Non-GUI smoke: manifest, tracker filters, error contracts. ASCII only, READ-ONLY
# (negative PATCH checks reuse an existing issue, so nothing is created or mutated).
$base = "http://127.0.0.1:8000"

$m = Invoke-RestMethod -Uri ($base + "/") -TimeoutSec 20
Write-Output ("manifest: endpoints=" + $m.endpoints.Count + " categories=" + $m.categories.Count)
Write-Output ("empty_reason vocabulary: " + ($m.notes.empty_reason -join ", "))
Write-Output ("index_as_of: " + $m.notes.index_as_of + " source: " + $m.notes.index_as_of_source)

$o = Invoke-RestMethod -Uri ($base + "/issues?status=open") -TimeoutSec 20
Write-Output ("open=" + $o.count + " open_total=" + $o.open_total + " total=" + $o.total +
              " by_status=" + ($o.by_status | ConvertTo-Json -Compress))
foreach ($i in $o.issues) { Write-Output ("  open: " + $i.id + " [" + $i.severity + "] " + $i.endpoint) }

foreach ($q in @("nope", "fixed", "closed", "new")) {
    try {
        $r = Invoke-RestMethod -Uri ($base + "/issues?status=" + $q) -TimeoutSec 20
        Write-Output ("status=" + $q + " -> count=" + $r.count)
    } catch {
        Write-Output ("status=" + $q + " -> HTTP " + $_.Exception.Response.StatusCode.value__)
    }
}

try {
    Invoke-RestMethod -Uri ($base + "/issues") -Method Patch -Body (@{ id = "x"; status = "fixed" } | ConvertTo-Json) `
        -ContentType "application/json" -TimeoutSec 20 | Out-Null
    Write-Output "PATCH /issues (no id) -> accepted (BAD)"
} catch {
    Write-Output ("PATCH /issues (no id) -> HTTP " + $_.Exception.Response.StatusCode.value__)
}

$any = (Invoke-RestMethod -Uri ($base + "/issues?limit=1") -TimeoutSec 20).issues[0].id
try {
    Invoke-RestMethod -Uri ($base + "/issues/" + $any) -Method Patch -Body (@{ zzz = 1 } | ConvertTo-Json) `
        -ContentType "application/json" -TimeoutSec 20 | Out-Null
    Write-Output ("unknown field on " + $any + " -> accepted (BAD)")
} catch {
    Write-Output ("unknown field on " + $any + " -> HTTP " + $_.Exception.Response.StatusCode.value__)
}
$after = Invoke-RestMethod -Uri ($base + "/issues/" + $any) -TimeoutSec 20
Write-Output ("issue " + $any + " unchanged: status=" + $after.status + " note_len=" +
              ("" + $after.resolution_note).Length)
