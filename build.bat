@echo off
:: ============================================================
:: build.bat — Đóng gói CheckSysHealth thành file .exe
:: Yêu cầu: Python 3.8+ đã cài, pip hoạt động
:: Chạy: build.bat (không cần quyền admin)
:: Output: dist\CheckSysHealth.exe
:: ============================================================

echo.
echo  ╔═══════════════════════════════════════════╗
echo  ║    CheckSysHealth — Build Script          ║
echo  ║    Đóng gói thành .exe với PyInstaller   ║
echo  ╚═══════════════════════════════════════════╝
echo.

:: ─── Bước 1: Cài thư viện nếu chưa có ─────────────────────────────────────
echo [1/4] Cài đặt dependencies...
pip install -r requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [LÔI] Không cài được requirements.txt
    echo Kiểm tra kết nối internet và Python/pip đã cài chưa.
    pause & exit /b 1
)

pip install pyinstaller --quiet
if %errorlevel% neq 0 (
    echo [LÔI] Không cài được PyInstaller
    pause & exit /b 1
)
echo [OK] Dependencies đã cài xong.

:: ─── Bước 2: Tải Chart.js vào cache ────────────────────────────────────────
echo.
echo [2/4] Tải Chart.js (để nhúng vào report)...
python -c "
import requests, pathlib, tempfile
p = pathlib.Path(tempfile.gettempdir()) / 'CheckSysHealth' / 'chartjs.min.js'
p.parent.mkdir(parents=True, exist_ok=True)
if p.exists() and p.stat().st_size > 10000:
    print('[OK] Chart.js đã có trong cache')
else:
    try:
        r = requests.get('https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js', timeout=20)
        p.write_bytes(r.content)
        print(f'[OK] Chart.js tải xong ({len(r.content)//1024} KB)')
    except Exception as e:
        print(f'[WARN] Không tải được Chart.js: {e}')
        print('[INFO] Report vẫn hoạt động, nhưng không có biểu đồ tròn')
"

:: ─── Bước 3: Dọn build cũ ──────────────────────────────────────────────────
echo.
echo [3/4] Chuẩn bị build...
if exist "dist\CheckSysHealth.exe" del /f "dist\CheckSysHealth.exe"
if exist "build" rmdir /s /q "build"
if exist "CheckSysHealth.spec" del /f "CheckSysHealth.spec"

:: ─── Bước 4: Build với PyInstaller ─────────────────────────────────────────
echo.
echo [4/4] Đang build...
echo (Quá trình này có thể mất 1-3 phút)

pyinstaller ^
  --onefile ^
  --uac-admin ^
  --name "CheckSysHealth" ^
  --console ^
  --hidden-import win32api ^
  --hidden-import win32con ^
  --hidden-import win32security ^
  --hidden-import win32process ^
  --hidden-import win32service ^
  --hidden-import win32serviceutil ^
  --hidden-import win32clipboard ^
  --hidden-import win32evtlog ^
  --hidden-import wmi ^
  --hidden-import pywintypes ^
  --hidden-import pythoncom ^
  --hidden-import psutil ^
  --hidden-import colorama ^
  --hidden-import requests ^
  --hidden-import winreg ^
  --hidden-import zipfile ^
  --hidden-import socket ^
  --collect-submodules collectors ^
  --collect-submodules utils ^
  --collect-submodules tools ^
  --collect-submodules report ^
  checksyshealth.py

if %errorlevel% neq 0 (
    echo.
    echo [LÔI] Build thất bại! Xem log ở trên để biết chi tiết.
    pause & exit /b 1
)

echo.
echo  ╔═══════════════════════════════════════════════════════╗
echo  ║  BUILD THÀNH CÔNG!                                     ║
echo  ║  File: dist\CheckSysHealth.exe                        ║
echo  ║  Chạy file .exe này với quyền Administrator           ║
echo  ║  (hoặc double-click, Windows sẽ tự hỏi UAC)          ║
echo  ╚═══════════════════════════════════════════════════════╝
echo.

:: Mở thư mục dist
explorer dist

pause
