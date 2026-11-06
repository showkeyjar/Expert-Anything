@echo off
REM Build the ExpertAnything one-click installer (onedir).
REM Prereqs:  pip install -r requirements.txt pyinstaller
python -m PyInstaller expert_anything.spec --clean --noconfirm
echo.
echo Build complete. Runnable at: dist\ExpertAnything\ExpertAnything.exe
pause
