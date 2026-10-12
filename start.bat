@echo off
chcp 65001 >nul
setlocal
:: 优先使用项目虚拟环境，其次回退到系统 python
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" run.py
) else (
    python run.py
)
endlocal