"""
collectors/battery_collector.py
Thu thập thông tin pin laptop: dung lượng thiết kế vs hiện tại (Wear Level),
số chu kỳ sạc, % sạc hiện tại, tình trạng (Good/Weak/Bad).

Nếu là máy bàn (không có pin) → trả về {'present': False}.

API sử dụng:
  - WMI Win32_Battery: thông tin pin cơ bản
  - WMI BatteryStaticData (root/wmi): dung lượng thiết kế, số chu kỳ
  - WMI BatteryFullChargedCapacity (root/wmi): dung lượng sạc đầy hiện tại
  - WMI BatteryStatus (root/wmi): trạng thái sạc hiện tại
  - PowerShell POWERCFG: fallback nếu WMI không có đủ dữ liệu
"""
from __future__ import annotations

import subprocess
import re
from typing import Dict, Any, Optional

from utils.wmi_helper import wmi_query, wmi_first, safe_get


def _run_powershell(cmd: str, timeout: int = 10) -> str:
    """Chạy lệnh PowerShell và trả về output string."""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _get_battery_report_data() -> Dict[str, int]:
    """
    Lấy dung lượng pin từ POWERCFG /BATTERYREPORT.
    Đây là nguồn chính xác nhất cho DesignCapacity và FullChargeCapacity.

    Chạy: powercfg /batteryreport /output <temp_path>
    Parse file XML output để lấy số liệu.
    Trả về dict {design_capacity_mwh, full_charge_mwh}
    """
    import tempfile, os
    result = {}

    try:
        tmp_file = os.path.join(tempfile.gettempdir(), "CheckSysHealth_batt.xml")
        subprocess.run(
            ["powercfg", "/batteryreport", "/output", tmp_file, "/xml"],
            capture_output=True, timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW
        )

        if not os.path.exists(tmp_file):
            return result

        with open(tmp_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        # Parse DesignCapacity từ XML
        m = re.search(r"<DesignCapacity>(\d+)</DesignCapacity>", content)
        if m:
            result["design_capacity_mwh"] = int(m.group(1))

        # Parse FullChargeCapacity
        m = re.search(r"<FullChargeCapacity>(\d+)</FullChargeCapacity>", content)
        if m:
            result["full_charge_mwh"] = int(m.group(1))

        # Parse CycleCount
        m = re.search(r"<CycleCount>(\d+)</CycleCount>", content)
        if m:
            result["cycle_count"] = int(m.group(1))

        # Dọn file tạm
        try:
            os.remove(tmp_file)
        except Exception:
            pass

    except Exception:
        pass

    return result


def collect() -> Dict[str, Any]:
    """
    Thu thập thông tin pin laptop.

    Returns:
        Dict với:
          present: bool (False nếu không có pin)
          charge_pct: % pin hiện tại
          is_charging: bool
          design_capacity_mwh: dung lượng thiết kế (mWh)
          full_charge_mwh: dung lượng sạc đầy hiện tại (mWh)
          wear_level_pct: % còn lại so với thiết kế (100% = mới, <80% = yếu)
          cycle_count: số lần sạc
          status: "Good" / "Weak" / "Bad"
          status_color: "good" / "warn" / "danger"
    """
    result: Dict[str, Any] = {
        "present":             False,
        "charge_pct":          0,
        "is_charging":         False,
        "design_capacity_mwh": 0,
        "full_charge_mwh":     0,
        "wear_level_pct":      100,
        "cycle_count":         None,
        "status":              "N/A",
        "status_color":        "unknown",
        "name":                "N/A",
    }

    # ─── Kiểm tra pin có tồn tại không (Win32_Battery) ──────────────────────
    batteries = wmi_query(r"root\cimv2", "SELECT * FROM Win32_Battery")
    if not batteries:
        # Không có pin → máy bàn hoặc pin đã tháo ra
        result["present"] = False
        return result

    result["present"] = True
    batt = batteries[0]

    # Tên pin
    result["name"] = safe_get(batt, "Name", "Battery").strip()

    # % pin hiện tại
    charge_pct = safe_get(batt, "EstimatedChargeRemaining", 0)
    result["charge_pct"] = int(charge_pct) if charge_pct else 0

    # Trạng thái sạc (BatteryStatus):
    # 1=Discharging, 2=AC power, 3=Fully charged, 4=Low, 5=Critical, 6=Charging
    batt_status = int(safe_get(batt, "BatteryStatus", 1))
    result["is_charging"] = batt_status in {2, 3, 6}

    # ─── Dung lượng từ WMI root\wmi ──────────────────────────────────────────
    # BatteryStaticData chứa DesignedCapacity (mWh)
    static_data = wmi_first(r"root\wmi",
                            "SELECT * FROM BatteryStaticData")
    if static_data:
        design = safe_get(static_data, "DesignedCapacity", 0)
        if design and int(design) > 0:
            result["design_capacity_mwh"] = int(design)

        cycle = safe_get(static_data, "CycleCount", None)
        if cycle is not None:
            result["cycle_count"] = int(cycle)

    # BatteryFullChargedCapacity chứa FullChargedCapacity (mWh)
    full_cap_data = wmi_first(r"root\wmi",
                              "SELECT * FROM BatteryFullChargedCapacity")
    if full_cap_data:
        full = safe_get(full_cap_data, "FullChargedCapacity", 0)
        if full and int(full) > 0:
            result["full_charge_mwh"] = int(full)

    # ─── Fallback: POWERCFG nếu WMI không có đủ dữ liệu ────────────────────
    if result["design_capacity_mwh"] == 0 or result["full_charge_mwh"] == 0:
        report = _get_battery_report_data()
        if report.get("design_capacity_mwh"):
            result["design_capacity_mwh"] = report["design_capacity_mwh"]
        if report.get("full_charge_mwh"):
            result["full_charge_mwh"] = report["full_charge_mwh"]
        if report.get("cycle_count") and result["cycle_count"] is None:
            result["cycle_count"] = report["cycle_count"]

    # ─── Tính Wear Level % ───────────────────────────────────────────────────
    if result["design_capacity_mwh"] > 0 and result["full_charge_mwh"] > 0:
        wear_pct = (result["full_charge_mwh"] / result["design_capacity_mwh"]) * 100
        result["wear_level_pct"] = round(min(wear_pct, 100), 1)
    else:
        result["wear_level_pct"] = None  # Không tính được

    # ─── Phân loại tình trạng pin ────────────────────────────────────────────
    wear = result.get("wear_level_pct")
    if wear is None:
        result["status"]       = "Unknown"
        result["status_color"] = "unknown"
    elif wear >= 80:
        result["status"]       = "Good"
        result["status_color"] = "good"
    elif wear >= 50:
        result["status"]       = "Weak"
        result["status_color"] = "warn"
    else:
        result["status"]       = "Bad"
        result["status_color"] = "danger"

    return result
