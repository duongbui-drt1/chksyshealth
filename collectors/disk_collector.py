"""
collectors/disk_collector.py
Thu thập thông tin ổ đĩa: model, dung lượng, loại (NVMe/SATA),
SMART data (health%, bad sector, POH, TBW), nhiệt độ.

Ưu tiên dữ liệu từ CrystalDiskInfo (chi tiết hơn).
Fallback sang WMI MSStorageDriver_ATAPISmartData nếu CDI không có.

API sử dụng:
  - WMI Win32_DiskDrive: thông tin cơ bản ổ đĩa
  - WMI root/wmi MSStorageDriver_ATAPISmartData: raw SMART data (SATA/IDE)
  - WMI Win32_LogicalDisk: thông tin partition và không gian trống
  - psutil.disk_usage(): không gian trống thực tế
  - CrystalDiskInfo output (nếu có): SMART chi tiết
"""
from __future__ import annotations

import re
import struct
from typing import Dict, Any, List, Optional

import psutil
from utils.wmi_helper import wmi_query, safe_get

# ─── SMART Attribute IDs quan trọng ──────────────────────────────────────────
SMART_ATTR = {
    0x01: "Raw Read Error Rate",
    0x03: "Spin Up Time",
    0x04: "Start/Stop Count",
    0x05: "Reallocated Sectors Count",     # Bad sector chính
    0x07: "Seek Error Rate",
    0x09: "Power On Hours",                # Số giờ hoạt động
    0x0A: "Spin Retry Count",
    0x0C: "Power Cycle Count",
    0xBB: "Reported Uncorrectable Errors",
    0xBC: "Command Timeout",
    0xC2: "Temperature",                   # Nhiệt độ HDD
    0xC5: "Current Pending Sector Count",  # Sector đang chờ realloc
    0xC6: "Offline Uncorrectable",         # Bad sector offline
    0xC7: "Ultra DMA CRC Error Count",
    0xF0: "Head Flying Hours",
    0xF1: "Total LBAs Written",            # TBW của SSD (sectors written)
    0xF2: "Total LBAs Read",
}

# SMART attributes liên quan đến bad sector (bất kỳ giá trị raw > 0 = cảnh báo)
CRITICAL_ATTRS = {0x05, 0xBB, 0xC5, 0xC6}


def _parse_smart_raw_data(raw_data_array) -> Dict[int, Dict]:
    """
    Parse raw SMART data từ WMI MSStorageDriver_ATAPISmartData.
    Format: byte array, mỗi attribute chiếm 12 bytes, bắt đầu từ byte index 2.

    Cấu trúc 1 attribute (12 bytes):
      [0]    : Attribute ID (0x00 = unused)
      [1-2]  : Flags (little-endian)
      [3]    : Current value (normalized, 0-255, 100 = mới)
      [4]    : Worst value (giá trị xấu nhất từ trước đến nay)
      [5-10] : Raw value (6 bytes, little-endian) — giá trị thực
      [11]   : Reserved

    Returns:
        Dict { attr_id: { current, worst, raw, name } }
    """
    if not raw_data_array:
        return {}

    attrs = {}
    # Chuyển WMI array sang bytes
    try:
        data = bytes(raw_data_array)
    except Exception:
        return {}

    # Skip 2 bytes đầu (version), mỗi attribute 12 bytes
    for offset in range(2, len(data) - 11, 12):
        attr_id = data[offset]
        if attr_id == 0:
            continue  # Slot trống

        current = data[offset + 3]
        worst   = data[offset + 4]
        # Raw value: 6 bytes little-endian
        raw = int.from_bytes(data[offset + 5:offset + 11], byteorder="little")

        attrs[attr_id] = {
            "id":      attr_id,
            "name":    SMART_ATTR.get(attr_id, f"Attr {attr_id:#04x}"),
            "current": current,
            "worst":   worst,
            "raw":     raw,
        }

    return attrs


def _detect_interface(pnp_device_id: str) -> str:
    """
    Phát hiện loại giao tiếp ổ đĩa từ PNPDeviceID.
    NVMe: PNPDeviceID chứa 'NVMe' hoặc 'STORAGE\\DISK'
    SATA: chứa 'IDE', 'AHCI', 'SCSI'
    USB: chứa 'USB'
    """
    if not pnp_device_id:
        return "Unknown"
    pid = pnp_device_id.upper()
    if "NVME" in pid:
        return "NVMe"
    elif "USB" in pid:
        return "USB"
    elif "IDE" in pid or "AHCI" in pid:
        return "SATA"
    elif "SCSI" in pid:
        return "SCSI"
    elif "RAID" in pid:
        return "RAID"
    return "Unknown"


def _calculate_health_from_smart(smart_attrs: Dict) -> int:
    """
    Tính % health từ SMART attributes.
    Logic đơn giản: nếu có bad sector → giảm health, nếu POH cao → giảm nhẹ.
    Trả về 0-100.
    """
    health = 100

    # Bad sector (reallocated) — mỗi sector trừ 10%
    bad_sectors = smart_attrs.get(0x05, {}).get("raw", 0)
    if bad_sectors > 0:
        health -= min(bad_sectors * 10, 50)

    # Current pending sectors — chưa reallocated nhưng đang chờ
    pending = smart_attrs.get(0xC5, {}).get("raw", 0)
    if pending > 0:
        health -= min(pending * 5, 30)

    # Uncorrectable errors — nghiêm trọng
    uncorr = smart_attrs.get(0xC6, {}).get("raw", 0)
    if uncorr > 0:
        health -= min(uncorr * 15, 40)

    # Reported uncorrectable (NVMe/SSD)
    reported = smart_attrs.get(0xBB, {}).get("raw", 0)
    if reported > 0:
        health -= min(reported * 5, 30)

    return max(0, min(100, health))


def _get_disk_usage() -> Dict[str, Any]:
    """Lấy thông tin sử dụng từng partition."""
    partitions = {}
    try:
        for part in psutil.disk_partitions(all=False):
            try:
                usage = psutil.disk_usage(part.mountpoint)
                partitions[part.device.replace("\\", "").replace(":", "")] = {
                    "mountpoint": part.mountpoint,
                    "fstype":     part.fstype,
                    "total_gb":   round(usage.total / 1024**3, 2),
                    "used_gb":    round(usage.used  / 1024**3, 2),
                    "free_gb":    round(usage.free  / 1024**3, 2),
                    "used_pct":   round(usage.percent, 1),
                }
            except Exception:
                continue
    except Exception:
        pass
    return partitions


def collect(cdi_data: List[Dict] = None) -> Dict[str, Any]:
    """
    Thu thập thông tin tất cả ổ đĩa.

    Args:
        cdi_data: List SMART data từ CrystalDiskInfo (nếu có).
                  Nếu None → dùng WMI fallback.

    Returns:
        Dict với:
          drives: list thông tin từng ổ
          partitions: dict thông tin partition
    """
    cdi_data = cdi_data or []

    # Tạo index CDI data theo model name để tra cứu nhanh
    cdi_by_model: Dict[str, Dict] = {}
    for d in cdi_data:
        model_key = d.get("model", "").lower().strip()
        if model_key:
            cdi_by_model[model_key] = d

    drives_result: List[Dict] = []

    # ─── Lấy danh sách ổ đĩa từ WMI ─────────────────────────────────────────
    wmi_drives = wmi_query(r"root\cimv2", "SELECT * FROM Win32_DiskDrive")

    # ─── Lấy SMART raw data từ WMI (chỉ hiệu quả với SATA) ──────────────────
    smart_by_instance: Dict[str, Dict] = {}
    try:
        smart_raw_list = wmi_query(r"root\wmi", "SELECT * FROM MSStorageDriver_ATAPISmartData")
        for s in smart_raw_list:
            inst = safe_get(s, "InstanceName", "").lower()
            raw  = safe_get(s, "VendorSpecific", None)
            if raw:
                smart_by_instance[inst] = _parse_smart_raw_data(raw)
    except Exception:
        pass

    for drive in wmi_drives:
        # Thông tin cơ bản
        model      = safe_get(drive, "Model",        "Unknown Drive").strip()
        size_bytes = int(safe_get(drive, "Size", 0))
        size_gb    = round(size_bytes / 1024**3, 2)
        pnp_id     = safe_get(drive, "PNPDeviceID",  "").strip()
        interface  = _detect_interface(pnp_id)
        serial     = safe_get(drive, "SerialNumber", "N/A").strip()
        firmware   = safe_get(drive, "FirmwareRevision", "N/A").strip()
        status     = safe_get(drive, "Status",       "Unknown").strip()

        drive_info: Dict[str, Any] = {
            "model":          model,
            "size_gb":        size_gb,
            "interface":      interface,
            "serial":         serial,
            "firmware":       firmware,
            "status":         status,
            "health_pct":     None,
            "health_status":  "Unknown",
            "temperature_c":  None,
            "power_on_hours": None,
            "power_on_count": None,
            "tbw_gb":         None,
            "bad_sectors":    0,
            "smart_attrs":    [],
            "source":         "WMI",  # hoặc "CrystalDiskInfo"
        }

        # ─── Ưu tiên dùng CDI data nếu có ───────────────────────────────────
        cdi_match = None
        for cdi_model_key, cdi_entry in cdi_by_model.items():
            # So khớp mềm: nếu model WMI chứa model CDI hoặc ngược lại
            model_lower = model.lower()
            if cdi_model_key in model_lower or model_lower in cdi_model_key:
                cdi_match = cdi_entry
                break

        if cdi_match:
            drive_info["health_pct"]     = cdi_match.get("health_pct")
            drive_info["health_status"]  = cdi_match.get("health_status", "Unknown")
            drive_info["temperature_c"]  = cdi_match.get("temperature_c")
            drive_info["power_on_hours"] = cdi_match.get("power_on_hours")
            drive_info["power_on_count"] = cdi_match.get("power_on_count")
            drive_info["tbw_gb"]         = cdi_match.get("tbw_gb")
            drive_info["source"]         = "CrystalDiskInfo"
            if cdi_match.get("interface"):
                drive_info["interface"]  = cdi_match["interface"]
        else:
            # ─── Fallback: WMI SMART data ────────────────────────────────────
            # Tìm SMART data khớp với drive (theo InstanceName có chứa serial)
            matched_smart = {}
            for inst_key, smart_dict in smart_by_instance.items():
                if serial.lower() in inst_key or model.lower()[:8] in inst_key:
                    matched_smart = smart_dict
                    break

            if not matched_smart and smart_by_instance:
                # Nếu không khớp được, lấy theo thứ tự index
                idx = len(drives_result)
                keys = list(smart_by_instance.keys())
                if idx < len(keys):
                    matched_smart = smart_by_instance[keys[idx]]

            if matched_smart:
                # Nhiệt độ từ attribute 0xC2
                temp_attr = matched_smart.get(0xC2, {})
                if temp_attr.get("raw"):
                    # Raw temperature: byte thấp nhất = nhiệt độ
                    drive_info["temperature_c"] = temp_attr["raw"] & 0xFF

                # Số giờ hoạt động từ attribute 0x09
                poh_attr = matched_smart.get(0x09, {})
                if poh_attr.get("raw"):
                    drive_info["power_on_hours"] = poh_attr["raw"]

                # Bad sectors: attribute 0x05 (reallocated)
                bad_attr = matched_smart.get(0x05, {})
                drive_info["bad_sectors"] = bad_attr.get("raw", 0)

                # TBW cho SSD: attribute 0xF1
                tbw_attr = matched_smart.get(0xF1, {})
                if tbw_attr.get("raw"):
                    # F1 raw = số LBA đã ghi × 512 bytes / 1024^3 = GB
                    lba_written = tbw_attr["raw"]
                    drive_info["tbw_gb"] = round(lba_written * 512 / 1024**3, 1)

                # Tính health %
                drive_info["health_pct"] = _calculate_health_from_smart(matched_smart)
                drive_info["bad_sectors"]  = (
                    matched_smart.get(0x05, {}).get("raw", 0) +
                    matched_smart.get(0xC5, {}).get("raw", 0)
                )

                # Convert SMART attrs thành list để render trong report
                drive_info["smart_attrs"] = [
                    v for v in matched_smart.values()
                    if v["id"] in SMART_ATTR
                ]

            # Status từ WMI
            if status == "OK":
                drive_info["health_status"] = "Good"
                if drive_info["health_pct"] is None:
                    drive_info["health_pct"] = 100
            else:
                drive_info["health_status"] = "Caution"
                if drive_info["health_pct"] is None:
                    drive_info["health_pct"] = 50

        # Xác định màu health
        hp = drive_info.get("health_pct")
        if hp is not None:
            if hp >= 80:
                drive_info["health_color"] = "good"
            elif hp >= 50:
                drive_info["health_color"] = "warn"
            else:
                drive_info["health_color"] = "danger"
        else:
            drive_info["health_color"] = "unknown"

        drives_result.append(drive_info)

    return {
        "drives":     drives_result,
        "partitions": _get_disk_usage(),
    }
