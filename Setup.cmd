@echo off
cd /d "%~dp0"
py -3 -m venv .venv
if errorlevel 1 goto missing
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Setup complete. Double-click Launch.cmd.
pause
exit /b 0
:missing
echo Install Python 3.12 or newer, including the Python launcher, then run Setup.cmd again.
:failed
echo Setup did not complete. Review the message above.
pause
exit /b 1
