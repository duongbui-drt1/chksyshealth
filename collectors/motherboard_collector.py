"""
collectors/motherboard_collector.py
Thu thập thông tin Mainboard: hãng, model, serial, BIOS version/date.
Kiểm tra SLIC OEM ID từ BIOS (dùng để so sánh khi phát hiện crack SLIC giả).

API sử dụng:
  - WMI Win32_BaseBoard: thông tin mainboard
  - WMI Win32_BIOS: thông tin BIOS
  - WMI SoftwareLicensingService: đọc SLIC OEM ID
"""
from __future__ import annotations

from typing import Dict, Any
from utils.wmi_helper import wmi_query, wmi_first, safe_get


def collect() -> Dict[str, Any]:
    """
    Thu thập thông tin mainboard và BIOS.

    Returns:
        Dict với các key:
          mb_manufacturer, mb_model, mb_serial, mb_version,
          bios_manufacturer, bios_version, bios_date, bios_serial,
          bios_smbios_version, slic_oem_id (dùng cho crack detection)
    """
    result: Dict[str, Any] = {
        "mb_manufacturer":    "N/A",
        "mb_model":           "N/A",
        "mb_serial":          "N/A",
        "mb_version":         "N/A",
        "bios_manufacturer":  "N/A",
        "bios_version":       "N/A",
        "bios_date":          "N/A",
        "bios_serial":        "N/A",
        "bios_smbios_version": "N/A",
        "slic_oem_id":        None,  # OEM ID từ bảng SLIC trong BIOS
        "system_manufacturer": "N/A",  # Hãng máy tính (Dell, HP, Asus...)
        "system_model":        "N/A",  # Model máy tính
    }

    # ─── Mainboard info từ Win32_BaseBoard ───────────────────────────────────
    board = wmi_first(r"root\cimv2", "SELECT * FROM Win32_BaseBoard")
    if board:
        result["mb_manufacturer"] = safe_get(board, "Manufacturer", "N/A").strip()
        result["mb_model"]        = safe_get(board, "Product", "N/A").strip()
        result["mb_serial"]       = safe_get(board, "SerialNumber", "N/A").strip()
        result["mb_version"]      = safe_get(board, "Version", "N/A").strip()

    # ─── BIOS info từ Win32_BIOS ──────────────────────────────────────────────
    bios = wmi_first(r"root\cimv2", "SELECT * FROM Win32_BIOS")
    if bios:
        result["bios_manufacturer"] = safe_get(bios, "Manufacturer", "N/A").strip()
        result["bios_version"]      = safe_get(bios, "SMBIOSBIOSVersion", "N/A").strip()
        result["bios_serial"]       = safe_get(bios, "SerialNumber", "N/A").strip()
        result["bios_smbios_version"] = (
            f"{safe_get(bios, 'SMBIOSMajorVersion', '?')}."
            f"{safe_get(bios, 'SMBIOSMinorVersion', '?')}"
        )

        # Ngày phát hành BIOS — format WMI: "20230101000000.000000+000"
        bios_date_raw = safe_get(bios, "ReleaseDate", "")
        if bios_date_raw and len(bios_date_raw) >= 8:
            y = bios_date_raw[0:4]
            m = bios_date_raw[4:6]
            d = bios_date_raw[6:8]
            result["bios_date"] = f"{d}/{m}/{y}"
        else:
            result["bios_date"] = "N/A"

    # ─── Thông tin hệ thống (hãng máy, model) ────────────────────────────────
    system = wmi_first(r"root\cimv2", "SELECT * FROM Win32_ComputerSystem")
    if system:
        result["system_manufacturer"] = safe_get(system, "Manufacturer", "N/A").strip()
        result["system_model"]        = safe_get(system, "Model", "N/A").strip()

    # ─── SLIC OEM ID từ SoftwareLicensingService ─────────────────────────────
    # Bảng SLIC trong BIOS chứa OEM ID dùng cho OEM activation.
    # Nếu SLIC báo một hãng nhưng máy thực tế là hãng khác → dấu hiệu crack SLIC.
    sls = wmi_first(r"root\cimv2", "SELECT * FROM SoftwareLicensingService")
    if sls:
        # OA2 SLIC OEM ID — thường là tên hãng: "Microsoft", "DELL", "HP"...
        oem_id = safe_get(sls, "OA2xBIOSMarkerMinorVersion", None)
        if oem_id:
            result["slic_oem_id"] = str(oem_id)

        # Tên BIOS OEM từ key khác (tùy version Windows)
        oem_key = safe_get(sls, "KeyManagementServiceMachine", None)
        if oem_key and oem_key != "N/A":
            result["kms_machine"] = str(oem_key)

    return result
