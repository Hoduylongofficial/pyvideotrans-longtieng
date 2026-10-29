@echo off
rem ===========================================================
rem  MO PHAN MEM pyvideotrans (giao dien sp.py)
rem
rem  Cach dung: bam dup vao file nay (hoac loi tat tren Desktop)
rem  Moi lan mo tu cap nhat len ban moi nhat tren GitHub (neu co).
rem ===========================================================
setlocal
cd /d "%~dp0"
rem Tham so luu vao bien truoc, trong khoi ( ) moi doc bang !ARGS!
set "ARGS=%*"
setlocal enabledelayedexpansion
rem Toan bo lenh con lai nam trong 1 khoi ( ) de cmd doc het truoc khi chay:
rem buoc tu cap nhat co the ghi de chinh file .bat nay.
(
    title pyvideotrans

    if exist "cap_nhat.py" (
        if exist ".venv\Scripts\python.exe" (
            ".venv\Scripts\python.exe" cap_nhat.py --tu-dong
        ) else (
            uv run --no-project cap_nhat.py --tu-dong
        )
    )

    if not exist "sp.py" (
        echo.
        echo  [LOI] Khong thay sp.py canh file .bat nay.
        echo  Hay de MO_PHAN_MEM.bat trong thu muc goc cua pyvideotrans.
        echo.
        pause
        exit /b 1
    )

    set "LOI="
    where uv >nul 2>nul
    if errorlevel 1 (
        if exist ".venv\Scripts\python.exe" (
            ".venv\Scripts\python.exe" sp.py !ARGS!
            if errorlevel 1 set "LOI=1"
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
        uv run sp.py !ARGS!
        if errorlevel 1 set "LOI=1"
    )

    if defined LOI (
        echo.
        echo ============================================================
        echo   Phan mem dong voi loi. Xem thong bao o tren.
        echo ============================================================
        pause
        exit /b 1
    )
    exit /b 0
)
