@echo off
rem ===========================================================
rem  LONG TIENG HANG LOAT - 1 video + 1 file .srt -> 25 ngon ngu
rem
rem  Cach dung:
rem    - Bam dup vao file nay, roi keo tha video va file .srt vao
rem    - Hoac keo thang video + file .srt tha len file .bat nay
rem
rem  Chinh giong doc / font / kenh dich: dub_all.config.json
rem ===========================================================
setlocal
cd /d "%~dp0"
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

if not exist "dub_all.py" (
    echo.
    echo  [LOI] Khong thay dub_all.py canh file .bat nay.
    echo  Hay de LONG_TIENG.bat trong thu muc goc cua pyvideotrans.
    echo.
    pause
    exit /b 1
)

uv run dub_all.py --menu %*
set "RC=%ERRORLEVEL%"

echo.
echo ============================================================
if "%RC%"=="0" (
    echo   Da xong. Bam phim bat ky de dong cua so.
) else (
    echo   Ket thuc voi loi ^(ma loi: %RC%^).
    echo   Mo lai file .bat nay va chay tiep - phan da xong se duoc bo qua.
)
echo ============================================================
pause >nul
endlocal
exit /b %RC%
