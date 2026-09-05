@echo off
REM Trickster macro launcher (ASCII-only).
REM Called by run_pickup.bat / run_hunt.bat with a mode argument.
REM No argument = pickup mode.
REM Uses "if errorlevel N" syntax to avoid %errorlevel% parse-time expansion
REM inside parenthesized blocks.

setlocal
cd /d "%~dp0"

set "MODE=%~1"
if "%MODE%"=="" set "MODE=--pickup"

REM -----------------------------------------------------------
REM UAC self-elevation: re-launch as administrator if needed
REM -----------------------------------------------------------
REM NOTE: the mode argument MUST be passed through. Without -ArgumentList
REM the elevated instance starts with no argument and falls back to pickup,
REM so run_hunt.bat and run_autoclick.bat would both open the pickup app.
net session >nul 2>&1
if not errorlevel 1 goto :have_admin
if "%ELEVATED%"=="1" goto :have_admin
echo Requesting administrator privileges...
echo (Cancel is fine - it will start without them.)
set "ELEVATED=1"
powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%MODE%' -Verb RunAs" >nul 2>&1
if not errorlevel 1 exit /b 0
echo Continuing without administrator privileges.

:have_admin

set "WHAT=Item Pickup"
if "%MODE%"=="--hunt" set "WHAT=Hunting"
if "%MODE%"=="--autoclick" set "WHAT=Auto Clicker"
echo ============================================================
echo  Starting: %WHAT%
echo ============================================================
echo.

REM -----------------------------------------------------------
REM [1/3] Python detection
REM -----------------------------------------------------------
echo [1/3] Checking Python...

python --version >nul 2>&1
if errorlevel 1 goto :no_python

REM Reject the Windows Store "app execution alias" stub.
for /f "delims=" %%p in ('where python 2^>nul') do (
    echo %%p | findstr /i "WindowsApps" >nul && goto :store_stub
    goto :python_ok
)

:python_ok
REM Auto-install succeeded previously -- clean up the flag file
del "%TEMP%\macro_pyinstall.tmp" >nul 2>&1
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo   OK: %%v

REM -----------------------------------------------------------
REM [2/3] Dependency check / install
REM -----------------------------------------------------------
echo.
echo [2/3] Checking dependencies...

python -c "import pynput, pygetwindow, cv2, mss, numpy, PIL" >nul 2>&1
if errorlevel 1 goto :install_deps
echo   All dependencies already installed.
goto :run

:install_deps
echo   Some dependencies missing - installing now...
echo.
python -m pip install --upgrade pip
if errorlevel 1 goto :pip_fail

python -m pip install -r requirements.txt
if errorlevel 1 goto :pip_fail

echo.
echo   Install complete.

REM Re-verify after install
python -c "import pynput, pygetwindow, cv2, mss, numpy, PIL" >nul 2>&1
if errorlevel 1 goto :import_fail

REM -----------------------------------------------------------
REM [3/3] Launch GUI
REM -----------------------------------------------------------
:run
echo.
echo [3/3] Starting GUI...
echo ============================================================
echo   (This console will close automatically.
echo    Closing the GUI window stops the macro.)
echo.

REM Launch via pythonw.exe (no console) and detach.
REM If pythonw is missing (rare), fall back to python.
where pythonw >nul 2>&1
if errorlevel 1 goto :fallback_python
if "%MODE%"=="--autoclick" goto :run_autoclick
start "" pythonw main.py %MODE%
goto :end

:run_autoclick
start "" pythonw autoclick.py
goto :end

:fallback_python
if "%MODE%"=="--autoclick" goto :run_autoclick_py
start "" python main.py %MODE%
goto :end

:run_autoclick_py
start "" python autoclick.py
goto :end


REM -----------------------------------------------------------
REM Error handlers
REM -----------------------------------------------------------

REM --- Python not found: attempt silent auto-install -----------
:no_python
REM If we already tried once and Python is still missing, give up.
if exist "%TEMP%\macro_pyinstall.tmp" goto :no_python_manual

echo.
echo   Python not found. Attempting automatic installation...
echo   (requires internet access -- approx. 25 MB download)
echo.

REM curl is built into Windows 10 1803+ and Windows 11.
curl --version >nul 2>&1
if errorlevel 1 goto :no_python_manual

echo   Downloading Python 3.12.9 installer...
curl -L --progress-bar -o "%TEMP%\python_setup.exe" "https://www.python.org/ftp/python/3.12.9/python-3.12.9-amd64.exe"
if errorlevel 1 goto :dl_fail

echo.
echo   Installing Python (user install, no admin needed)...
"%TEMP%\python_setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=0
if errorlevel 1 goto :install_fail

del "%TEMP%\python_setup.exe" >nul 2>&1

REM Write flag so a second restart won't loop if PATH still broken.
echo 1 > "%TEMP%\macro_pyinstall.tmp"

echo.
echo   Python installed. Restarting launcher with updated PATH...
echo.
start "" "%~f0"
exit /b 0

:no_python_manual
echo.
echo   [ERROR] Python not found and auto-install could not complete.
echo   Install Python 3.10+ manually: https://www.python.org/downloads/
echo   IMPORTANT: check "Add python.exe to PATH" during install.
echo.
pause
exit /b 1

:dl_fail
echo.
echo   [ERROR] Failed to download Python installer.
echo   Check your internet connection, or install manually:
echo   https://www.python.org/downloads/
echo.
pause
exit /b 1

:install_fail
echo.
echo   [ERROR] Python installer exited with an error.
echo   Try: right-click this .bat -^> Run as administrator
echo   Or install manually: https://www.python.org/downloads/
echo.
pause
exit /b 1

REM --- Store stub -------------------------------------------------
:store_stub
echo.
echo   [ERROR] Detected Microsoft Store Python stub, not a real Python.
echo.
echo   Windows has a placeholder 'python.exe' that just opens the Store.
echo   Steps to fix:
echo     1. Settings -^> Apps -^> Advanced app settings -^> App execution aliases
echo     2. Turn OFF "python.exe" and "python3.exe"
echo     3. Install real Python from https://www.python.org/downloads/
echo        (check "Add python.exe to PATH" during install)
echo     4. Open a NEW cmd and run this .bat again.
echo.
pause
exit /b 1

:pip_fail
echo.
echo   [ERROR] Failed to install dependencies via pip.
echo   Possible causes:
echo     - No network connection
echo     - Proxy / firewall blocking pypi.org
echo     - Permission denied (try: right-click .bat -^> Run as administrator)
echo.
pause
exit /b 1

:import_fail
echo.
echo   [ERROR] Installation finished but some packages still not importable.
echo   Try: python -m pip install --upgrade --force-reinstall -r requirements.txt
echo.
pause
exit /b 1

:run_fail
echo.
echo   [ERROR] main.py exited with an error. See the traceback above.
echo.
pause
exit /b 1

:end
endlocal
