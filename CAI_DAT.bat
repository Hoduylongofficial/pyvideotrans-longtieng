@echo off
rem ===========================================================
rem  TRANG CAI DAT LONG TIENG (mo trong trinh duyet)
rem
rem  Cach dung: bam dup file nay, trinh duyet tu mo trang cai dat:
rem  kenh dich, chuoi model, API key, giong doc, Telegram, render.
rem  Dong cua so den nay khi cai xong.
rem ===========================================================
setlocal
cd /d "%~dp0"
title Cai dat long tieng - pyvideotrans

where uv >/dev/null 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" cai_dat.py
    ) else (
        echo.
        echo  [LOI] Khong tim thay lenh "uv" va thu muc .venv.
        echo.
        pause
        exit /b 1
    )
) else (
    uv run cai_dat.py
)

echo.
echo   Bam phim bat ky de dong cua so.
pause >nul
endlocal
exit /b
