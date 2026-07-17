"""
collectors/gpu_collector.py
Thu thập thông tin GPU: tên, VRAM, driver version, nhiệt độ (nếu có LHM).

API sử dụng:
  - WMI Win32_VideoController: tên GPU, VRAM, driver version, resolution
  - LHM sensor data: nhiệt độ GPU (nếu đang chạy)
"""
from __future__ import annotations

from typing import Dict, Any, List

from utils.wmi_helper import wmi_query, safe_get


def collect(sensor_data: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Thu thập thông tin GPU (có thể có nhiều GPU trên 1 máy).

    Args:
        sensor_data: Dict từ LHM chứa 'gpu_temp', 'gpu_load'

    Returns:
        Dict với 'gpus': list thông tin từng GPU
    """
    sensor_data = sensor_data or {}
    gpus: List[Dict] = []

    # ─── Đọc tất cả GPU từ WMI ───────────────────────────────────────────────
    controllers = wmi_query(r"root\cimv2",
                            "SELECT * FROM Win32_VideoController")

    for i, ctrl in enumerate(controllers):
        name = safe_get(ctrl, "Name", "Unknown GPU").strip()

        # Bỏ qua Microsoft Basic Display Adapter (driver ảo)
        if "Microsoft Basic Display" in name or "Remote Desktop" in name:
            continue

        # VRAM — WMI trả bytes, chuyển sang MB/GB
        vram_bytes = int(safe_get(ctrl, "AdapterRAM", 0))
        # WMI AdapterRAM bị cap ở 4GB trên GPU > 4GB (32-bit field)
        # Đây là giới hạn của WMI, chấp nhận hiển thị N/A cho GPU nhiều VRAM hơn
        if vram_bytes > 0:
            vram_mb = vram_bytes / 1024**2
            if vram_mb >= 1024:
                vram_str = f"{vram_mb/1024:.1f} GB"
            else:
                vram_str = f"{vram_mb:.0f} MB"
            vram_gb = round(vram_mb / 1024, 2)
        else:
            vram_str = "N/A"
            vram_gb  = 0

        # Driver version
        driver_ver = safe_get(ctrl, "DriverVersion", "N/A").strip()

        # Driver date — format WMI: "20230101000000.000000+000"
        driver_date_raw = safe_get(ctrl, "DriverDate", "")
        if driver_date_raw and len(driver_date_raw) >= 8:
            y = driver_date_raw[0:4]
            m = driver_date_raw[4:6]
            d = driver_date_raw[6:8]
            driver_date = f"{d}/{m}/{y}"
        else:
            driver_date = "N/A"

        # Resolution hiện tại
        h_res = int(safe_get(ctrl, "CurrentHorizontalResolution", 0))
        v_res = int(safe_get(ctrl, "CurrentVerticalResolution", 0))
        refresh = int(safe_get(ctrl, "CurrentRefreshRate", 0))
        resolution = f"{h_res}×{v_res}@{refresh}Hz" if h_res and v_res else "N/A"

        # Trạng thái
        status = safe_get(ctrl, "Status", "N/A").strip()

        gpu_info = {
            "name":          name,
            "vram_gb":       vram_gb,
            "vram_str":      vram_str,
            "driver_version": driver_ver,
            "driver_date":   driver_date,
            "resolution":    resolution,
            "status":        status,
            "temperature_c": None,
            "load_pct":      None,
        }

        # ─── Nhiệt độ GPU từ LHM sensor ──────────────────────────────────────
        # Nếu có nhiều GPU, LHM thường chỉ trả về GPU chính
        # TODO: mở rộng để map sensor theo tên GPU nếu cần
        if i == 0:
            if "gpu_temp" in sensor_data:
                gpu_info["temperature_c"] = round(sensor_data["gpu_temp"], 1)
            if "gpu_load" in sensor_data:
                gpu_info["load_pct"] = round(sensor_data["gpu_load"], 1)

        gpus.append(gpu_info)

    return {"gpus": gpus}
