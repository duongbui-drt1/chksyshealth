"""
tools/cdi_manager.py
Trình thu thập dữ liệu SMART gốc (Native WMI Storage SMART).
Thay thế hoàn toàn cơ chế chạy file exe ngoài và clipboard (/CopyExit)
bằng truy vấn trực tiếp vào Windows Storage API (root/Microsoft/Windows/Storage),
giúp ứng dụng chạy siêu nhanh, ổn định 100% và không bao giờ bị văng/crash.
"""
from __future__ import annotations

import sys
from typing import Dict, Any, List, Optional
from utils.progress import print_step, print_ok, print_warn
from utils.wmi_helper import wmi_query, safe_get


def get_smart_data(is_online: bool = False) -> List[Dict[str, Any]]:
    """
    Thu thập dữ liệu SMART từ WMI namespace root/Microsoft/Windows/Storage
    (MSFT_PhysicalDisk và MSFT_StorageReliabilityCounter).

    Returns:
        List các dict SMART data theo từng ổ đĩa.
    """
    print_step("Đọc SMART data từ Windows Storage API (Native WMI)")
    drives: List[Dict[str, Any]] = []

    try:
        # 1. Lấy danh sách ổ đĩa vật lý từ Storage namespace
        physical_disks = wmi_query(r"root\Microsoft\Windows\Storage", "SELECT * FROM MSFT_PhysicalDisk")
        if not physical_disks:
            print_warn("Không tìm thấy MSFT_PhysicalDisk trong WMI Storage")
            return drives

        # 2. Lấy bộ đếm độ tin cậy (Nhiệt độ, Wear Level, Power On Hours, Errors)
        counters = wmi_query(r"root\Microsoft\Windows\Storage", "SELECT * FROM MSFT_StorageReliabilityCounter")
        counter_by_devid: Dict[str, Any] = {}
        for c in counters:
            dev_id = str(safe_get(c, "DeviceId", "")).strip()
            if dev_id:
                counter_by_devid[dev_id] = c

        for pdisk in physical_disks:
            try:
                model = str(safe_get(pdisk, "FriendlyName", "Unknown Drive")).strip()
                if not model or model == "Unknown Drive":
                    continue

                dev_id = str(safe_get(pdisk, "DeviceId", "")).strip()
                serial = str(safe_get(pdisk, "SerialNumber", "N/A")).strip()
                size_bytes = int(safe_get(pdisk, "Size", 0))
                size_gb = round(size_bytes / (1024**3), 2)

                # BusType: 17=NVMe, 11=SATA, 7=USB, 8=RAID, 10=SAS
                bus_type_raw = int(safe_get(pdisk, "BusType", 0))
                bus_map = {17: "NVMe", 11: "SATA", 7: "USB", 8: "RAID", 10: "SAS"}
                interface = bus_map.get(bus_type_raw, "Unknown")

                # HealthStatus: 0=Healthy, 1=Warning, 2=Unhealthy, 5=Unknown
                health_raw = int(safe_get(pdisk, "HealthStatus", 5))
                if health_raw == 0:
                    health_status = "Good"
                    health_pct = 100
                elif health_raw == 1:
                    health_status = "Caution"
                    health_pct = 70
                elif health_raw == 2:
                    health_status = "Bad"
                    health_pct = 20
                else:
                    health_status = "Unknown"
                    health_pct = 100

                drive_dict: Dict[str, Any] = {
                    "model": model,
                    "serial": serial,
                    "size_gb": size_gb,
                    "interface": interface,
                    "health_status": health_status,
                    "health_pct": health_pct,
                }

                # Kết hợp dữ liệu từ MSFT_StorageReliabilityCounter
                if dev_id in counter_by_devid:
                    cnt = counter_by_devid[dev_id]
                    # Nhiệt độ
                    temp = safe_get(cnt, "Temperature", None)
                    if temp is not None and int(temp) > 0:
                        drive_dict["temperature_c"] = int(temp)

                    # Wear Level (%) -> chuyển thành Health Pct nếu là NVMe/SSD
                    wear = safe_get(cnt, "Wear", None)
                    if wear is not None and int(wear) <= 100:
                        wear_val = int(wear)
                        drive_dict["wear_level_pct"] = wear_val
                        # Với SSD/NVMe: Health% = 100 - Wear%
                        calc_health = max(1, 100 - wear_val)
                        drive_dict["health_pct"] = calc_health
                        if calc_health < 30:
                            drive_dict["health_status"] = "Bad"
                        elif calc_health < 70:
                            drive_dict["health_status"] = "Caution"
                        else:
                            drive_dict["health_status"] = "Good"

                    # Power On Hours
                    poh = safe_get(cnt, "PowerOnHours", None)
                    if poh is not None and int(poh) >= 0:
                        drive_dict["power_on_hours"] = int(poh)

                    # Read/Write errors
                    read_err = int(safe_get(cnt, "ReadErrorsUncorrected", 0))
                    write_err = int(safe_get(cnt, "WriteErrorsUncorrected", 0))
                    if read_err + write_err > 0 and drive_dict["health_status"] == "Good":
                        drive_dict["health_status"] = "Caution"
                        drive_dict["health_pct"] = min(drive_dict["health_pct"], 80)

                drives.append(drive_dict)
            except Exception:
                continue

        if drives:
            print_ok(f"WMI Storage: đọc được {len(drives)} ổ đĩa ({', '.join(d['model'] for d in drives[:2])})")
        else:
            print_warn("WMI Storage: không đọc được thông tin ổ đĩa nào")

    except Exception as exc:
        print_warn(f"Lỗi truy vấn WMI Storage: {exc}")

    return drives
