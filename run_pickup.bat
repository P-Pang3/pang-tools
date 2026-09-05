@echo off
REM Trickster - PICKUP macro (items only).
REM Delegates to the shared launcher so install/dependency logic lives once.
cd /d "%~dp0"
call run_macro.bat --pickup
