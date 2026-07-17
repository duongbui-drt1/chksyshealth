# CheckSysHealth PowerShell One-Liner Bootstrapper
# Author: Duli Software
# Usage: irm https://raw.githubusercontent.com/duongbui-drt1/chksyshealth/main/run.ps1 | iex

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# 1. Tự động kiểm tra và xin quyền Administrator (UAC) nếu chưa có
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host " [UAC] Đang yêu cầu quyền Administrator để đọc thông tin phần cứng..." -ForegroundColor Yellow
    # Kiểm tra xem script được gọi từ đâu để chạy với quyền Admin
    $scriptUrl = "https://raw.githubusercontent.com/duongbui-drt1/chksyshealth/main/run.ps1"
    $psCommand = "irm '$scriptUrl' | iex"
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -Command `"$psCommand`""
    exit
}

Write-Host "`n ========================================================" -ForegroundColor Cyan
Write-Host "       CheckSysHealth v1.0 - Duli Software" -ForegroundColor Cyan
Write-Host " ========================================================`n" -ForegroundColor Cyan

# 2. Tạo thư mục làm việc tạm thời
$workDir = "$env:TEMP\CheckSysHealth_Bootstrapper"
if (Test-Path $workDir) { Remove-Item -Recurse -Force $workDir -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
Set-Location $workDir

# 3. Kiểm tra Python trong hệ thống (py, python, python3)
$pyCmd = $null
foreach ($cmd in @("python", "py -3", "python3")) {
    try {
        $ver = Invoke-Expression "$cmd --version 2>&1"
        if ($ver -like "*Python 3*") {
            $pyCmd = $cmd
            break
        }
    } catch { continue }
}

if ($pyCmd) {
    Write-Host " [OK] Phát hiện Python: ($ver)" -ForegroundColor Green
    Write-Host " [INFO] Đang tải mã nguồn mới nhất từ GitHub repository..." -ForegroundColor Cyan
    
    $zipUrl = "https://github.com/duongbui-drt1/chksyshealth/archive/refs/heads/main.zip"
    $zipPath = "$workDir\main.zip"
    Invoke-WebRequest -Uri $zipUrl -OutFile $zipPath
    
    Write-Host " [INFO] Đang giải nén..." -ForegroundColor Cyan
    Expand-Archive -Path $zipPath -DestinationPath $workDir -Force
    Set-Location "$workDir\chksyshealth-main"
    
    Write-Host " [INFO] Đang kiểm tra thư viện (pip install -r requirements.txt)..." -ForegroundColor Cyan
    Invoke-Expression "$pyCmd -m pip install -q -r requirements.txt --disable-pip-version-check"
    
    Write-Host " [RUN] Đang khởi chạy CheckSysHealth... Vui lòng đợi trong giây lát...`n" -ForegroundColor Green
    Invoke-Expression "$pyCmd checksyshealth.py"
} else {
    Write-Host " [WARN] Không tìm thấy Python 3 trên hệ thống." -ForegroundColor Yellow
    Write-Host " [INFO] Đang kiểm tra và tải bản CheckSysHealth.exe (Standalone) từ GitHub Releases..." -ForegroundColor Cyan
    
    $exeUrl = "https://github.com/duongbui-drt1/chksyshealth/releases/latest/download/CheckSysHealth.exe"
    $exePath = "$workDir\CheckSysHealth.exe"
    
    try {
        Invoke-WebRequest -Uri $exeUrl -OutFile $exePath
        Write-Host " [RUN] Đang khởi chạy CheckSysHealth.exe...`n" -ForegroundColor Green
        Start-Process -FilePath $exePath -Wait
    } catch {
        Write-Host "`n [ERROR] Chưa tìm thấy file CheckSysHealth.exe trên GitHub Releases hoặc tải thất bại." -ForegroundColor Red
        Write-Host " [GUIDE] Vui lòng cài đặt Python 3 từ https://www.python.org/downloads/ hoặc tải file CheckSysHealth.exe trực tiếp từ repo." -ForegroundColor Yellow
    }
}

Write-Host "`n [DONE] Quá trình kiểm tra hoàn tất." -ForegroundColor Green
