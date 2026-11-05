@ECHO OFF
CHCP 65001 >nul
CD /d "D:\ConsPlus"
SET CONSULTANT_HOST=0.0.0.0
SET CONSULTANT_PORT=8000
SET CONSULTANT_GUI_TIMEOUT=120
REM ---------------------------------------------------------------------------
REM THIS FILE MUST STAY ASCII-ONLY (and CRLF). Under "CHCP 65001" cmd.exe tracks
REM batch position in BYTES, so multi-byte (Cyrillic) lines make the offset slip
REM and following commands get silently skipped or chopped mid-line. That is how
REM a SET line below stopped being executed. Keep comments in English ASCII.
REM ---------------------------------------------------------------------------
REM Index cut date of the restored base. 2026-07-03 comes from the freshness
REM stamp "as of 03.07.2026" read in the client itself, i.e. it is a lower
REM bound: the base also holds acts (red. 26.06.2026) with changes
REM effective 07.07.2026. If you delete this line the server accumulates the
REM date instead from "red. ot / s izm. ot" stamps of documents it actually
REM reads (logs/index_observed.json) and reports index_as_of_source honestly.
SET CONSULTANT_INDEX_AS_OF=2026-07-03
ECHO Starting ConsPlus server on http://%CONSULTANT_HOST%:%CONSULTANT_PORT%/
REM Flask stdout/stderr goes to a file: Resurrector starts us with
REM hide_window=true, nobody drains the pipe, and an unread pipe would
REM eventually block the server. Restarts on crash are done by Resurrector
REM (see scripts\install_resurrector.ps1).
CALL D:\ConsPlus\venv\Scripts\python.exe -m server.app >> "D:\ConsPlus\logs\server_http.log" 2>&1
