"""
collectors/media_collector.py
Thu thập thông tin Driver thiết bị Âm thanh (Audio) và Bluetooth (BLE) trên hệ thống.

Sử dụng WMI Win32_PnPSignedDriver để trích xuất đầy đủ thông số Driver chính xác:
  - Tên thiết bị (DeviceName)
  - Hãng sản xuất (Manufacturer)
  - Phiên bản Driver (DriverVersion)
  - Ngày phát hành Driver (DriverDate)
"""
from __future__ import annotations

from typing import Dict, Any, List
from utils.wmi_helper import wmi_query, safe_get


def _format_wmi_date(date_str: str) -> str:
    """Chuyển đổi định dạng ngày WMI (e.g., 20210519000000.******) thành DD/MM/YYYY."""
    if not date_str or len(date_str) < 8:
        return "N/A"
    try:
        y = date_str[0:4]
        m = date_str[4:6]
        d = date_str[6:8]
        return f"{d}/{m}/{y}"
    except Exception:
        return "N/A"


def collect() -> Dict[str, Any]:
    """
    Thu thập danh sách thiết bị âm thanh và bluetooth có kèm Driver ký số.
    """
    audio_devices: List[Dict[str, Any]] = []
    bt_devices: List[Dict[str, Any]] = []

    # Query toàn bộ Driver đã đăng ký trên hệ thống
    drivers = wmi_query(r"root\cimv2", "SELECT * FROM Win32_PnPSignedDriver")

    for drv in drivers:
        guid = safe_get(drv, "ClassGuid", "").lower()
        if not guid:
            continue

        name = safe_get(drv, "DeviceName", "").strip()
        if not name:
            continue

        manufacturer = safe_get(drv, "Manufacturer", "Unknown").strip()
        version = safe_get(drv, "DriverVersion", "N/A").strip()
        date_raw = safe_get(drv, "DriverDate", "")
        driver_date = _format_wmi_date(date_raw)
        device_id = safe_get(drv, "DeviceID", "N/A").strip()

        device_info = {
            "name": name,
            "manufacturer": manufacturer,
            "version": version,
            "date": driver_date,
            "device_id": device_id
        }

        # Class GUID cho Thiết bị âm thanh (Sound, video and game controllers)
        if "4d36e96c-e325-11ce-bfc1-08002be10318" in guid:
            # Lọc bỏ một số bộ ảo không cần thiết nếu danh sách quá dài, nhưng ưu tiên giữ lại để kiểm tra
            audio_devices.append(device_info)

        # Class GUID cho Thiết bị Bluetooth
        elif "e0cbf06c-cd8b-4647-bb8a-263b43f0f974" in guid:
            bt_devices.append(device_info)

    # Sắp xếp thiết bị để các hãng thứ 3 (Intel, Realtek, Qualcomm, Broadcom...) lên trước Microsoft
    def sort_key(d):
        m = d["manufacturer"].lower()
        if "microsoft" in m:
            return 1
        if "unknown" in m:
            return 2
        return 0

    audio_devices.sort(key=sort_key)
    bt_devices.sort(key=sort_key)

    return {
        "audio": audio_devices,
        "bluetooth": bt_devices
    }
