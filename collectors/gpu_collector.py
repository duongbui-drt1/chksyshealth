"""
collectors/gpu_collector.py
Thu thập thông tin cấu hình đồ họa GPU: tên card, hãng, VRAM, Driver Version, Driver Date,
Architecture, Die Size, Transistors, Shaders, Memory Type (GDDR6/HBM...), Bus Width, Clocks, Resolution.

API & Công cụ sử dụng:
  - GPU-Z (gpuz_data): cấu hình phần cứng đồ họa chuyên sâu nhất từ TechPowerUp
  - WMI Win32_VideoController: thông tin cơ bản, độ phân giải màn hình hiện tại
"""
from __future__ import annotations

from typing import Dict, Any, List

from utils.wmi_helper import wmi_query, safe_get


def collect(gpuz_data: List[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Thu thập và tổng hợp thông tin GPU (có thể có nhiều GPU trên 1 máy).

    Args:
        gpuz_data: List các dict trích xuất từ báo cáo XML của GPU-Z

    Returns:
        Dict với 'gpus': list thông tin chi tiết từng card đồ họa
    """
    gpuz_data = gpuz_data or []
    gpus: List[Dict] = []

    # ─── 1. Đọc tất cả GPU từ WMI Win32_VideoController ───────────────────────
    controllers = wmi_query(r"root\cimv2", "SELECT * FROM Win32_VideoController")

    for i, ctrl in enumerate(controllers):
        name = safe_get(ctrl, "Name", "Unknown GPU").strip()
        if "Microsoft Basic Display" in name or "Remote Desktop" in name:
            continue

        vram_bytes = int(safe_get(ctrl, "AdapterRAM", 0))
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

        driver_ver = safe_get(ctrl, "DriverVersion", "N/A").strip()
        driver_date_raw = safe_get(ctrl, "DriverDate", "")
        if driver_date_raw and len(driver_date_raw) >= 8:
            y = driver_date_raw[0:4]
            m = driver_date_raw[4:6]
            d = driver_date_raw[6:8]
            driver_date = f"{d}/{m}/{y}"
        else:
            driver_date = "N/A"

        h_res = int(safe_get(ctrl, "CurrentHorizontalResolution", 0))
        v_res = int(safe_get(ctrl, "CurrentVerticalResolution", 0))
        refresh = int(safe_get(ctrl, "CurrentRefreshRate", 0))
        resolution = f"{h_res}×{v_res}@{refresh}Hz" if h_res and v_res else "N/A"
        status = safe_get(ctrl, "Status", "N/A").strip()

        gpu_info = {
            "name":           name,
            "vram_gb":        vram_gb,
            "vram_str":       vram_str,
            "driver_version": driver_ver,
            "driver_date":    driver_date,
            "resolution":     resolution,
            "status":         status,
            "architecture":   "N/A",
            "die_size":       "N/A",
            "transistors":    "N/A",
            "shaders":        "N/A",
            "directx":        "N/A",
            "memory_type":    "N/A",
            "memory_bus_width": "N/A",
            "gpu_clock":      "N/A",
            "memory_clock":   "N/A",
            "subvendor":      "N/A",
            "temperature_c":  None,
        }

        # ─── 2. Match & gộp dữ liệu chuyên sâu từ GPU-Z ──────────────────────
        matched_gz = None
        if i < len(gpuz_data):
            matched_gz = gpuz_data[i]
        else:
            # Thử match theo tên
            for gz in gpuz_data:
                gz_name = gz.get("name", "").lower()
                if gz_name in name.lower() or name.lower() in gz_name:
                    matched_gz = gz
                    break

        if matched_gz:
            if matched_gz.get("architecture"): gpu_info["architecture"] = matched_gz["architecture"]
            if matched_gz.get("die_size"): gpu_info["die_size"] = matched_gz["die_size"]
            if matched_gz.get("transistors"): gpu_info["transistors"] = matched_gz["transistors"]
            if matched_gz.get("shaders"): gpu_info["shaders"] = matched_gz["shaders"]
            if matched_gz.get("directx"): gpu_info["directx"] = matched_gz["directx"]
            if matched_gz.get("memory_type"): gpu_info["memory_type"] = matched_gz["memory_type"]
            if matched_gz.get("memory_bus_width"): gpu_info["memory_bus_width"] = matched_gz["memory_bus_width"]
            if matched_gz.get("gpu_clock"): gpu_info["gpu_clock"] = matched_gz["gpu_clock"]
            if matched_gz.get("memory_clock"): gpu_info["memory_clock"] = matched_gz["memory_clock"]
            if matched_gz.get("subvendor"): gpu_info["subvendor"] = matched_gz["subvendor"]
            if matched_gz.get("temperature_c") is not None: gpu_info["temperature_c"] = matched_gz["temperature_c"]
            if matched_gz.get("memory_size_str") and gpu_info["vram_str"] == "N/A":
                gpu_info["vram_str"] = matched_gz["memory_size_str"]

        gpus.append(gpu_info)

    # Nếu WMI không tìm ra GPU nào nhưng GPU-Z có dữ liệu
    if not gpus and gpuz_data:
        for gz in gpuz_data:
            gpus.append({
                "name": gz.get("name", "GPU-Z Detected Card"),
                "vram_str": gz.get("memory_size_str", "N/A"),
                "driver_version": gz.get("driver_version", "N/A"),
                "driver_date": "N/A",
                "resolution": "N/A",
                "status": "OK",
                "architecture": gz.get("architecture", "N/A"),
                "die_size": gz.get("die_size", "N/A"),
                "transistors": gz.get("transistors", "N/A"),
                "shaders": gz.get("shaders", "N/A"),
                "directx": gz.get("directx", "N/A"),
                "memory_type": gz.get("memory_type", "N/A"),
                "memory_bus_width": gz.get("memory_bus_width", "N/A"),
                "gpu_clock": gz.get("gpu_clock", "N/A"),
                "memory_clock": gz.get("memory_clock", "N/A"),
                "subvendor": gz.get("subvendor", "N/A"),
                "temperature_c": gz.get("temperature_c", None),
            })

    return {"gpus": gpus}
