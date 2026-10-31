@echo off
echo ============================================
echo  Study Buddy — Build Script
echo ============================================

:: Install deps
pip install -r requirements.txt

:: Generate extension icon
python create_icon.py

:: PyInstaller — one-file exe, no console window, with tray support
pyinstaller ^
  --onefile ^
  --windowed ^
  --name "StudyBuddy" ^
  --icon "extension\icon.png" ^
  --add-data "extension;extension" ^
  study_buddy.py

echo.
echo Build complete!  dist\StudyBuddy.exe is your app.
echo.
echo Next steps:
echo   1. Run dist\StudyBuddy.exe
echo   2. Load the 'extension' folder in Chrome/Edge (Developer mode)
echo   3. Set your ANTHROPIC_API_KEY when prompted (saved locally)
echo.
pause
