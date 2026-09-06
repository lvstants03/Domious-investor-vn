# Script Redeploy Backend Dominus Investor tren PowerShell
$ErrorActionPreference = "Stop"

Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host "       DOMINUS INVESTOR - REDEPLOY BACKEND (LOCAL DOCKER)            " -ForegroundColor Cyan
Write-Host "=====================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "[*] Thao tac nay se build lai Backend va GIU NGUYEN Database PostgreSQL." -ForegroundColor Yellow
Write-Host ""

Set-Location $PSScriptRoot

# 1. Kiem tra Docker Desktop
try {
    docker info | Out-Null
} catch {
    Write-Host "[LOI] Docker Desktop chua duoc bat hoac chua khoi dong xong!" -ForegroundColor Red
    Write-Host "Vui long mo Docker Desktop va thu lai."
    exit 1
}

# 2. Rebuild backend container va giu nguyen volume
Write-Host "[*] Dang build lai Backend va khoi dong container..." -ForegroundColor Green
docker compose up -d --build

Write-Host ""
Write-Host "[*] Dang doi Backend khoi dong (5 giay)..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

# 3. Kiem tra endpoint /health
Write-Host "[*] Kiem tra trang thai ket noi:" -ForegroundColor Green
try {
    $res = curl.exe -s -m 5 http://localhost:8082/health
    Write-Host $res -ForegroundColor White
    Write-Host ""
    Write-Host "=====================================================================" -ForegroundColor Green
    Write-Host "[THANH CONG] Backend Dominus Investor da duoc Redeploy thanh cong!" -ForegroundColor Green
    Write-Host "=====================================================================" -ForegroundColor Green
    Write-Host "- Backend Local  : http://localhost:8082"
    Write-Host "- Health Check   : http://localhost:8082/health"
    Write-Host "- Database Local : localhost:5432 (dominus_investor)"
    Write-Host "====================================================================="
} catch {
    Write-Host ""
    Write-Host "[CANH BAO] Backend dang khoi dong hoac chua san sang." -ForegroundColor Yellow
    Write-Host "Ban co the kiem tra log chi tiet bang lenh: docker compose logs -f backend"
}

Write-Host ""
