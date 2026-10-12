@echo off
cd /d "%~dp0"
if exist .venv\Scripts\python.exe (
 .venv\Scripts\python.exe -u startup.py
) else if exist ..\.venv\Scripts\python.exe (
 ..\.venv\Scripts\python.exe -u startup.py
) else (
 echo Please run Setup.cmd first.
 pause
)
if errorlevel 1 pause
