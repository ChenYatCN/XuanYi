@echo off
chcp 65001 >nul
set "XUANYI_PROJECT=%~dp0"
cd /d "%XUANYI_PROJECT%"
set "XUANYI_PYTHON=%XUANYI_PROJECT%.venv\Scripts\python.exe"
if not exist "%XUANYI_PYTHON%" set "XUANYI_PYTHON=%XUANYI_PROJECT%..\XuanShu\.venv\Scripts\python.exe"
if not exist "%XUANYI_PYTHON%" (
    echo 未找到 Python 环境。请按 README 创建 .venv 并安装 requirements.txt。
    pause
    exit /b 1
)
set "PYTHONNOUSERSITE=1"
set "PYTHONUSERBASE=%XUANYI_PROJECT%build\python-userbase"
set "PYTHONPATH="
set "PYTHONHOME="
set "QT_PLUGIN_PATH="
set "QML2_IMPORT_PATH="
set "QML_IMPORT_PATH="
set "PATH=%SystemRoot%\System32;%SystemRoot%;%SystemRoot%\System32\Wbem;%SystemRoot%\System32\WindowsPowerShell\v1.0"
"%XUANYI_PYTHON%" -X utf8 -m unittest discover -s tests
if errorlevel 1 goto failed
"%XUANYI_PYTHON%" -X utf8 -m PyInstaller XuanYi.spec --noconfirm
if errorlevel 1 goto failed
"%XUANYI_PYTHON%" -X utf8 verify_bundle.py dist\XuanYi.exe
if errorlevel 1 goto failed
echo 完成：%XUANYI_PROJECT%dist\XuanYi.exe
pause
exit /b 0
:failed
echo 检查或打包失败；不清理原 XuanShu 项目及旧成品。
pause
exit /b 1
