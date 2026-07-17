"""
collectors/cpu_collector.py
Thu thập thông tin CPU: tên, hãng, số nhân/luồng, xung nhịp,
% tải hiện tại, nhiệt độ (nếu có LHM), Processor ID.

API sử dụng:
  - WMI Win32_Processor: thông tin tĩnh CPU
  - psutil.cpu_percent(): % tải thực tế
  - WMI root/LibreHardwareMonitor: nhiệt độ (nếu LHM đang chạy)
"""
from __future__ import annotations

import psutil
from typing import Dict, Any, Optional

from utils.wmi_helper import wmi_query, safe_get


def collect(sensor_data: Dict[str, float] = None) -> Dict[str, Any]:
    """
    Thu thập toàn bộ thông tin CPU.

    Args:
        sensor_data: Dict từ OHM/LHM chứa nhiệt độ sensor
                     (key 'cpu_temp', 'cpu_load')

    Returns:
        Dict thông tin CPU với các key:
          name, manufacturer, cores, threads, base_clock_mhz,
          max_clock_mhz, current_clock_mhz, load_pct, temperature_c,
          processor_id, architecture, socket, l2_cache_kb, l3_cache_kb
    """
    sensor_data = sensor_data or {}
    result: Dict[str, Any] = {
        "name":            "N/A",
        "manufacturer":    "N/A",
        "cores":           0,
        "threads":         0,
        "base_clock_mhz":  0,
        "max_clock_mhz":   0,
        "current_clock_mhz": 0,
        "load_pct":        0.0,
        "temperature_c":   None,
        "processor_id":    "N/A",
        "architecture":    "N/A",
        "socket":          "N/A",
        "l2_cache_kb":     0,
        "l3_cache_kb":     0,
        "description":     "N/A",
    }

    # ─── Đọc thông tin tĩnh CPU từ WMI ───────────────────────────────────────
    cpus = wmi_query(r"root\cimv2", "SELECT * FROM Win32_Processor")
    if cpus:
        cpu = cpus[0]  # Lấy CPU đầu tiên (đa số máy chỉ có 1 socket)

        result["name"]            = safe_get(cpu, "Name", "N/A").strip()
        result["manufacturer"]    = safe_get(cpu, "Manufacturer", "N/A").strip()
        result["description"]     = safe_get(cpu, "Description", "N/A").strip()
        result["processor_id"]    = safe_get(cpu, "ProcessorId", "N/A").strip()

        def _int(val, default=0):
            """Chuyển đổi an toàn sang int, trả về default nếu không hợp lệ."""
            try:
                return int(val) if val not in (None, "N/A", "") else default
            except (ValueError, TypeError):
                return default

        # Số nhân vật lý (NumberOfCores) và số luồng logic (NumberOfLogicalProcessors)
        result["cores"]   = _int(safe_get(cpu, "NumberOfCores", 0))
        result["threads"] = _int(safe_get(cpu, "NumberOfLogicalProcessors", 0))

        # Xung nhịp — WMI trả MHz
        result["max_clock_mhz"]     = _int(safe_get(cpu, "MaxClockSpeed", 0))
        result["current_clock_mhz"] = _int(safe_get(cpu, "CurrentClockSpeed", 0))
        result["base_clock_mhz"]    = result["max_clock_mhz"]

        # Cập nhật xung nhịp thực tế từ psutil (độ chính xác cao hơn, không bị khoá ở xung nhịp tĩnh)
        try:
            freq = psutil.cpu_freq()
            if freq:
                if freq.current > 0:
                    result["current_clock_mhz"] = int(freq.current)
                if freq.max > 0 and freq.max > result["max_clock_mhz"]:
                    result["max_clock_mhz"] = int(freq.max)
        except Exception:
            pass

        # Cache — WMI trả kilobytes
        result["l2_cache_kb"] = _int(safe_get(cpu, "L2CacheSize", 0))
        result["l3_cache_kb"] = _int(safe_get(cpu, "L3CacheSize", 0))

        # Socket
        result["socket"] = safe_get(cpu, "SocketDesignation", "N/A").strip()

        # Architecture (AddressWidth: 32 hoặc 64 bit)
        addr_width = _int(safe_get(cpu, "AddressWidth", 64), 64)
        result["architecture"] = f"x{addr_width}"

    # ─── % tải CPU thực tế (psutil chính xác hơn WMI LoadPercentage) ─────────
    # Đo trong 0.5 giây để có số chính xác
    try:
        result["load_pct"] = round(psutil.cpu_percent(interval=0.5), 1)
    except Exception:
        # Fallback: đọc từ WMI nếu psutil thất bại
        if cpus:
            result["load_pct"] = float(safe_get(cpus[0], "LoadPercentage", 0))

    # ─── Nhiệt độ CPU từ LHM sensor data ────────────────────────────────────
    if "cpu_temp" in sensor_data:
        result["temperature_c"] = round(sensor_data["cpu_temp"], 1)
    elif "cpu_load" in sensor_data:
        # Cập nhật lại load từ LHM nếu chính xác hơn
        result["load_pct"] = round(sensor_data["cpu_load"], 1)

    # ─── Tính health score CPU ───────────────────────────────────────────────
    temp = result.get("temperature_c")
    if temp is not None:
        # Phân loại nhiệt độ: <70°C tốt, 70-85°C cảnh báo, >85°C nguy hiểm
        if temp < 70:
            result["temp_status"] = "good"
        elif temp < 85:
            result["temp_status"] = "warn"
        else:
            result["temp_status"] = "danger"
    else:
        result["temp_status"] = "unknown"

    return result
