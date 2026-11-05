$ErrorActionPreference = 'Stop'

function Normalize-Bat($path) {
    $bytes = [System.IO.File]::ReadAllBytes($path)
    $non = @($bytes | Where-Object { $_ -gt 127 })
    $lf = @($bytes | Where-Object { $_ -eq 10 }).Count
    $crlf = 0
    for ($i = 1; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 10 -and $bytes[$i-1] -eq 13) { $crlf++ } }
    $txt = [System.Text.Encoding]::UTF8.GetString($bytes)
    $txt = $txt -replace "`r`n", "`n" -replace "`n", "`r`n"
    [System.IO.File]::WriteAllBytes($path, [System.Text.Encoding]::ASCII.GetBytes($txt))
    "{0}: nonAscii_before={1} LF={2} CRLF={3} -> rewritten CRLF-only ASCII" -f (Split-Path $path -Leaf), $non.Count, $lf, $crlf
}

foreach ($f in @('D:\ConsPlus\run_server.bat')) {
    if (Test-Path $f) { Normalize-Bat $f }
}

function Count-Crlf($bytes) {
    $n = 0
    for ($i = 1; $i -lt $bytes.Length; $i++) { if ($bytes[$i] -eq 10 -and $bytes[$i-1] -eq 13) { $n++ } }
    return $n
}

# report only: _CRUN_utf8.bat may legitimately need its UTF-8 bytes
foreach ($f in @('D:\ConsPlus\_CRUN_utf8.bat')) {
    if (Test-Path $f) {
        $bb = [System.IO.File]::ReadAllBytes($f)
        $na = @($bb | Where-Object { $_ -gt 127 }).Count
        $nlf = @($bb | Where-Object { $_ -eq 10 }).Count
        $ncr = Count-Crlf $bb
        "CHECK-ONLY {0}: nonAscii={1} LF={2} CRLF={3}" -f (Split-Path $f -Leaf), $na, $nlf, $ncr
    }
}

Write-Output "=== verify run_server.bat parses and sets the var (python CALL replaced by ECHO) ==="
$text = [System.IO.File]::ReadAllText('D:\ConsPlus\run_server.bat')
$text = $text -replace '(?m)^CALL .*server\.app.*$', 'ECHO PROBE_INDEX_AS_OF=[%CONSULTANT_INDEX_AS_OF%] PROBE_TIMEOUT=[%CONSULTANT_GUI_TIMEOUT%]'
$tmp = 'D:\ConsPlus\logs\_probe_final.bat'
[System.IO.File]::WriteAllBytes($tmp, [System.Text.Encoding]::ASCII.GetBytes($text))
cmd /c $tmp

Write-Output "=== bytes left of run_server.bat (all <=127?) ==="
$b = [System.IO.File]::ReadAllBytes('D:\ConsPlus\run_server.bat')
"nonAscii={0} size={1}" -f (@($b | Where-Object { $_ -gt 127 }).Count), $b.Length
