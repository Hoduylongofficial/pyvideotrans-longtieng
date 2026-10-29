@echo off
rem ===========================================================
rem  LONG TIENG HANG LOAT - 1 video + 1 file .srt -> 25 ngon ngu
rem
rem  Cach dung:
rem    - Bam dup vao file nay, roi keo tha video va file .srt vao
rem    - Hoac keo thang video + file .srt tha len file .bat nay
rem
rem  Moi lan mo tu cap nhat len ban moi nhat tren GitHub (neu co).
rem  Chinh giong doc / font / kenh dich: dub_all.config.json
rem ===========================================================
setlocal
cd /d "%~dp0"
rem File keo tha luu vao bien truoc, trong khoi ( ) moi doc bang !ARGS!:
rem ten file co dau ngoac nhu "video(1).mp4" khong lam vo khoi lenh.
set "ARGS=%*"
setlocal enabledelayedexpansion
rem Toan bo lenh con lai nam trong 1 khoi ( ) de cmd doc het truoc khi chay:
rem buoc tu cap nhat co the ghi de chinh file .bat nay.
(
    title Long tieng hang loat - pyvideotrans

    where uv >nul 2>nul
    if errorlevel 1 (
        echo.
        echo  [LOI] Khong tim thay lenh "uv" trong PATH.
        echo  Hay cai uv roi mo lai file nay:
        echo    https://docs.astral.sh/uv/getting-started/installation/
        echo.
        pause
        exit /b 1
    )

    if exist "cap_nhat.py" (
        if exist ".venv\Scripts\python.exe" (
            ".venv\Scripts\python.exe" cap_nhat.py --tu-dong
        ) else (
            uv run --no-project cap_nhat.py --tu-dong
        )
    )

    if not exist "dub_all.py" (
        echo.
        echo  [LOI] Khong thay dub_all.py canh file .bat nay.
        echo  Hay de LONG_TIENG.bat trong thu muc goc cua pyvideotrans.
        echo.
        pause
        exit /b 1
    )

    set "LOI="
    uv run dub_all.py --menu !ARGS!
    if errorlevel 1 set "LOI=1"

    echo.
    echo ============================================================
    if defined LOI (
        echo   Ket thuc voi loi. Xem thong bao o tren.
        echo   Mo lai file .bat nay va chay tiep - phan da xong se duoc bo qua.
    ) else (
        echo   Da xong. Bam phim bat ky de dong cua so.
    )
    echo ============================================================
    pause >nul
    if defined LOI exit /b 1
    exit /b 0
)
