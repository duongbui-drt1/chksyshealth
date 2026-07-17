"""
collectors/cpu_collector.py
Thu thập thông tin CPU: tên, hãng, codename, socket, tiến trình nm, tập lệnh,
số nhân/luồng, xung nhịp, % tải hiện tại, L1/L2/L3 Cache, Processor ID.

API & Công cụ sử dụng:
  - CPU-Z (cpuz_data): thông tin cấu hình phần cứng chuyên sâu nhất (Codename, NM, Instructions, Caches)
  - WMI Win32_Processor: thông tin tĩnh nền tảng
  - psutil.cpu_percent(): % tải thực tế thời gian thực
"""
from __future__ import annotations

import psutil
from typing import Dict, Any, Optional

from utils.wmi_helper import wmi_query, safe_get


def collect(cpuz_data: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    Thu thập và tổng hợp toàn bộ thông tin CPU.

    Args:
        cpuz_data: Dict trích xuất từ báo cáo của CPU-Z

    Returns:
        Dict thông tin CPU đầy đủ
    """
    cpuz_data = cpuz_data or {}
    result: Dict[str, Any] = {
        "name":            "N/A",
        "codename":        "N/A",
        "manufacturer":    "N/A",
        "socket":          "N/A",
        "technology_nm":   "N/A",
        "instructions":    "N/A",
        "stepping":        "N/A",
        "cores":           0,
        "threads":         0,
        "base_clock_mhz":  0,
        "max_clock_mhz":   0,
        "current_clock_mhz": 0,
        "load_pct":        0.0,
        "temperature_c":   None,
        "processor_id":    "N/A",
        "architecture":    "N/A",
        "l1_cache_str":    "N/A",
        "l2_cache_kb":     0,
        "l2_cache_str":    "N/A",
        "l3_cache_kb":     0,
        "l3_cache_str":    "N/A",
        "description":     "N/A",
    }

    # ─── 1. Đọc thông tin tĩnh từ WMI Win32_Processor ────────────────────────
    cpus = wmi_query(r"root\cimv2", "SELECT * FROM Win32_Processor")
    if cpus:
        cpu = cpus[0]

        result["name"]            = safe_get(cpu, "Name", "N/A").strip()
        result["manufacturer"]    = safe_get(cpu, "Manufacturer", "N/A").strip()
        result["description"]     = safe_get(cpu, "Description", "N/A").strip()
        result["processor_id"]    = safe_get(cpu, "ProcessorId", "N/A").strip()

        def _int(val, default=0):
            try:
                return int(val) if val not in (None, "N/A", "") else default
            except (ValueError, TypeError):
                return default

        result["cores"]   = _int(safe_get(cpu, "NumberOfCores", 0))
        result["threads"] = _int(safe_get(cpu, "NumberOfLogicalProcessors", 0))

        result["max_clock_mhz"]     = _int(safe_get(cpu, "MaxClockSpeed", 0))
        result["current_clock_mhz"] = _int(safe_get(cpu, "CurrentClockSpeed", 0))
        result["base_clock_mhz"]    = result["max_clock_mhz"]

        # Cache WMI (KB)
        result["l2_cache_kb"] = _int(safe_get(cpu, "L2CacheSize", 0))
        result["l3_cache_kb"] = _int(safe_get(cpu, "L3CacheSize", 0))

        result["socket"] = safe_get(cpu, "SocketDesignation", "N/A").strip()

        addr_width = _int(safe_get(cpu, "AddressWidth", 64), 64)
        result["architecture"] = f"x{addr_width}"

    # Cập nhật xung nhịp từ psutil
    try:
        freq = psutil.cpu_freq()
        if freq:
            if freq.current > 0:
                result["current_clock_mhz"] = int(freq.current)
            if freq.max > 0 and freq.max > result["max_clock_mhz"]:
                result["max_clock_mhz"] = int(freq.max)
    except Exception:
        pass

    # ─── 2. Ưu tiên ghi đè & bổ sung từ dữ liệu chuyên sâu CPU-Z ──────────────
    if cpuz_data:
        if cpuz_data.get("cpuz_name") and cpuz_data["cpuz_name"] != "N/A":
            result["name"] = cpuz_data["cpuz_name"]
        if cpuz_data.get("codename"):
            result["codename"] = cpuz_data["codename"]
        if cpuz_data.get("package_socket"):
            result["socket"] = cpuz_data["package_socket"]
        if cpuz_data.get("technology_nm"):
            result["technology_nm"] = cpuz_data["technology_nm"]
        if cpuz_data.get("instructions"):
            result["instructions"] = cpuz_data["instructions"]
        if cpuz_data.get("stepping"):
            result["stepping"] = cpuz_data["stepping"]
        if cpuz_data.get("l1_data_cache"):
            result["l1_cache_str"] = cpuz_data["l1_data_cache"]
        if cpuz_data.get("l2_cache"):
            result["l2_cache_str"] = cpuz_data["l2_cache"]
        elif result["l2_cache_kb"] > 0:
            result["l2_cache_str"] = f"{result['l2_cache_kb']} KB"
        if cpuz_data.get("l3_cache"):
            result["l3_cache_str"] = cpuz_data["l3_cache"]
        elif result["l3_cache_kb"] > 0:
            result["l3_cache_str"] = f"{result['l3_cache_kb']/1024:.1f} MB"
        if cpuz_data.get("cores") and cpuz_data["cores"] > 0:
            result["cores"] = cpuz_data["cores"]
        if cpuz_data.get("threads") and cpuz_data["threads"] > 0:
            result["threads"] = cpuz_data["threads"]
    else:
        if result["l2_cache_kb"] > 0:
            result["l2_cache_str"] = f"{result['l2_cache_kb']} KB"
        if result["l3_cache_kb"] > 0:
            result["l3_cache_str"] = f"{result['l3_cache_kb']/1024:.1f} MB"

    # ─── 3. % tải CPU thực tế từ psutil ──────────────────────────────────────
    try:
        result["load_pct"] = round(psutil.cpu_percent(interval=0.5), 1)
    except Exception:
        if cpus:
            result["load_pct"] = float(safe_get(cpus[0], "LoadPercentage", 0))

    return result
