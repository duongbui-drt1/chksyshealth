r"""
tools/ohm_manager.py
Quản lý LibreHardwareMonitor (LHM) — công cụ đọc sensor nhiệt độ CPU/GPU.

Luồng hoạt động:
  1. Kiểm tra xem LHM đã được cache chưa (thư mục temp)
  2. Nếu online và chưa có → tải xuống từ GitHub releases (hiển thị progress bar)
  3. Giải nén ZIP vào thư mục temp tạm thời
  4. Khởi động LHM.exe chạy ẩn (hidden window), không hiện trên taskbar
  5. Chờ 4 giây để LHM đăng ký WMI namespace
  6. Đọc dữ liệu sensor từ WMI namespace root/LibreHardwareMonitor
  7. Kill process LHM sau khi đọc xong
  8. Trả về dict { 'cpu_temp': float, 'gpu_temp': float, ... }

Yêu cầu:
  - Cần quyền Administrator để LHM đăng ký WMI provider
  - Cần kết nối internet để tải xuống lần đầu
  - Nếu không có internet hoặc tải thất bại → trả về dict rỗng (graceful fallback)
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Optional

from utils.progress import (
    print_step, print_ok, print_warn, print_error,
    make_download_callback, print_progress_bar
)
from utils.wmi_helper import wmi_query

# URL tải LibreHardwareMonitor từ GitHub releases
# Chọn phiên bản net472 để tương thích Windows 10/11 không cần .NET 6+
LHM_DOWNLOAD_URL = (
    "https://github.com/LibreHardwareMonitor/LibreHardwareMonitor"
    "/releases/download/v0.9.3/LibreHardwareMonitor-net472.zip"
)
LHM_EXE_NAME = "LibreHardwareMonitor.exe"

# WMI namespace mà LHM đăng ký khi đang chạy
LHM_WMI_NAMESPACE = r"root\LibreHardwareMonitor"

# Thư mục cache — dùng %TEMP%\CheckSysHealth\lhm\ để tránh tải lại mỗi lần
_CACHE_DIR = Path(tempfile.gettempdir()) / "CheckSysHealth" / "lhm"

# Process LHM đang chạy (global để có thể kill sau khi dùng xong)
_lhm_process: Optional[subprocess.Popen] = None


def _get_cached_exe() -> Optional[Path]:
    """
    Tìm file LHM.exe trong thư mục cache.
    Trả về Path nếu tồn tại, None nếu chưa có.
    """
    exe = _CACHE_DIR / LHM_EXE_NAME
    return exe if exe.exists() else None


def _download_lhm() -> Optional[Path]:
    """
    Tải LibreHardwareMonitor từ GitHub và giải nén vào thư mục cache.
    Hiển thị progress bar trong quá trình tải.

    Returns:
        Path tới LHM.exe nếu thành công, None nếu thất bại
    """
    try:
        import requests
    except ImportError:
        print_warn("Thư viện 'requests' chưa được cài — không thể tải LHM")
        return None

    print_step("Tải LibreHardwareMonitor (đọc sensor nhiệt độ)")

    try:
        # Tạo thư mục cache nếu chưa có
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        zip_path = _CACHE_DIR / "lhm.zip"

        # Tải với streaming để hiển thị progress bar
        resp = requests.get(LHM_DOWNLOAD_URL, stream=True, timeout=30)
        resp.raise_for_status()

        total_size = int(resp.headers.get("content-length", 0))
        downloaded = 0
        callback = make_download_callback("LibreHardwareMonitor")

        with open(zip_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    callback(downloaded, total_size)

        print_ok(f"Đã tải LHM ({downloaded/1024/1024:.1f} MB)")

        # Giải nén ZIP
        print_step("Giải nén LibreHardwareMonitor")
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(_CACHE_DIR)

        # Dọn file zip tạm
        zip_path.unlink(missing_ok=True)

        # Tìm file exe sau khi giải nén (có thể nằm trong subfolder)
        for exe_path in _CACHE_DIR.rglob(LHM_EXE_NAME):
            # Di chuyển lên thư mục cache gốc nếu nằm trong subfolder
            target = _CACHE_DIR / LHM_EXE_NAME
            if exe_path != target:
                shutil.move(str(exe_path), str(target))
            print_ok(f"LibreHardwareMonitor sẵn sàng: {target}")
            return target

        print_warn(f"Không tìm thấy {LHM_EXE_NAME} sau khi giải nén")
        return None

    except Exception as exc:
        print_warn(f"Không thể tải LibreHardwareMonitor: {exc}")
        return None


def _ensure_lhm_config(exe_path: Path) -> None:
    """
    Tạo hoặc cập nhật file LibreHardwareMonitor.config để bật WMI = true.
    Mặc định LHM không bật WMI provider nếu chưa cấu hình trong file này.
    """
    config_path = exe_path.parent / "LibreHardwareMonitor.config"
    config_content = """<?xml version="1.0" encoding="utf-8"?>
<LibreHardwareMonitor>
  <Option name="WMI" value="true" />
  <Option name="MinimizeToTray" value="true" />
  <Option name="MinimizetoTray" value="true" />
  <Option name="RunOnStartup" value="false" />
</LibreHardwareMonitor>"""
    try:
        config_path.write_text(config_content, encoding="utf-8")
    except Exception as exc:
        print_warn(f"Không thể ghi config LHM: {exc}")


def _start_lhm(exe_path: Path) -> bool:
    """
    Khởi động LHM thu nhỏ vào khay hệ thống (không hiện trên màn hình).
    LHM cần chạy để đăng ký WMI namespace và cập nhật sensor.

    Returns:
        True nếu khởi động thành công
    """
    global _lhm_process
    try:
        _ensure_lhm_config(exe_path)

        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 7  # SW_SHOWMINNOACTIVE (thu nhỏ không chiếm focus)

        _lhm_process = subprocess.Popen(
            [str(exe_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            startupinfo=si,
            cwd=str(exe_path.parent)
        )
        return True
    except Exception as exc:
        print_warn(f"Không thể khởi động LHM: {exc}")
        _lhm_process = None
        return False


def _read_sensors_from_wmi() -> Dict[str, float]:
    """
    Đọc dữ liệu sensor từ WMI namespace root/LibreHardwareMonitor.
    LHM phải đang chạy để namespace này tồn tại.

    Returns:
        Dict với các key:
          'cpu_temp': nhiệt độ CPU (°C)
          'gpu_temp': nhiệt độ GPU (°C)
          'cpu_load': % tải CPU
          'gpu_load': % tải GPU
    """
    result: Dict[str, float] = {}

    sensors = wmi_query(LHM_WMI_NAMESPACE, "SELECT * FROM Sensor")
    if not sensors:
        return result

    # Lọc và lấy giá trị từng sensor
    for s in sensors:
        try:
            name        = (getattr(s, "Name", "") or "").lower()
            sensor_type = (getattr(s, "SensorType", "") or "").lower()
            value       = getattr(s, "Value", None)
            hardware    = (getattr(s, "Hardware", "") or "").lower()
            identifier  = (getattr(s, "Identifier", "") or "").lower()

            if value is None:
                continue

            # Kiểm tra xem sensor có thuộc về CPU không (Identifier hoặc Hardware chứa từ khóa CPU)
            is_cpu = (
                "/intelcpu/" in identifier or
                "/amdcpu/" in identifier or
                "/cpu/" in identifier or
                any(kw in hardware for kw in ["cpu", "intel", "amd", "ryzen", "core", "xeon", "celeron", "pentium", "athlon"])
            )

            # Kiểm tra xem sensor có thuộc về GPU không
            is_gpu = (
                "/gpu/" in identifier or
                "/nvidiagpu/" in identifier or
                "/amdgpu/" in identifier or
                any(kw in hardware for kw in ["gpu", "radeon", "geforce", "nvidia", "intel uhd", "intel hd", "iris"])
            )

            # Nhiệt độ CPU — ưu tiên "CPU Package", "CPU Die", "Core Average"
            if sensor_type == "temperature" and is_cpu:
                if any(k in name for k in ["package", "die", "core avg", "tctl", "tdie", "average"]):
                    result["cpu_temp"] = float(value)
                elif "cpu_temp" not in result:
                    # Fallback: lấy sensor temperature đầu tiên của CPU
                    result["cpu_temp"] = float(value)

            # Nhiệt độ GPU
            elif sensor_type == "temperature" and is_gpu:
                if "core" in name or "gpu_temp" not in result:
                    result["gpu_temp"] = float(value)

            # % tải CPU
            elif sensor_type == "load" and is_cpu:
                if any(k in name for k in ["total", "cpu total", "cpu load"]):
                    result["cpu_load"] = float(value)
                elif "cpu_load" not in result and "package" in name:
                    result["cpu_load"] = float(value)

            # % tải GPU
            elif sensor_type == "load" and is_gpu:
                if "core" in name or "gpu_load" not in result:
                    result["gpu_load"] = float(value)

        except Exception:
            continue

    return result


def _read_native_acpi_thermal() -> Dict[str, float]:
    """
    Đọc cảm biến nhiệt độ ACPI tích hợp sẵn trong kernel Windows (Native WMI).
    Thay thế cho LibreHardwareMonitor khi máy bị chặn driver ring-0 hoặc Core Isolation.
    """
    result: Dict[str, float] = {}
    for tbl in [
        "Win32_PerfFormattedData_Counters_ThermalZoneInformation",
        "Win32_PerfRawData_Counters_ThermalZoneInformation"
    ]:
        try:
            zones = wmi_query(r"root\cimv2", f"SELECT * FROM {tbl}")
            temps = []
            for z in zones:
                for attr in ["HighPrecisionTemperature", "Temperature"]:
                    try:
                        val = getattr(z, attr, None)
                        if val is not None and str(val).strip() != "":
                            t = float(val)
                            if 200 < t < 2000:  # Kelvin -> Celsius
                                temps.append(round(t - 273.15, 1))
                            elif t >= 2000:     # 0.1 Kelvin -> Celsius
                                temps.append(round((t - 2732) / 10.0, 1))
                    except Exception:
                        continue
            valid_temps = [c for c in temps if 20 <= c <= 115]
            if valid_temps:
                result["cpu_temp"] = max(valid_temps)
                return result
        except Exception:
            continue

    try:
        zones = wmi_query(r"root\wmi", "SELECT * FROM MSAcpi_ThermalZoneTemperature")
        temps = []
        for z in zones:
            try:
                val = getattr(z, "CurrentTemperature", None)
                if val is not None:
                    cur = float(val)
                    if cur > 2000:
                        temps.append(round((cur - 2732) / 10.0, 1))
            except Exception:
                continue
        valid_temps = [c for c in temps if 20 <= c <= 115]
        if valid_temps:
            result["cpu_temp"] = max(valid_temps)
    except Exception:
        pass

    return result


def stop_lhm() -> None:
    """
    Dừng process LibreHardwareMonitor nếu đang chạy.
    Gọi hàm này khi kết thúc chương trình để dọn dẹp.
    """
    global _lhm_process
    if _lhm_process is not None:
        try:
            _lhm_process.terminate()
            _lhm_process.wait(timeout=5)
            print_ok("LibreHardwareMonitor đã dừng")
        except Exception:
            try:
                _lhm_process.kill()
            except Exception:
                pass
        finally:
            _lhm_process = None


def get_sensor_data(is_online: bool = False) -> Dict[str, float]:
    """
    Hàm chính: lấy dữ liệu sensor từ LibreHardwareMonitor hoặc Native Windows ACPI.
    """
    sensors: Dict[str, float] = {}

    # Bước 1: Thử đọc cảm biến gốc ACPI từ kernel Windows trước (siêu nhanh, không cần LHM)
    native_sensors = _read_native_acpi_thermal()
    if "cpu_temp" in native_sensors:
        sensors["cpu_temp"] = native_sensors["cpu_temp"]

    # Bước 2: Tìm LHM exe trong cache để đọc thêm GPU / chi tiết
    exe_path = _get_cached_exe()
    if exe_path is None and is_online:
        exe_path = _download_lhm()

    if exe_path is not None and _start_lhm(exe_path):
        print_step("Chờ sensor WMI sẵn sàng")
        lhm_sensors = {}
        for attempt in range(8):
            time.sleep(0.6)
            lhm_sensors = _read_sensors_from_wmi()
            if lhm_sensors:
                break
        stop_lhm()

        # Cập nhật kết quả LHM vào sensors
        if "cpu_temp" in lhm_sensors and lhm_sensors["cpu_temp"] > 0:
            sensors["cpu_temp"] = lhm_sensors["cpu_temp"]
        if "gpu_temp" in lhm_sensors and lhm_sensors["gpu_temp"] > 0:
            sensors["gpu_temp"] = lhm_sensors["gpu_temp"]
        if "cpu_load" in lhm_sensors:
            sensors["cpu_load"] = lhm_sensors["cpu_load"]
        if "gpu_load" in lhm_sensors:
            sensors["gpu_load"] = lhm_sensors["gpu_load"]

    if sensors:
        temps = []
        if "cpu_temp" in sensors:
            temps.append(f"CPU {sensors['cpu_temp']:.0f}°C")
        if "gpu_temp" in sensors:
            temps.append(f"GPU {sensors['gpu_temp']:.0f}°C")
        print_ok(f"Sensor: {', '.join(temps) if temps else 'đã đọc'}")
    else:
        print_warn("Không đọc được cảm biến nhiệt độ (ACPI/LHM bị chặn)")

    return sensors
