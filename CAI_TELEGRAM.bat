@echo off
rem ===========================================================
rem  CAI GUI BAO CAO / LOG LOI LONG TIENG VE NHOM TELEGRAM
rem
rem  Cach dung: bam dup file nay, dan token bot + ID nhom
rem  (lay tu nguoi quan tri). Chi can lam 1 lan tren moi may.
rem ===========================================================
setlocal
cd /d "%~dp0"
title Cai bao cao Telegram - pyvideotrans

where uv >nul 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" bao_cao_telegram.py
    ) else (
        echo.
        echo  [LOI] Khong tim thay lenh "uv" va thu muc .venv.
        echo.
        pause
        exit /b 1
    )
) else (
    uv run bao_cao_telegram.py
)

echo.
echo   Bam phim bat ky de dong cua so.
pause >nul
endlocal
exit /b
