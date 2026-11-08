@echo off
rem ===========================================================
rem  CAI DAT bo long tieng tren may moi - bam dup 1 lan la xong
rem
rem  Tu lam het:
rem    1. Cai uv (trinh quan ly Python)
rem    2. Cai ffmpeg ban day du (co libass cho phu de A Rap / An Do)
rem    3. Cai thu vien Python (uv sync) - lan dau 10-20 phut, vai GB
rem    4. Tao file cau hinh, loi tat LONG_TIENG / MO_PHAN_MEM tren Desktop
rem    5. Hoi nhap key kenh dich + giong doc (co the bo qua, lam sau)
rem
rem  Can mang Internet. Khong can quyen Administrator.
rem  Chay lai bao nhieu lan cung duoc: buoc nao xong roi thi bo qua.
rem ===========================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"
title Cai dat bo long tieng - pyvideotrans
set "GOC=%~dp0"
if "%GOC:~-1%"=="\" set "GOC=%GOC:~0,-1%"

echo.
echo ============================================================
echo   CAI DAT BO LONG TIENG 25 NGON NGU
echo   Thu muc: %GOC%
echo ============================================================

rem --- Bam dup ngay trong file zip: Windows chi giai nen moi file .bat ra thu muc tam
if not exist "pyproject.toml" goto chua_giai_nen
if not exist "dub_all.py" goto chua_giai_nen

rem ===========================================================
echo.
echo [1/5] uv
rem ===========================================================
set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if not errorlevel 1 goto uv_ok
echo   Chua co uv, dang cai...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol = 'Tls12'; irm https://astral.sh/uv/install.ps1 | iex"
where uv >nul 2>nul
if errorlevel 1 (
    echo.
    echo   [LOI] Cai uv khong thanh cong. Kiem tra mang roi bam dup lai file nay.
    echo   Hoac tu cai theo huong dan: https://docs.astral.sh/uv/getting-started/installation/
    goto loi
)
:uv_ok
for /f "delims=" %%v in ('uv --version') do echo   OK - %%v

rem ===========================================================
echo.
echo [2/5] ffmpeg
rem ===========================================================
rem Cac cho ffmpeg co the nam: thu muc ffmpeg cua bo nay, winget, PATH san co
set "PATH=%GOC%\ffmpeg;%LOCALAPPDATA%\Microsoft\WinGet\Links;%PATH%"
call :kiem_tra_ffmpeg
if "!FF_OK!"=="1" goto ffmpeg_ok

where winget >nul 2>nul
if errorlevel 1 goto ffmpeg_tai_zip
echo   Dang cai ffmpeg bang winget ^(Gyan.FFmpeg, khoang 200 MB^)...
winget install --id Gyan.FFmpeg -e --silent --accept-source-agreements --accept-package-agreements
call :kiem_tra_ffmpeg
if "!FF_OK!"=="1" goto ffmpeg_ok

:ffmpeg_tai_zip
echo   Tai ffmpeg ban day du vao thu muc ffmpeg cua bo nay...
set "FF_TMP=%TEMP%\cai_dat_ffmpeg_%RANDOM%"
mkdir "%FF_TMP%" >nul 2>nul
curl.exe -L --fail --retry 3 -o "%FF_TMP%\ffmpeg.zip" "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
if errorlevel 1 (
    echo   [LOI] Khong tai duoc ffmpeg. Kiem tra mang roi bam dup lai file nay.
    rmdir /s /q "%FF_TMP%" >nul 2>nul
    goto loi
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%FF_TMP%\ffmpeg.zip' -DestinationPath '%FF_TMP%\x' -Force; Get-ChildItem '%FF_TMP%\x' -Recurse -Filter *.exe | Where-Object { $_.Directory.Name -eq 'bin' } | Copy-Item -Destination '%GOC%\ffmpeg' -Force"
rmdir /s /q "%FF_TMP%" >nul 2>nul
rem Them thu muc ffmpeg cua bo nay vao PATH cua tai khoan (cho ca cac cua so mo sau)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$d = '%GOC%\ffmpeg'; $p = [Environment]::GetEnvironmentVariable('Path', 'User'); if (-not $p) { $p = '' }; if (($p -split ';') -notcontains $d) { [Environment]::SetEnvironmentVariable('Path', ($d + ';' + $p).TrimEnd(';'), 'User') }"
call :kiem_tra_ffmpeg
if "!FF_OK!"=="1" goto ffmpeg_ok
echo   [LOI] Van chua co ffmpeg day du ^(can --enable-libass^).
echo   Tu cai: mo PowerShell, go: winget install Gyan.FFmpeg
goto loi
:ffmpeg_ok
echo   OK - !FF_VER!

rem ===========================================================
echo.
echo [3/5] Thu vien Python ^(uv sync^)
rem ===========================================================
echo   Lan dau mat khoang 10-20 phut va tai vai GB. Dung tat cua so nay.
echo.
uv sync
if errorlevel 1 (
    echo.
    echo   uv sync loi, thu lai lan nua...
    uv sync
    if errorlevel 1 (
        echo.
        echo   [LOI] Cai thu vien khong thanh cong. Kiem tra mang roi bam dup lai file nay.
        goto loi
    )
)
echo   OK - thu vien da cai xong.

rem ===========================================================
echo.
echo [4/5] File cau hinh + loi tat tren Desktop
rem ===========================================================
rem Lan dau nap cau hinh se tao videotrans\params.json, DOI_MODEL / DOI_TTS can file nay
if not exist "videotrans\params.json" (
    ".venv\Scripts\python.exe" -c "from videotrans.configure import config"
)
if not exist "videotrans\params.json" (
    echo   [LOI] Khong tao duoc videotrans\params.json.
    goto loi
)
echo   OK - videotrans\params.json

if not defined CAI_DAT_DESKTOP (
    for /f "delims=" %%d in ('powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"') do set "CAI_DAT_DESKTOP=%%d"
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s = New-Object -ComObject WScript.Shell; foreach ($x in @(@('Long tieng 25 ngon ngu', 'LONG_TIENG.bat'), @('Mo phan mem pyvideotrans', 'MO_PHAN_MEM.bat'))) { $l = $s.CreateShortcut((Join-Path '!CAI_DAT_DESKTOP!' ($x[0] + '.lnk'))); $l.TargetPath = Join-Path '%GOC%' $x[1]; $l.WorkingDirectory = '%GOC%'; $l.Save() }"
if errorlevel 1 (
    echo   [!] Khong tao duoc loi tat - van dung binh thuong bang cach bam dup LONG_TIENG.bat trong thu muc nay.
) else (
    echo   OK - Desktop co "Long tieng 25 ngon ngu" va "Mo phan mem pyvideotrans"
)

rem ===========================================================
echo.
echo [5/5] Key kenh dich + giong doc
rem ===========================================================
echo   Can URL + key do quan ly gui rieng ^(qua Zalo^).
echo   Chua co thi go K, sau nay bam DOI_MODEL.bat va DOI_TTS.bat de nhap.
echo.
set "TRA_LOI="
set /p "TRA_LOI=  Nhap key kenh dich ngay bay gio? (C/K): "
if /i "!TRA_LOI!"=="c" (
    echo.
    echo   Mo DOI_MODEL: chon so 10 ^(9Router^) neu quan ly gui URL 9Router.
    call "!GOC!\DOI_MODEL.bat"
)
set "TRA_LOI="
set /p "TRA_LOI=  Nhap key giong doc (GPU Modal / GPU may nha) ngay bay gio? (C/K): "
if /i "!TRA_LOI!"=="c" (
    call "!GOC!\DOI_TTS.bat"
)

echo.
echo ============================================================
echo   CAI DAT XONG.
echo.
echo   Long tieng: bam dup "Long tieng 25 ngon ngu" tren Desktop
echo               ^(hoac LONG_TIENG.bat trong thu muc nay^).
echo   Moi lan mo se tu cap nhat ban moi nhat - khong can lam gi them.
echo ============================================================
echo.
echo   Bam phim bat ky de dong cua so.
pause >nul
endlocal
exit /b 0

rem ===========================================================
:kiem_tra_ffmpeg
rem FF_OK=1 khi ffmpeg chay duoc va co libass (phu de cung A Rap / An Do can no)
set "FF_OK=0"
set "FF_VER="
where ffmpeg >nul 2>nul
if errorlevel 1 exit /b 0
for /f "tokens=1-3" %%a in ('ffmpeg -hide_banner -version 2^>nul ^| findstr /b /c:"ffmpeg version"') do set "FF_VER=%%a %%b %%c"
ffmpeg -hide_banner -version 2>nul | findstr /c:"--enable-libass" >nul
if errorlevel 1 (
    echo   ffmpeg dang co thieu libass, can cai ban day du.
    exit /b 0
)
set "FF_OK=1"
exit /b 0

:chua_giai_nen
echo.
echo   [LOI] Chua giai nen file zip.
echo   Bam chuot phai vao file zip ^> Extract All / Giai nen tat ca,
echo   giai nen ra o D:\ ^(vi du D:\pyvideotrans-longtieng^),
echo   roi bam dup CAI_DAT.bat trong thu muc vua giai nen.
goto loi

:loi
echo.
echo ============================================================
echo   CAI DAT CHUA XONG. Xem dong [LOI] o tren.
echo   Sua xong thi bam dup lai CAI_DAT.bat - phan da xong se duoc bo qua.
echo ============================================================
echo.
echo   Bam phim bat ky de dong cua so.
pause >nul
endlocal
exit /b 1
