$ErrorActionPreference = 'Stop'
$rows = Get-ChildItem -LiteralPath 'D:\ConsPlus\data\issues' -Filter *.json | Sort-Object Name
$out = New-Object System.Collections.Generic.List[string]
foreach ($r in $rows) {
  $j = [System.IO.File]::ReadAllText($r.FullName, [System.Text.Encoding]::UTF8) | ConvertFrom-Json
  if ($j.status -eq 'fixed') { continue }
  $out.Add('========================================================')
  $out.Add(('ID {0} | {1} | sev={2} | ep={3}' -f $j.id, $j.status, $j.severity, $j.endpoint))
  $out.Add(('TITLE: ' + $j.title))
  $out.Add(('DESC : ' + $j.description))
  $out.Add(('STEPS: ' + $j.steps))
  $out.Add(('EXPECT: ' + $j.expected))
  $out.Add(('ACTUAL: ' + $j.actual))
}
[System.IO.File]::WriteAllLines('D:\ConsPlus\logs\open_issues.txt', $out, (New-Object System.Text.UTF8Encoding($true)))
Write-Output ('DUMPED=' + $out.Count)
