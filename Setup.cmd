@echo off
cd /d "%~dp0"
echo StrokeScribe prototype setup (Python 3.12 - 3.14 supported).
py -3 --version
if errorlevel 1 goto missing
py -3 -m venv .venv
if errorlevel 1 goto missing
echo Updating the package installer...
.venv\Scripts\python.exe -m pip install --upgrade pip
if errorlevel 1 goto failed
echo Installing prebuilt packages (no C/C++ compiler required)...
.venv\Scripts\python.exe -m pip install --only-binary=:all: -r requirements.txt
if errorlevel 1 goto failed
echo.
echo Setup complete. Double-click Launch.cmd or Launch-headset.cmd.
pause
exit /b 0
:missing
echo Install 64-bit Python 3.12, 3.13 or 3.14 with the Python launcher, then run Setup.cmd again.
pause
exit /b 1
:failed
echo.
echo Setup did not complete. A package may not have a compatible prebuilt Windows wheel.
echo This version supports Windows 64-bit Python 3.12, 3.13 and 3.14.
echo Please keep this window and send a screenshot of the error.
pause
exit /b 1
