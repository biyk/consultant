$ErrorActionPreference = 'SilentlyContinue'
Write-Output ('now = ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss') + '  (utc' + (Get-Date).ToUniversalTime().ToString(' HH:mm') + ')')
Write-Output '--- issues files by status, with mtime ---'
$rows = @()
foreach ($f in (Get-ChildItem 'D:\ConsPlus\data\issues' -Filter '*.json')) {
    $j = Get-Content -LiteralPath $f.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
    $rows += [pscustomobject]@{
        id = $j.id; status = $j.status; sev = $j.severity; ep = $j.endpoint
        created = ([DateTimeOffset]::FromUnixTimeSeconds($j.created)).ToLocalTime().ToString('MM-dd HH:mm')
        mtime = $f.LastWriteTime.ToString('MM-dd HH:mm')
    }
}
$rows | Sort-Object created | ForEach-Object {
    Write-Output ($_.created + '  upd=' + $_.mtime + '  ' + $_.status.PadRight(6) + ' ' + $_.sev.PadRight(8) + ' ' + $_.ep.PadRight(9) + ' ' + $_.id)
}
Write-Output '--- counts ---'
$rows | Group-Object status | ForEach-Object { Write-Output ($_.Name + ' = ' + $_.Count) }
$rows | Where-Object { $_.status -eq 'new' } | Group-Object ep | Sort-Object Count -Descending | ForEach-Object { Write-Output ('open by endpoint: ' + $_.Name + ' = ' + $_.Count) }
$rows | Where-Object { $_.status -eq 'new' } | Group-Object sev | ForEach-Object { Write-Output ('open by severity: ' + $_.Name + ' = ' + $_.Count) }
