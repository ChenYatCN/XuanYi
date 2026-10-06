@echo off
chcp 65001 >nul
set "XUANYI_PROJECT=%~dp0"
cd /d "%XUANYI_PROJECT%"
if exist "dist\XuanYi.exe" (
    start "" "dist\XuanYi.exe"
    exit /b
)
set "XUANYI_PYTHON=%XUANYI_PROJECT%.venv\Scripts\python.exe"
if not exist "%XUANYI_PYTHON%" set "XUANYI_PYTHON=%XUANYI_PROJECT%..\XuanShu\.venv\Scripts\python.exe"
if not exist "%XUANYI_PYTHON%" (
    echo 未找到 Python 环境，请按 README 安装依赖，或先打包。
    pause
    exit /b 1
)
powershell -NoProfile -Command "Start-Process -FilePath $env:XUANYI_PYTHON -ArgumentList ('-X utf8 ' + [char]34 + $env:XUANYI_PROJECT + 'XuanYi.py' + [char]34) -WorkingDirectory $env:XUANYI_PROJECT -Verb RunAs -WindowStyle Hidden"
