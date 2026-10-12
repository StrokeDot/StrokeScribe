@echo off
cd /d "%~dp0"
echo Opening StrokeScribe with the headset drawing...
if exist .venv\Scripts\python.exe (
 .venv\Scripts\python.exe -u startup.py samples\arthur-headset-traced.svg
) else if exist ..\.venv\Scripts\python.exe (
 ..\.venv\Scripts\python.exe -u startup.py samples\arthur-headset-traced.svg
) else (
 echo Please run Setup.cmd first.
 pause
)
if errorlevel 1 pause
