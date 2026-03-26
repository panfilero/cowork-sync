@echo off
echo Building CoworkSync...
pyinstaller --onefile --windowed --name CoworkSync ^
  --icon coworksync/assets/icon_green.ico ^
  --add-data "coworksync/assets;assets" ^
  --add-data "coworksync/templates;coworksync/templates" ^
  --add-data "coworksync/static;coworksync/static" ^
  coworksync/main.py
echo.
echo Done. Output: dist\CoworkSync.exe
pause
