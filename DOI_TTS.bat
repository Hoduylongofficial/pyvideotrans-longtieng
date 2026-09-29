@echo off
rem ===========================================================
rem  DOI GIONG DOC (TTS)
rem
rem  Cach dung: bam dup vao file nay roi chon so trong menu.
rem   - Edge-TTS: giong Microsoft online, mien phi
rem   - OmniVoice: chay tren GPU thue Modal, nhai giong (nhap URL + key)
rem   - Chon giong mau, doc thu + uoc tinh thoi gian / chi phi
rem ===========================================================
setlocal
cd /d "%~dp0"
title Doi giong doc (TTS) - pyvideotrans

if not exist "doi_tts.py" (
    echo.
    echo  [LOI] Khong thay doi_tts.py canh file .bat nay.
    echo  Hay de DOI_TTS.bat trong thu muc goc cua pyvideotrans.
    echo.
    pause
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" doi_tts.py %*
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
    uv run doi_tts.py %*
)
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   Ket thuc voi loi ^(ma loi: %RC%^). Xem thong bao o tren.
    echo ============================================================
    pause
)
endlocal
exit /b %RC%
