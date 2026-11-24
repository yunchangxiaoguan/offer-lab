@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto find_python
".venv\Scripts\python.exe" -c "import docx, fitz" >nul 2>nul
if not errorlevel 1 goto launch_venv

:find_python
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 goto use_python
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>nul
if not errorlevel 1 goto use_py
echo 这台电脑需要先安装 Python 3.10 或更新版本。安装时请选择 Add Python to PATH。
pause
exit /b 1

:use_python
set "launcher=python"
goto check_packages
:use_py
set "launcher=py -3"

:check_packages
%launcher% -c "import docx, fitz" >nul 2>nul
if not errorlevel 1 goto launch_current
echo 首次使用需要下载 Word 和 PDF 导出组件，并安装到程序目录的 .venv 文件夹。
choice /c YN /m "现在安装吗？选 Y 安装，选 N 退出"
if errorlevel 2 exit /b 1
%launcher% -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed

:launch_venv
".venv\Scripts\python.exe" -X utf8 app.py --open %*
goto finish
:launch_current
%launcher% -X utf8 app.py --open %*

:finish
if not errorlevel 1 exit /b 0
:failed
echo 启动未完成，请查看上方提示。
pause
exit /b 1
