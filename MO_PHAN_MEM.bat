@echo off
rem ===========================================================
rem  MO PHAN MEM pyvideotrans (giao dien sp.py)
rem
rem  Cach dung: bam dup vao file nay (hoac loi tat tren Desktop)
rem ===========================================================
setlocal
cd /d "%~dp0"
title pyvideotrans

if not exist "sp.py" (
    echo.
    echo  [LOI] Khong thay sp.py canh file .bat nay.
    echo  Hay de MO_PHAN_MEM.bat trong thu muc goc cua pyvideotrans.
    echo.
    pause
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" sp.py %*
    ) else (
        echo.
        echo  [LOI] Khong tim thay lenh "uv" va thu muc .venv.
        echo  Hay cai uv roi mo lai file nay:
        echo    https://docs.astral.sh/uv/getting-started/installation/
        echo.
        pause
        exit /b 1
    )
) else (
    uv run sp.py %*
)
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Phan mem dong voi loi ^(ma loi: %RC%^). Xem thong bao o tren.
    echo ============================================================
    pause
)
endlocal
exit /b %RC%
