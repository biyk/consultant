@ECHO OFF
CHCP 65001 >nul
CD /d "D:\ConsPlus"
SET CONSULTANT_HOST=0.0.0.0
SET CONSULTANT_PORT=8000
SET CONSULTANT_GUI_TIMEOUT=120
ECHO Запуск сервера КонсультантПлюс на http://%CONSULTANT_HOST%:%CONSULTANT_PORT%/
D:\ConsPlus\venv\Scripts\python.exe -m server.app
