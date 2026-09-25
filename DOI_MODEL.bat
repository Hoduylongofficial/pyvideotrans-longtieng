@echo off
rem ===========================================================
rem  DOI KENH DICH / MODEL / API KEY
rem
rem  Cach dung: bam dup vao file nay roi chon so trong menu.
rem   - Doi qua lai: OpenRouter tra phi (deepseek) / model free / Gemini
rem   - Them nhieu API key (tu xoay vong khi 1 key bi gioi han)
rem   - Kiem tra key, dich thu 1 file .srt
rem ===========================================================
setlocal
cd /d "%~dp0"
title Doi kenh dich / model / API key - pyvideotrans

if not exist "doi_model.py" (
    echo.
    echo  [LOI] Khong thay doi_model.py canh file .bat nay.
    echo  Hay de DOI_MODEL.bat trong thu muc goc cua pyvideotrans.
    echo.
    pause
    exit /b 1
)

where uv >nul 2>nul
if errorlevel 1 (
    if exist ".venv\Scripts\python.exe" (
        ".venv\Scripts\python.exe" doi_model.py %*
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
    uv run doi_model.py %*
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
