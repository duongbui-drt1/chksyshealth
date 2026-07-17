"""
collectors/ram_collector.py
Thu thập thông tin RAM: tổng dung lượng, từng thanh (capacity, hãng, tốc độ, serial),
số khe đang dùng / tổng số khe.

API sử dụng:
  - WMI Win32_PhysicalMemory: thông tin từng thanh RAM
  - WMI Win32_PhysicalMemoryArray: số khe tổng cộng
  - psutil: dung lượng RAM thực tế đang dùng
"""
from __future__ import annotations

import psutil
from typing import Dict, Any, List

from utils.wmi_helper import wmi_query, wmi_first, safe_get, safe_int


# Map mã loại RAM (MemoryType) sang tên
MEMORY_TYPE_MAP = {
    0:  "Unknown",
    1:  "Other",
    2:  "DRAM",
    3:  "Synchronous DRAM",
    4:  "Cache DRAM",
    5:  "EDO",
    6:  "EDRAM",
    7:  "VRAM",
    8:  "SRAM",
    9:  "RAM",
    10: "ROM",
    11: "Flash",
    12: "EEPROM",
    13: "FEPROM",
    14: "EPROM",
    15: "CDRAM",
    16: "3DRAM",
    17: "SDRAM",
    18: "SGRAM",
    19: "RDRAM",
    20: "DDR",
    21: "DDR2",
    22: "DDR2 FB-DIMM",
    24: "DDR3",
    26: "DDR4",
    34: "DDR5",
}

# Map mã FormFactor sang tên
FORM_FACTOR_MAP = {
    0:  "Unknown",
    1:  "Other",
    2:  "SIP",
    3:  "DIP",
    4:  "ZIP",
    5:  "SOJ",
    6:  "Proprietary",
    7:  "SIMM",
    8:  "DIMM",
    9:  "TSOP",
    10: "PGA",
    11: "RIMM",
    12: "SODIMM",
    13: "SRIMM",
    14: "SMD",
    15: "SSMP",
    16: "QFP",
    17: "TQFP",
    18: "SOIC",
    19: "LCC",
    20: "PLCC",
    21: "BGA",
    22: "FPBGA",
    23: "LGA",
}


def collect() -> Dict[str, Any]:
    """
    Thu thập thông tin RAM đầy đủ.

    Returns:
        Dict với:
          total_gb, used_gb, available_gb, used_pct,
          slots_used, slots_total,
          sticks: list các thanh RAM (capacity_gb, manufacturer, speed_mhz,
                   part_number, serial, slot, form_factor, memory_type)
    """
    result: Dict[str, Any] = {
        "total_gb":     0.0,
        "used_gb":      0.0,
        "available_gb": 0.0,
        "used_pct":     0.0,
        "slots_used":   0,
        "slots_total":  0,
        "sticks":       [],
    }

    # ─── Dung lượng RAM thực tế (psutil chính xác nhất) ─────────────────────
    try:
        vm = psutil.virtual_memory()
        result["total_gb"]     = round(vm.total     / 1024**3, 2)
        result["used_gb"]      = round(vm.used      / 1024**3, 2)
        result["available_gb"] = round(vm.available / 1024**3, 2)
        result["used_pct"]     = round(vm.percent, 1)
    except Exception:
        pass

    # ─── Số khe RAM tổng từ Win32_PhysicalMemoryArray ────────────────────────
    arrays = wmi_query(r"root\cimv2", "SELECT * FROM Win32_PhysicalMemoryArray")
    for arr in arrays:
        try:
            result["slots_total"] += int(safe_get(arr, "MemoryDevices", 0) or 0)
        except (ValueError, TypeError):
            pass

    # ─── Thông tin từng thanh RAM ────────────────────────────────────────────
    sticks_raw = wmi_query(r"root\cimv2", "SELECT * FROM Win32_PhysicalMemory")
    sticks: List[Dict] = []

    for stick in sticks_raw:
        # Dung lượng thanh RAM (byte → GB)
        capacity_bytes = safe_int(stick, "Capacity", 0)
        capacity_gb    = round(capacity_bytes / 1024**3, 2)

        # Tốc độ — ConfiguredClockSpeed chính xác hơn Speed (là speed tối đa của module)
        speed_mhz = safe_int(stick, "ConfiguredClockSpeed", 0)
        if speed_mhz == 0:
            speed_mhz = safe_int(stick, "Speed", 0)

        # Loại RAM (DDR4, DDR5...)
        mem_type_code = safe_int(stick, "SMBIOSMemoryType", 0)
        mem_type = MEMORY_TYPE_MAP.get(mem_type_code, f"Type {mem_type_code}")

        # Form factor (DIMM, SODIMM...)
        form_code = safe_int(stick, "FormFactor", 0)
        form = FORM_FACTOR_MAP.get(form_code, "Unknown")

        # Điện áp (đơn vị millivolt từ WMI, chuyển sang volt)
        voltage_mv = safe_int(stick, "ConfiguredVoltage", 0)
        voltage_v  = voltage_mv / 1000 if voltage_mv > 0 else None

        stick_info = {
            "capacity_gb":   capacity_gb,
            "manufacturer":  safe_get(stick, "Manufacturer", "N/A").strip(),
            "part_number":   safe_get(stick, "PartNumber",   "N/A").strip(),
            "serial":        safe_get(stick, "SerialNumber", "N/A").strip(),
            "speed_mhz":     speed_mhz,
            "memory_type":   mem_type,
            "form_factor":   form,
            "slot":          safe_get(stick, "DeviceLocator", "N/A").strip(),
            "bank":          safe_get(stick, "BankLabel",     "N/A").strip(),
            "voltage_v":     voltage_v,
            "data_width_bit": safe_int(stick, "DataWidth", 0),
        }
        sticks.append(stick_info)

    result["sticks"]     = sticks
    result["slots_used"] = len(sticks)  # Số thanh có mặt = slots đang dùng

    # Nếu slots_total chưa có (WMI trả 0), ước tính từ số thanh
    if result["slots_total"] == 0:
        result["slots_total"] = max(len(sticks), 2)

    return result
