@echo off
rem ===========================================================
rem  CAP NHAT bo long tieng len ban moi nhat tren GitHub
rem
rem  Cach dung: dong MO_PHAN_MEM / LONG_TIENG, roi bam dup file nay.
rem  Lan dau se hoi token GitHub (xin quan ly), cac lan sau tu chay.
rem  API key, cau hinh rieng cua may nay duoc giu nguyen.
rem ===========================================================
rem Toan bo lenh nam trong 1 khoi ( ) de cmd doc het truoc khi chay:
rem file .bat nay co the bi chinh ban cap nhat ghi de trong luc dang chay.
(
    setlocal
    cd /d "%~dp0"
    title Cap nhat - pyvideotrans

    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" cap_nhat.py
    ) else (
        uv run --no-project cap_nhat.py
    )
    if errorlevel 1 (
        echo.
        echo   Cap nhat THAT BAI. Xem thong bao o tren.
    )
    echo.
    echo   Bam phim bat ky de dong cua so.
    pause >nul
    endlocal
    exit /b
)
