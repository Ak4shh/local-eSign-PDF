@echo off
setlocal
echo === PDF eSign ^| PyInstaller build ===

echo Cleaning previous build artifacts...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo Building executable...
pyinstaller pdf_esign.spec --noconfirm

if %ERRORLEVEL% neq 0 (
    echo.
    echo BUILD FAILED -- check output above
    exit /b 1
)

echo.
echo === BUILD COMPLETE ===
echo Output: dist\PDF-eSign.exe
for %%F in (dist\PDF-eSign.exe) do echo Size:   %%~zF bytes
