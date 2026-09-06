@echo off
setlocal enabledelayedexpansion

echo =====================================================================
echo        DOMINUS INVESTOR - REDEPLOY BACKEND (LOCAL DOCKER)
echo =====================================================================
echo.
echo [*] Thao tac nay se build lai Backend va GIU NGUYEN Database PostgreSQL.
echo.

cd /d "%~dp0"

REM 1. Kiem tra Docker Desktop
docker info >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo [LOI] Docker Desktop chua duoc bat hoac chua khoi dong xong!
    echo Vui long mo Docker Desktop va thu lai.
    echo.
    pause
    exit /b 1
)

REM 2. Dung va rebuild container backend (giu nguyen volume database)
echo [*] Dang build lai Backend va khoi dong container...
docker compose up -d --build

echo.
echo [*] Dang doi Backend khoi dong (5 giay)...
timeout /t 5 /nobreak >nul

REM 3. Kiem tra trang thai endpoint /health
echo [*] Kiem tra trang thai ket noi:
curl.exe -s -m 5 http://localhost:8082/health
if %ERRORLEVEL% EQU 0 (
    echo.
    echo.
    echo =====================================================================
    echo [THANH CONG] Backend Dominus Investor da duoc Redeploy thanh cong!
    echo =====================================================================
    echo - Backend Local  : http://localhost:8082
    echo - Health Check   : http://localhost:8082/health
    echo - Database Local : localhost:5432 (dominus_investor)
    echo =====================================================================
) else (
    echo.
    echo.
    echo [CANH BAO] Backend dang khoi dong hoac chua san sang.
    echo Ban co the kiem tra log chi tiet bang lenh:
    echo    docker compose logs -f backend
    echo =====================================================================
)

echo.
pause
