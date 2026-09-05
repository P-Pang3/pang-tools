@echo off
REM Trickster - HUNT macro (skills, monsters, potions).
REM Delegates to the shared launcher so install/dependency logic lives once.
cd /d "%~dp0"
call run_macro.bat --hunt
