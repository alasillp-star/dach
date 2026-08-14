@echo off
setlocal
title Arabic Winning Products Scanner Setup
echo Starting Arabic Winning Products Scanner installer...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "irm 'https://raw.githubusercontent.com/alasillp-star/dach/main/install_windows_scanner.ps1' ^| iex"
echo.
echo If the installer opened an Administrator window, continue there.
pause
