$ErrorActionPreference = 'Stop'
$rows = Get-ChildItem -LiteralPath 'D:\ConsPlus\data\issues' -Filter *.json | Sort-Object Name
$fixed = @(); $open = @()
foreach ($r in $rows) {
  $j = [System.IO.File]::ReadAllText($r.FullName, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  $line = '{0} | id={1} | {2} | {3} | {4} | {5}' -f $r.BaseName, $j.id, $j.status, $j.severity, $j.endpoint, $j.title
  if ($j.status -eq 'fixed') { $fixed += $line } else { $open += $line }
}
$out = @("FIXED ($($fixed.Count):)") + $fixed + @("", "NEW ($($open.Count):)") + $open
[System.IO.File]::WriteAllLines('D:\ConsPlus\logs\issues_now.txt', $out, (New-Object System.Text.UTF8Encoding($true)))
Write-Output ('TOTAL={0} FIXED={1} OPEN={2}' -f $rows.Count, $fixed.Count, $open.Count)
