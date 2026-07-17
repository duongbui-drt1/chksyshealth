r"""
collectors/license_collector.py
Kiểm tra bản quyền phần mềm và phát hiện dấu hiệu crack Windows.

=== CÁC PHƯƠNG PHÁP PHÁT HIỆN CRACK (5 nhóm) ===

1. HOSTS FILE KMS HIJACKING
   Đọc C:/Windows/System32/drivers/etc/hosts
   Tìm dòng trỏ domain Microsoft KMS về địa chỉ không phải Microsoft

2. SCHEDULED TASK KMS AUTOMATION
   Liệt kê tất cả Scheduled Tasks
   Cờ task có tên/command nghi ngờ (KMS, activat, loader...)
   Kiểm tra task không có publisher hợp lệ và chạy từ %AppData%/%Temp%

3. PORT 1688 LISTENER
   Kiểm tra port 1688 (port chuẩn KMS) có process đang lắng nghe trên localhost

4. SPP FILE INTEGRITY
   Kiểm tra chữ ký số Authenticode của sppsvc.exe, SppExtComObj.dll, slc.dll

5. REGISTRY KMS TAMPERING
   Kiểm tra KeyManagementServiceName / KeyManagementServicePort trong registry

6. RUN KEYS CRACK TOOLS
   Kiểm tra các mục Run/RunOnce trong registry khởi động cùng Windows

7. KNOWN CRACK FILES
   Kiểm tra sự tồn tại của các file crack nổi tiếng (KMSpico, AAct, RemoveWAT...)

8. CRACK SERVICES
   Tìm service liên quan KMS emulator

9. DRIVER SIGNING
   Kiểm tra driver không có chữ ký số hợp lệ

10. FIREWALL BYPASS RULES
    Tìm firewall rule cho phép port 1688 (KMS) từ bên ngoài

API sử dụng:
  - WMI SoftwareLicensingProduct: trạng thái activation Windows
  - Registry (read-only): HKLM/SOFTWARE/Microsoft/Windows NT/...
  - Windows Task Scheduler COM: liệt kê scheduled tasks
  - psutil.net_connections(): kiểm tra port đang mở
  - subprocess: chạy sigcheck / Get-AuthenticodeSignature
"""
from __future__ import annotations

import os
import re
import json
import socket
import hashlib
import subprocess
import winreg
import ctypes
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple

import psutil
from utils.wmi_helper import wmi_query, wmi_first, safe_get


# ─── Danh sách domain KMS Microsoft hợp lệ ──────────────────────────────────
# Nếu hosts file trỏ các domain này về IP khác → nghi ngờ KMS hijack
KMS_MICROSOFT_DOMAINS = [
    "kms.core.windows.net",
    "activation.sls.microsoft.com",
    "validation.sls.microsoft.com",
    "genuine.microsoft.com",
    "go.microsoft.com",
    "sls.microsoft.com",
    "wpa.microsoft.com",
    "crl.microsoft.com",
]

# Từ khóa trong tên scheduled task nghi ngờ
SUSPICIOUS_TASK_KEYWORDS = [
    "kms", "activate", "activator", "loader", "patch",
    "kmspico", "aact", "toolkit", "rearm", "reloader",
    "slmgr", "licensingscript", "wpa", "ospp", "autokms", "ohook", "c2r-r2v",
]

# Đường dẫn crack tool phổ biến cần kiểm tra
KNOWN_CRACK_PATHS = [
    # KMSpico
    r"%ProgramFiles%\KMSpico",
    r"%ProgramFiles(x86)%\KMSpico",
    r"%APPDATA%\KMSpico",
    r"%SystemRoot%\KMSpico",
    r"C:\KMSpico",
    # AAct
    r"%ProgramFiles%\AAct Network",
    r"%ProgramFiles(x86)%\AAct Network",
    r"%APPDATA%\AAct",
    # Microsoft Toolkit
    r"%APPDATA%\Microsoft Toolkit",
    r"%ProgramFiles%\Microsoft Toolkit",
    # KMS_VL_ALL & MAS / Ohook
    r"%SystemDrive%\KMS_VL_ALL",
    r"%ProgramData%\Microsoft\OfficeSoftwareProtectionPlatform\licenses\ohook",
    # Các file exe đặc trưng trong system32
    r"%SystemRoot%\system32\SECOH-QAD.exe",  # loader cũ
    r"%SystemRoot%\SECOH-QAD.exe",
]

# Tên service crack phổ biến
KNOWN_CRACK_SERVICES = [
    "kmservice", "kmspico", "autopico", "kmseldi",
    "mdl_kms", "kmsserver", "vlmcsd", "osppsvc_crack", "ohooksvc",
]

# Tên file crack phổ biến (kiểm tra trong %Temp%, %AppData%...)
KNOWN_CRACK_FILENAMES = [
    "kmspico.exe", "kmseldi.exe", "autopico.exe", "kmsservice.exe",
    "aact.exe", "aact_x64.exe", "aact network.exe",
    "microsoft_toolkit.exe", "microsoft toolkit.exe",
    "kms_vl_all.cmd", "activate.cmd",
    "removewat.exe", "wat.exe",
    "mdl.exe", "re-loader.exe",
    "ohook.dll", "c2r-r2v.exe", "sppc_hook.dll", "mas_activate.cmd",
]

# ─── WMI License status codes ────────────────────────────────────────────────
LICENSE_STATUS = {
    0: "Unlicensed",
    1: "Licensed",
    2: "OOB Grace Period",         # Out-of-Box grace (mới cài)
    3: "OOT Grace Period",         # Out-of-Tolerance grace (KMS hết hạn)
    4: "Non-Genuine Grace Period", # Phát hiện không genuine
    5: "Notification",             # Đang trong notification mode
    6: "Extended Grace Period",
}


# ─── PHẦN 1: Windows Activation ──────────────────────────────────────────────

def _get_windows_license() -> Dict[str, Any]:
    """
    Lấy trạng thái bản quyền Windows qua WMI SoftwareLicensingProduct.
    ApplicationId của Windows: {55c92734-d682-4d71-983e-d6ec3f16059f}
    """
    info: Dict[str, Any] = {
        "product_name":    "Windows",
        "activation_status": "Unknown",
        "license_type":    "Unknown",
        "product_id":      "N/A",
        "install_date":    "N/A",
        "build_number":    "N/A",
        "edition":         "N/A",
        "kms_server":      None,
        "kms_port":        None,
        "partial_key":     "N/A",
    }

    # ─── Thông tin OS từ registry ────────────────────────────────────────────
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\Windows NT\CurrentVersion",
                           access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            def reg_val(name, default="N/A"):
                try:
                    return winreg.QueryValueEx(key, name)[0]
                except Exception:
                    return default

            info["product_name"]  = reg_val("ProductName")
            info["edition"]       = reg_val("EditionID")
            info["build_number"]  = reg_val("CurrentBuildNumber")
            info["product_id"]    = reg_val("ProductId")

            # Chuẩn hóa Windows 11: trên build >= 22000, registry ProductName
            # thường vẫn báo "Windows 10 Pro" do tương thích của Microsoft
            try:
                build_int = int(info["build_number"])
                if build_int >= 22000 and "Windows 10" in str(info["product_name"]):
                    info["product_name"] = str(info["product_name"]).replace("Windows 10", "Windows 11")
            except (ValueError, TypeError):
                pass

            # Install date (Unix timestamp)
            install_ts = reg_val("InstallDate", 0)
            if install_ts and install_ts != "N/A":
                import datetime
                try:
                    dt = datetime.datetime.fromtimestamp(int(install_ts))
                    info["install_date"] = dt.strftime("%d/%m/%Y")
                except Exception:
                    pass
    except Exception:
        pass

    # ─── Trạng thái activation từ WMI SoftwareLicensingProduct ──────────────
    # Lọc theo ApplicationId của Windows và PartialProductKey != ""
    WINDOWS_APP_ID = "55c92734-d682-4d71-983e-d6ec3f16059f"
    wql = (
        "SELECT * FROM SoftwareLicensingProduct "
        f"WHERE ApplicationId='{WINDOWS_APP_ID}' "
        "AND PartialProductKey IS NOT NULL"
    )
    products = wmi_query(r"root\cimv2", wql)

    for prod in products:
        status_code = int(safe_get(prod, "LicenseStatus", 0))
        info["activation_status"] = LICENSE_STATUS.get(status_code, "Unknown")
        info["partial_key"]       = safe_get(prod, "PartialProductKey", "N/A")
        info["product_id"]        = safe_get(prod, "ProductKeyID", info["product_id"])

        # LicenseFamily cho biết loại license
        family = safe_get(prod, "LicenseFamily", "")
        channel = safe_get(prod, "ProductKeyChannel", "")
        if "OEM" in family.upper() or "OEM" in channel.upper():
            info["license_type"] = "OEM"
        elif "Volume" in family or "MAK" in channel or "KMS" in channel:
            info["license_type"] = "Volume/KMS"
        elif "Retail" in channel or "Retail" in family:
            info["license_type"] = "Retail"
        else:
            info["license_type"] = channel or family or "Unknown"

        # KMS server (nếu là KMS license)
        kms_machine = safe_get(prod, "KeyManagementServiceMachine", None)
        kms_port    = safe_get(prod, "KeyManagementServicePort",    None)
        if kms_machine and kms_machine != "N/A":
            info["kms_server"] = kms_machine
        if kms_port and kms_port != "N/A":
            info["kms_port"] = kms_port

        break  # Lấy product đầu tiên khớp

    return info


# ─── PHẦN 2: Microsoft Office License ────────────────────────────────────────

def _get_office_license() -> Dict[str, Any]:
    """Đọc thông tin bản quyền Microsoft Office từ OSPP (ospp.vbs / WMI) và ClickToRun Registry."""
    info: Dict[str, Any] = {
        "installed":   False,
        "product_name": "N/A",
        "version":     "N/A",
        "channel":     "N/A",
        "license_type": "N/A",
        "activation_status": "Unknown",
        "partial_key": "N/A",
        "kms_server":  None,
        "kms_port":    None,
        "error_desc":  "",
    }

    # 1. Thử đọc C2R config (Microsoft 365 / Office 2019/2021/2024)
    c2r = {}
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\ClickToRun\Configuration", access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            i = 0
            while True:
                try:
                    name, val, _ = winreg.EnumValue(k, i)
                    c2r[name] = val
                    i += 1
                except OSError:
                    break
    except Exception:
        pass

    if c2r:
        info["installed"]    = True
        info["product_name"] = c2r.get("ProductReleaseIds", "Microsoft Office").split(",")[0]
        info["version"]      = c2r.get("VersionToReport", c2r.get("ClientVersionToReport", "N/A"))
        
        # Bảng chuyển đổi GUID kênh ClickToRun sang tên thân thiện
        cdn_map = {
            "492350f6-3a01-4f97-b9c0-c7c6ddf67d60": "Current Channel (Retail)",
            "55336b82-a18d-4dd6-b5f6-9e5095c314a6": "Monthly Enterprise Channel",
            "7ffbc6bf-bc32-4f92-8982-f9dd17fd3114": "Semi-Annual Enterprise Channel",
            "64256afe-f5d9-4f86-8936-8840a6a4f5be": "Current Channel (Preview)",
            "f2e724c1-748f-4b47-8fb8-8e0d210e9208": "Beta Channel",
            "5440fd1f-7ecb-4221-8110-145efaa6372f": "Perpetual 2019/2021/2024 Enterprise",
        }
        raw_cdn = str(c2r.get("CDNBaseUrl", ""))
        raw_ch  = str(c2r.get("UpdateChannel", ""))
        
        found_ch = "N/A"
        for guid, name in cdn_map.items():
            if guid.lower() in raw_cdn.lower() or guid.lower() in raw_ch.lower():
                found_ch = name
                break
        if found_ch == "N/A":
            if raw_ch:
                found_ch = raw_ch.split("/")[-1] if "/" in raw_ch else raw_ch
            elif raw_cdn:
                clean = raw_cdn.replace("http://officecdn.microsoft.com/pr/", "").rstrip("/")
                found_ch = clean[:25]
        info["channel"] = found_ch

        license_ids = str(c2r.get("LicenseIds", ""))
        if "Subscription" in license_ids or "O365" in license_ids:
            info["license_type"] = "Subscription (Microsoft 365)"
        elif "Perpetual" in license_ids or "Retail" in license_ids or "Volume" in license_ids:
            if "Retail" in license_ids:
                info["license_type"] = "Retail"
            elif "Volume" in license_ids:
                info["license_type"] = "Volume"
            else:
                info["license_type"] = "Perpetual"
        else:
            info["license_type"] = "ClickToRun"

    # 2. Tìm và chạy cscript ospp.vbs /dstatus để lấy chính xác tình trạng & kênh kích hoạt Office
    ospp_paths = [
        Path(r"C:\Program Files\Microsoft Office\root\Office16\ospp.vbs"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\Office16\ospp.vbs"),
        Path(r"C:\Program Files\Microsoft Office\Office16\ospp.vbs"),
        Path(r"C:\Program Files (x86)\Microsoft Office\Office16\ospp.vbs"),
    ]
    for p in ospp_paths:
        if p.exists():
            try:
                res = subprocess.run(
                    ["cscript", "//nologo", str(p), "/dstatus"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=15, creationflags=subprocess.CREATE_NO_WINDOW
                )
                output = res.stdout
                for line in output.splitlines():
                    line_clean = line.strip()
                    if line_clean.startswith("LICENSE NAME:"):
                        name_val = line_clean.split(":", 1)[1].strip()
                        if not info["installed"]:
                            info["installed"] = True
                            info["product_name"] = name_val.split(",")[0].strip()
                        if "retail" in name_val.lower():
                            info["license_type"] = "Retail"
                        elif "volume" in name_val.lower() or "kms" in name_val.lower():
                            info["license_type"] = "Volume / KMS Client"
                        elif "subscription" in name_val.lower():
                            info["license_type"] = "Subscription"
                    elif line_clean.startswith("LICENSE DESCRIPTION:"):
                        desc_val = line_clean.split(":", 1)[1].strip()
                        if "channel" in desc_val.lower():
                            if info["channel"] == "N/A" or "-" in info["channel"]:
                                info["channel"] = desc_val.split(",")[-1].strip()
                        if "volume_kmsclient" in desc_val.lower():
                            info["license_type"] = "Volume / KMS Client"
                            if info["channel"] == "N/A":
                                info["channel"] = "Volume Channel (KMS)"
                        elif "retail" in desc_val.lower():
                            if info["license_type"] == "N/A":
                                info["license_type"] = "Retail"
                    elif line_clean.startswith("LICENSE STATUS:"):
                        status_val = line_clean.split(":", 1)[1].strip().replace("-", "").strip()
                        if "LICENSED" in status_val.upper():
                            info["activation_status"] = "Licensed"
                        elif "NOTIFICATIONS" in status_val.upper():
                            info["activation_status"] = "Notification (Expired/Grace Ended)"
                        elif "OOB_GRACE" in status_val.upper():
                            info["activation_status"] = "OOB Grace Period"
                        elif "OOT_GRACE" in status_val.upper():
                            info["activation_status"] = "OOT Grace Period"
                        else:
                            info["activation_status"] = status_val
                    elif "Last 5 characters of installed product key:" in line_clean:
                        info["partial_key"] = line_clean.split(":", 1)[1].strip()
                    elif line_clean.startswith("ERROR DESCRIPTION:"):
                        info["error_desc"] = line_clean.split(":", 1)[1].strip()
                    elif line_clean.startswith("KMS machine name from DNS:") or line_clean.startswith("KMS machine:"):
                        parts = line_clean.split(":", 1)[1].strip().split(":")
                        info["kms_server"] = parts[0].strip()
                        if len(parts) > 1:
                            info["kms_port"] = parts[1].strip()
            except Exception:
                pass
            break

    # 3. Kiểm tra bổ sung từ WMI SoftwareLicensingProduct nếu cần
    if info["activation_status"] == "Unknown" or info["partial_key"] == "N/A":
        for ns in [r"root\cimv2", r"root\OfficeSoftwareProtectionPlatform"]:
            tbl = "SoftwareLicensingProduct" if "cimv2" in ns else "OfficeSoftwareProtectionProduct"
            wql = f"SELECT * FROM {tbl} WHERE PartialProductKey IS NOT NULL"
            prods = wmi_query(ns, wql)
            for prod in prods:
                name = str(safe_get(prod, "Name", "")).lower()
                desc = str(safe_get(prod, "Description", "")).lower()
                if "office" in name or "office" in desc or "proplus" in name:
                    if not info["installed"]:
                        info["installed"] = True
                        info["product_name"] = safe_get(prod, "Name", "Microsoft Office")
                    status_code = int(safe_get(prod, "LicenseStatus", 0))
                    info["activation_status"] = LICENSE_STATUS.get(status_code, "Unknown")
                    info["partial_key"] = safe_get(prod, "PartialProductKey", info["partial_key"])
                    kms_m = safe_get(prod, "KeyManagementServiceMachine", None)
                    if kms_m and kms_m != "N/A":
                        info["kms_server"] = kms_m
                    break
            if info["installed"] and info["activation_status"] != "Unknown":
                break

    return info


# ─── PHẦN 3: Adobe CC License ────────────────────────────────────────────────

def _get_adobe_license() -> Dict[str, Any]:
    """Đọc thông tin Adobe Creative Cloud từ registry."""
    info: Dict[str, Any] = {
        "installed": False,
        "products":  [],
    }

    adobe_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Adobe"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Adobe"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Adobe"),
    ]

    found_products = set()
    for hive, path in adobe_paths:
        try:
            with winreg.OpenKey(hive, path,
                               access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(k, i)
                        i += 1
                        # Bỏ qua các key không phải sản phẩm
                        if subkey_name.lower() in ["installer", "shared", "arm"]:
                            continue
                        product_name = subkey_name
                        if product_name not in found_products:
                            found_products.add(product_name)
                            info["products"].append({
                                "name":   product_name,
                                "status": "Installed",
                            })
                    except OSError:
                        break
        except Exception:
            continue

    # Kiểm tra Adobe CC Desktop App
    cc_path = os.path.expandvars(
        r"%ProgramFiles(x86)%\Adobe\Adobe Creative Cloud\ACC\Creative Cloud.exe"
    )
    if not os.path.exists(cc_path):
        cc_path = os.path.expandvars(
            r"%ProgramFiles%\Adobe\Adobe Creative Cloud\ACC\Creative Cloud.exe"
        )

    if os.path.exists(cc_path):
        info["installed"] = True
        info["cc_installed"] = True
    elif found_products:
        info["installed"] = True

    return info


# ─── PHẦN 4: CRACK DETECTION ─────────────────────────────────────────────────

def _check_hosts_file() -> List[Dict]:
    """
    [Kiểm tra 1] Quét hosts file tìm dòng KMS hijacking.
    Crack tool thường trỏ domain KMS Microsoft về localhost/IP giả.
    """
    findings = []
    hosts_path = Path(r"C:\Windows\System32\drivers\etc\hosts")

    try:
        with open(hosts_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception:
        return findings

    for line_num, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue  # Bỏ qua comment và dòng trống

        parts = stripped.split()
        if len(parts) < 2:
            continue

        ip_address = parts[0]
        hostnames  = parts[1:]

        for hostname in hostnames:
            hostname_lower = hostname.lower()
            for kms_domain in KMS_MICROSOFT_DOMAINS:
                if kms_domain in hostname_lower or hostname_lower in kms_domain:
                    # Domain KMS Microsoft bị trỏ về IP khác
                    # Kiểm tra có phải IP Microsoft không (216.x.x.x, 13.x.x.x...)
                    is_suspicious = not _is_microsoft_ip(ip_address)
                    if is_suspicious:
                        findings.append({
                            "type":        "hosts_kms_hijack",
                            "severity":    "High",
                            "title":       "Hosts file KMS hijacking phát hiện",
                            "description": (
                                f"Domain KMS '{hostname}' bị trỏ về IP '{ip_address}' "
                                f"(dòng {line_num}) — dấu hiệu KMS emulator."
                            ),
                            "evidence":    f"{hosts_path}:{line_num} → {stripped}",
                        })
    return findings


def _is_microsoft_ip(ip: str) -> bool:
    """Kiểm tra IP có thuộc dải Microsoft không (đơn giản hóa)."""
    # Microsoft sử dụng nhiều dải IP, đây chỉ là kiểm tra cơ bản
    microsoft_prefixes = ["13.", "20.", "40.", "52.", "104.", "131.", "137.", "157.", "168.", "207."]
    return any(ip.startswith(p) for p in microsoft_prefixes)


def _check_scheduled_tasks() -> List[Dict]:
    """
    [Kiểm tra 2] Quét Scheduled Tasks tìm task nghi ngờ liên quan KMS.
    Dùng schtasks.exe để liệt kê toàn bộ task.
    """
    findings = []

    try:
        # Lấy danh sách task dạng CSV
        result = subprocess.run(
            ["schtasks", "/query", "/fo", "LIST", "/v"],
            capture_output=True, text=True, timeout=20,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output = result.stdout
    except Exception:
        return findings

    # Parse task blocks
    current_task = {}
    for line in output.splitlines():
        if line.startswith("TaskName:"):
            if current_task:
                _evaluate_task(current_task, findings)
            current_task = {"name": line.split(":", 1)[1].strip()}
        elif ":" in line and current_task:
            key, _, val = line.partition(":")
            current_task[key.strip()] = val.strip()

    if current_task:
        _evaluate_task(current_task, findings)

    return findings


def _evaluate_task(task: Dict, findings: List) -> None:
    """Đánh giá 1 task có nghi ngờ không."""
    task_path = task.get("name", "")
    task_name = task_path.lower()
    run_as    = task.get("Run As User", "").lower()
    task_cmd  = (task.get("Task To Run", "") + task.get("Action", "")).lower()
    author    = task.get("Author", "").lower()

    # Bỏ qua các task hệ thống chuẩn của Microsoft dưới \Microsoft\Windows\ trừ khi tên chứa chính xác crack tool
    if "\\microsoft\\windows\\" in task_name:
        explicit_crack = any(c in task_name for c in ["kmspico", "aact", "autopico", "kms_vl_all", "ohook", "ospphook"])
        if not explicit_crack:
            return

    # Kiểm tra từ khóa nghi ngờ trong tên task
    name_suspicious = any(kw in task_name for kw in SUSPICIOUS_TASK_KEYWORDS)
    # Kiểm tra command chạy từ thư mục nghi ngờ
    cmd_suspicious  = any(p in task_cmd for p in [
        "\\appdata\\", "\\temp\\", "\\roaming\\", "kmspico", "aact", "autopico"
    ])
    # Kiểm tra task không có author hợp lệ và có từ khóa kms
    no_publisher    = not author or author in ["n/a", ""]

    if name_suspicious or (cmd_suspicious and no_publisher):
        severity = "High" if name_suspicious else "Medium"
        findings.append({
            "type":        "suspicious_scheduled_task",
            "severity":    severity,
            "title":       f"Scheduled Task nghi ngờ: '{task.get('name', 'Unknown')}'",
            "description": (
                f"Task có tên/lệnh liên quan đến KMS/activation. "
                f"Command: {task.get('Task To Run', 'N/A')[:100]}"
            ),
            "evidence":    f"Task: {task.get('name', 'N/A')} | Author: {task.get('Author', 'N/A')}",
        })


def _check_port_1688() -> List[Dict]:
    """
    [Kiểm tra 3] Kiểm tra port 1688 (KMS port chuẩn) có đang bị lắng nghe không.
    Nếu có service/process lạ listen port 1688 → nghi ngờ KMS emulator local.
    """
    findings = []

    try:
        connections = psutil.net_connections(kind="tcp")
        for conn in connections:
            if conn.laddr and conn.laddr.port == 1688 and conn.status == "LISTEN":
                # Tìm process đang listen
                proc_name = "Unknown"
                proc_path = "N/A"
                try:
                    if conn.pid:
                        proc = psutil.Process(conn.pid)
                        proc_name = proc.name()
                        proc_path = proc.exe()
                except Exception:
                    pass

                # Bỏ qua nếu là process hệ thống hợp lệ
                legit_processes = {"lsass.exe", "svchost.exe", "system"}
                if proc_name.lower() not in legit_processes:
                    findings.append({
                        "type":        "kms_port_listener",
                        "severity":    "Critical",
                        "title":       f"KMS emulator đang chạy (port 1688): {proc_name}",
                        "description": (
                            f"Process '{proc_name}' đang lắng nghe port 1688 (KMS port). "
                            f"Đây là dấu hiệu mạnh của KMS emulator giả mạo."
                        ),
                        "evidence":    f"PID: {conn.pid} | Process: {proc_name} | Path: {proc_path}",
                    })
    except Exception:
        pass

    return findings


def _check_spp_file_signatures() -> List[Dict]:
    """
    [Kiểm tra 4] Kiểm tra chữ ký số (Authenticode) của các file SPP quan trọng.
    File bị patch bởi crack tool thường mất hoặc có chữ ký không hợp lệ.

    Files kiểm tra:
      - C:/Windows/System32/sppsvc.exe (Software Protection Platform service)
      - C:/Windows/System32/SppExtComObj.dll
      - C:/Windows/System32/slc.dll (Software Licensing Client)
    """
    findings = []

    spp_files = [
        Path(r"C:\Windows\System32\sppsvc.exe"),
        Path(r"C:\Windows\System32\SppExtComObj.dll"),
        Path(r"C:\Windows\System32\slc.dll"),
        Path(r"C:\Windows\SysWOW64\slc.dll"),
    ]

    for file_path in spp_files:
        if not file_path.exists():
            continue

        # Kiểm tra chữ ký bằng PowerShell Get-AuthenticodeSignature
        try:
            ps_cmd = (
                f"$sig = Get-AuthenticodeSignature '{file_path}'; "
                f"$sig.Status.ToString() + '|' + $sig.SignerCertificate.Subject"
            )
            result = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = result.stdout.strip()

            if "|" in output:
                status, subject = output.split("|", 1)
                status = status.strip()

                if status == "Valid":
                    # Chữ ký hợp lệ → kiểm tra có phải Microsoft không
                    if "Microsoft Corporation" not in subject and "Microsoft Windows" not in subject:
                        findings.append({
                            "type":        "spp_signature_mismatch",
                            "severity":    "High",
                            "title":       f"File SPP có chữ ký không phải Microsoft: {file_path.name}",
                            "description": f"Signer: {subject[:80]}",
                            "evidence":    str(file_path),
                        })
                elif status in ["NotSigned", "HashMismatch", "NotTrusted"]:
                    findings.append({
                        "type":        "spp_signature_invalid",
                        "severity":    "Critical",
                        "title":       f"File SPP bị thay đổi/mất chữ ký: {file_path.name}",
                        "description": (
                            f"Trạng thái chữ ký: {status}. "
                            f"File '{file_path.name}' có thể đã bị patch bởi crack tool."
                        ),
                        "evidence":    str(file_path),
                    })
        except Exception:
            continue

    return findings


def _check_registry_tamper() -> List[Dict]:
    """
    [Kiểm tra 5] Kiểm tra registry SPP/KMS bị can thiệp.
    Tìm KMS server address trỏ về localhost hoặc IP nội bộ.
    """
    findings = []

    # Key SPP chứa KMS configuration
    spp_paths = [
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SoftwareProtectionPlatform"),
        (winreg.HKEY_LOCAL_MACHINE,
         r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\SoftwareProtectionPlatform\Activation"),
    ]

    for hive, path in spp_paths:
        try:
            with winreg.OpenKey(hive, path,
                               access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                # Đọc KMSName — địa chỉ KMS server đã cấu hình
                try:
                    kms_name = winreg.QueryValueEx(key, "KeyManagementServiceName")[0]
                    if kms_name:
                        # Kiểm tra có phải địa chỉ nội bộ không
                        suspicious_addresses = [
                            "127.0.0.1", "localhost", "::1",
                            "0.0.0.0", "192.168.", "10.", "172.",
                        ]
                        if any(kms_name.startswith(addr) for addr in suspicious_addresses):
                            findings.append({
                                "type":        "registry_kms_local_server",
                                "severity":    "High",
                                "title":       "Registry KMS server trỏ về địa chỉ nội bộ",
                                "description": (
                                    f"KMS server '{kms_name}' là địa chỉ local/private, "
                                    "có thể là KMS emulator đang chạy trên máy."
                                ),
                                "evidence":    f"{path}\\KeyManagementServiceName = {kms_name}",
                            })
                except FileNotFoundError:
                    pass  # Key không tồn tại = bình thường

                # Kiểm tra KeyManagementServicePort bất thường (bình thường là 1688)
                try:
                    kms_port = int(winreg.QueryValueEx(key, "KeyManagementServicePort")[0])
                    if kms_port != 1688 and kms_port > 0:
                        findings.append({
                            "type":        "registry_kms_nonstandard_port",
                            "severity":    "Medium",
                            "title":       f"KMS port khác 1688: {kms_port}",
                            "description": "KMS port chuẩn là 1688. Giá trị khác có thể bất thường.",
                            "evidence":    f"{path}\\KeyManagementServicePort = {kms_port}",
                        })
                except (FileNotFoundError, ValueError):
                    pass

        except Exception:
            continue

    # Kiểm tra registry run key cho crack tools
    run_paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Wow6432Node\Microsoft\Windows\CurrentVersion\Run"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Windows\CurrentVersion\Run"),
    ]

    for hive, path in run_paths:
        try:
            with winreg.OpenKey(hive, path,
                               access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        i += 1
                        val_lower  = val.lower()
                        name_lower = name.lower()
                        # Kiểm tra nếu value chứa tên crack tool
                        for crack_name in KNOWN_CRACK_FILENAMES:
                            if crack_name in val_lower or crack_name in name_lower:
                                findings.append({
                                    "type":        "registry_run_crack_tool",
                                    "severity":    "Critical",
                                    "title":       f"Crack tool trong registry Run: '{name}'",
                                    "description": f"Registry Run key '{name}' trỏ tới '{val[:100]}'",
                                    "evidence":    f"{path}\\{name} = {val[:150]}",
                                })
                    except OSError:
                        break
        except Exception:
            continue

    return findings


def _check_known_crack_files() -> List[Dict]:
    """
    [Kiểm tra 7] Quét các đường dẫn phổ biến của crack tool đã biết.
    Bao gồm KMSpico, AAct, Microsoft Toolkit, SECOH-QAD loader...
    """
    findings = []

    for path_template in KNOWN_CRACK_PATHS:
        # Expand environment variables
        try:
            expanded = os.path.expandvars(path_template)
        except Exception:
            continue

        if os.path.exists(expanded):
            # Lấy tên file/folder
            item_name = os.path.basename(expanded)
            findings.append({
                "type":        "known_crack_file_found",
                "severity":    "Critical",
                "title":       f"Crack tool phát hiện: '{item_name}'",
                "description": f"Đã tìm thấy file/thư mục của crack tool tại đường dẫn đã biết.",
                "evidence":    expanded,
            })

    # Quét thêm trong %TEMP% và %APPDATA%
    scan_dirs = [
        os.environ.get("TEMP", ""),
        os.environ.get("APPDATA", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    for scan_dir in scan_dirs:
        if not scan_dir or not os.path.isdir(scan_dir):
            continue
        try:
            for item in os.listdir(scan_dir):
                item_lower = item.lower()
                if any(cf in item_lower for cf in KNOWN_CRACK_FILENAMES):
                    findings.append({
                        "type":        "crack_file_in_temp",
                        "severity":    "High",
                        "title":       f"File crack tìm thấy trong Temp/AppData: {item}",
                        "description": "File có tên trùng với crack tool đã biết.",
                        "evidence":    os.path.join(scan_dir, item),
                    })
        except Exception:
            continue

    return findings


def _check_crack_services() -> List[Dict]:
    """
    [Kiểm tra 8] Tìm Windows service liên quan KMS emulator.
    Các service như KMService, KMSpico... thường được cài bởi crack tool.
    """
    findings = []

    services = wmi_query(r"root\cimv2", "SELECT * FROM Win32_Service")
    for svc in services:
        svc_name  = safe_get(svc, "Name",        "").lower()
        svc_disp  = safe_get(svc, "DisplayName", "").lower()
        svc_path  = safe_get(svc, "PathName",    "").lower()

        # Kiểm tra tên service
        if any(k in svc_name or k in svc_disp for k in KNOWN_CRACK_SERVICES):
            findings.append({
                "type":        "crack_service_found",
                "severity":    "Critical",
                "title":       f"KMS crack service đang chạy: '{safe_get(svc, 'Name', 'N/A')}'",
                "description": (
                    f"Service '{safe_get(svc, 'DisplayName', 'N/A')}' "
                    f"có tên liên quan KMS emulator. "
                    f"State: {safe_get(svc, 'State', 'N/A')}"
                ),
                "evidence":    f"Path: {safe_get(svc, 'PathName', 'N/A')[:150]}",
            })
            continue

        # Kiểm tra service chạy từ AppData/Temp (không bình thường)
        suspicious_paths = ["\\appdata\\", "\\temp\\", "\\roaming\\"]
        if any(p in svc_path for p in suspicious_paths):
            # Kiểm tra thêm tên file có nghi ngờ không
            for cf in KNOWN_CRACK_FILENAMES:
                if cf in svc_path:
                    findings.append({
                        "type":        "suspicious_service_path",
                        "severity":    "High",
                        "title":       f"Service chạy từ thư mục nghi ngờ: '{safe_get(svc, 'Name', 'N/A')}'",
                        "description": f"Service path: {safe_get(svc, 'PathName', 'N/A')[:150]}",
                        "evidence":    safe_get(svc, "PathName", "N/A"),
                    })
                    break

    return findings


def _check_unsigned_drivers() -> List[Dict]:
    """
    [Kiểm tra 9] Kiểm tra driver kernel không có chữ ký số hợp lệ.
    Crack tool dạng driver-based thường cài driver unsigned để hook API.
    """
    findings = []

    try:
        # driverquery /FO CSV /SI — liệt kê driver với thông tin signing
        result = subprocess.run(
            ["driverquery", "/FO", "CSV", "/SI"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        lines = result.stdout.splitlines()

        if len(lines) < 2:
            return findings

        # Bỏ qua header (dòng 1)
        for line in lines[1:]:
            parts = line.split(",")
            if len(parts) < 6:
                continue

            # Làm sạch CSV values (bỏ quotes)
            parts = [p.strip().strip('"') for p in parts]
            module_name = parts[0] if parts else "N/A"
            display_name = parts[1] if len(parts) > 1 else "N/A"
            driver_type  = parts[2] if len(parts) > 2 else "N/A"
            is_signed    = parts[5] if len(parts) > 5 else "N/A"

            # Chỉ quan tâm driver kernel (Kernel type) chưa ký
            if "kernel" in driver_type.lower() and is_signed.lower() in ["false", "no"]:
                # Bỏ qua các driver phổ biến không cần ký
                skip_drivers = {
                    "flpydisk", "cdrom", "tape", "scsiraid", "null", "beep"
                }
                if module_name.lower() in skip_drivers:
                    continue

                findings.append({
                    "type":        "unsigned_kernel_driver",
                    "severity":    "Medium",
                    "title":       f"Driver kernel không ký số: {display_name}",
                    "description": (
                        f"Driver '{module_name}' ({driver_type}) không có chữ ký số hợp lệ. "
                        "Crack tool dạng driver thường không được ký."
                    ),
                    "evidence":    f"Module: {module_name} | Signed: {is_signed}",
                })
    except Exception:
        pass

    return findings


def _check_office_kms_emulation(office_info: Dict[str, Any]) -> List[Dict]:
    """
    [Office Crack 1] Giả lập KMS server (giống Windows):
    Office Volume/MAK có thể activate qua KMS nội bộ. Crack tool tạo KMS giả trên localhost/LAN
    hoặc dùng Scheduled Task 'Office', 'OSPP', 'AutoKMS' để renew 180 ngày.
    """
    findings = []
    
    kms_server = office_info.get("kms_server")
    if kms_server and kms_server != "N/A":
        suspicious_addrs = ["127.0.0.1", "localhost", "::1", "0.0.0.0", "192.168.", "10.", "172."]
        if any(kms_server.startswith(addr) for addr in suspicious_addrs) or not _is_microsoft_ip(kms_server):
            findings.append({
                "type":        "office_kms_emulation",
                "severity":    "Critical",
                "title":       f"Phát hiện Office cấu hình kích hoạt qua KMS server giả lập: '{kms_server}'",
                "description": (
                    f"Office đang trỏ tới KMS server '{kms_server}' để kích hoạt. "
                    f"Đây là dấu hiệu của phần mềm KMS emulator dựng máy chủ giả trên LAN/localhost."
                ),
                "evidence":    f"OSPP / WMI KMS Server = {kms_server}",
            })

    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\OfficeSoftwareProtectionPlatform", access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
            try:
                reg_kms = winreg.QueryValueEx(k, "KeyManagementServiceName")[0]
                if reg_kms and reg_kms != kms_server:
                    suspicious_addrs = ["127.0.0.1", "localhost", "::1", "0.0.0.0", "192.168.", "10.", "172."]
                    if any(reg_kms.startswith(addr) for addr in suspicious_addrs):
                        findings.append({
                            "type":        "office_registry_kms_local",
                            "severity":    "High",
                            "title":       f"Registry OSPP của Office trỏ về KMS server local: '{reg_kms}'",
                            "description": "Registry HKLM\\SOFTWARE\\Microsoft\\OfficeSoftwareProtectionPlatform có KeyManagementServiceName trỏ về localhost/LAN.",
                            "evidence":    f"KeyManagementServiceName = {reg_kms}",
                        })
            except FileNotFoundError:
                pass
    except Exception:
        pass

    return findings


def _check_office_r2v_conversion(office_info: Dict[str, Any]) -> List[Dict]:
    """
    [Office Crack 2] Chuyển đổi Retail -> Volume license (C2R-R2V / GVLK Injection):
    Dùng script nạp Product Key GVLK doanh nghiệp public vào bản Office Click-to-Run Retail
    rồi trỏ activation qua KMS giả.
    """
    findings = []
    if not office_info.get("installed"):
        return findings

    prod_name = str(office_info.get("product_name", "")).lower()
    lic_type  = str(office_info.get("license_type", "")).lower()
    channel   = str(office_info.get("channel", "")).lower()
    partial   = str(office_info.get("partial_key", "")).upper()

    # Danh sách 5 ký tự cuối của GVLK (Generic Volume License Key) công khai cho Office
    office_gvlk_partials = {
        "88KC6": "Office ProPlus 2024 / 2021 GVLK",
        "6MWKP": "Office ProPlus 2019 GVLK",
        "WFG99": "Office ProPlus 2016 GVLK",
        "VCFCH": "Office Standard 2019 GVLK",
        "C2B9Z": "Office Standard 2016 GVLK",
        "6Q7VD": "Office ProPlus 2013 GVLK",
        "FBFBJ": "Office Standard 2013 GVLK",
    }

    is_retail_installer = "retail" in prod_name
    # Chỉ cảnh báo chuyển đổi R2V nếu bộ cài Retail thực sự đang chạy ở chế độ Volume / KMS Client
    is_volume_active = "volume" in lic_type or "kms" in lic_type or "volume_kmsclient" in channel
    if is_retail_installer and is_volume_active and partial in office_gvlk_partials:
        key_desc = office_gvlk_partials.get(partial, "Volume KMS Client Key")
        findings.append({
            "type":        "office_retail_to_volume_crack",
            "severity":    "High",
            "title":       "Phát hiện dấu hiệu chuyển đổi Office Retail sang Volume (C2R-R2V / GVLK)",
            "description": (
                f"Sản phẩm cài đặt gốc là bộ Retail ('{office_info.get('product_name')}') "
                f"nhưng lại áp dụng giấy phép Volume/KMS ('{key_desc}', Partial Key: {partial}). "
                "Đây là kỹ thuật C2R-R2V phổ biến để bẻ khóa qua KMS hoặc chèn token giả."
            ),
            "evidence":    f"Installer: {office_info.get('product_name')} | Active License: {lic_type} ({partial})",
        })

    return findings


def _check_office_file_integrity() -> List[Dict]:
    """
    [Office Crack 3] Patch file thực thi (ospp.vbs, licensingsdk, sppsvc liên quan Office):
    Kiểm tra chữ ký số Authenticode và tính nguyên vẹn của các file xử lý license Office.
    """
    findings = []
    office_files_to_check = [
        Path(r"C:\Program Files\Microsoft Office\root\Office16\ospp.vbs"),
        Path(r"C:\Program Files\Microsoft Office\root\Office16\OSPPC.DLL"),
        Path(r"C:\Program Files\Microsoft Office\root\Office16\OSPPWMI.DLL"),
        Path(r"C:\Program Files\Microsoft Office\root\vfs\ProgramFilesCommonX64\Microsoft Shared\Office16\licensing\licensing.dll"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\Office16\ospp.vbs"),
    ]

    for fpath in office_files_to_check:
        if not fpath.exists():
            continue
        try:
            ps_cmd = (
                f"$sig = Get-AuthenticodeSignature '{fpath}'; "
                f"$sig.Status.ToString() + '|' + $sig.SignerCertificate.Subject"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_cmd],
                capture_output=True, text=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW
            )
            output = res.stdout.strip()
            if "|" in output:
                status, subject = output.split("|", 1)
                status = status.strip()
                if status == "Valid":
                    if "Microsoft Corporation" not in subject and "Microsoft Windows" not in subject:
                        findings.append({
                            "type":        "office_file_signature_mismatch",
                            "severity":    "High",
                            "title":       f"File bản quyền Office có chữ ký không phải Microsoft: {fpath.name}",
                            "description": f"Signer: {subject[:80]}",
                            "evidence":    str(fpath),
                        })
                elif status in ["NotSigned", "HashMismatch", "NotTrusted"]:
                    findings.append({
                        "type":        "office_file_signature_invalid",
                        "severity":    "Critical",
                        "title":       f"File xử lý license Office bị mất chữ ký/patch thay thế: {fpath.name}",
                        "description": (
                            f"Trạng thái chữ ký: {status}. "
                            f"File '{fpath.name}' có thể đã bị sửa đổi trực tiếp để bypass kiểm tra bản quyền."
                        ),
                        "evidence":    str(fpath),
                    })
        except Exception:
            continue

    return findings


def _check_office_license_cache_injection() -> List[Dict]:
    """
    [Office Crack 4] License file cắm sẵn (offline activation / .xrm-ms / Ohook cache injection):
    Kiểm tra thư mục Cache ProgramData\\Microsoft\\OfficeSoftwareProtectionPlatform\\Cache (tokens.dat, .xrm-ms).
    """
    findings = []
    cache_dir = Path(r"C:\ProgramData\Microsoft\OfficeSoftwareProtectionPlatform\Cache")

    if cache_dir.exists():
        try:
            for item in cache_dir.iterdir():
                if item.name.lower() == "cache.dat" or item.suffix.lower() == ".xrm-ms":
                    findings.append({
                        "type":        "office_offline_token_injection",
                        "severity":    "High",
                        "title":       f"Phát hiện file license token lạ trong cache OSPP: '{item.name}'",
                        "description": "Thư mục Cache của OfficeSoftwareProtectionPlatform chứa file token/blob (.xrm-ms) bất thường nghi chèn từ máy khác (Offline Activation / Ohook).",
                        "evidence":    str(item),
                    })
        except Exception:
            pass

    ohook_paths = [
        Path(r"C:\Program Files\Microsoft Office\root\vfs\ProgramFilesCommonX64\Microsoft Shared\Office16\sppc.dll"),
        Path(r"C:\Program Files (x86)\Microsoft Office\root\vfs\ProgramFilesCommonX86\Microsoft Shared\Office16\sppc.dll"),
    ]
    for op in ohook_paths:
        if op.exists():
            findings.append({
                "type":        "office_ohook_bypass",
                "severity":    "Critical",
                "title":       "Phát hiện DLL Ohook giả lập sppc.dll trong thư mục cài đặt Office",
                "description": (
                    f"Đã tìm thấy file '{op.name}' tại đường dẫn riêng của Office ('{op.parent}'). "
                    "Đây là công cụ Ohook (MAS) đánh lừa Office đã kích hoạt vĩnh viễn không cần KMS."
                ),
                "evidence":    str(op),
            })

    return findings


def _check_office_registry_bypass() -> List[Dict]:
    """
    [Office Crack 5] Registry-only bypass (đơn giản nhất, ít bền):
    Kiểm tra can thiệp thẳng giá trị trong registry để Office nghĩ đã activate.
    """
    findings = []
    reg_checks = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\16.0\Common\Licensing", "LicenseStatusOverride"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Office\16.0\Common\Licensing", "NoLicenseCheck"),
        (winreg.HKEY_CURRENT_USER,  r"SOFTWARE\Microsoft\Office\16.0\Common\Licensing", "LicenseStatusOverride"),
    ]

    for hive, path, val_name in reg_checks:
        try:
            with winreg.OpenKey(hive, path, access=winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                try:
                    val = winreg.QueryValueEx(k, val_name)[0]
                    findings.append({
                        "type":        "office_registry_override",
                        "severity":    "Critical",
                        "title":       f"Phát hiện Registry Override can thiệp bản quyền Office: '{val_name}'",
                        "description": f"Key registry '{path}\\{val_name}' = {val} được đặt để giả mạo trạng thái kiểm tra bản quyền.",
                        "evidence":    f"{path}\\{val_name} = {val}",
                    })
                except FileNotFoundError:
                    pass
        except Exception:
            continue

    return findings


def _calculate_risk_level(findings: List[Dict]) -> str:
    """Tính mức độ rủi ro tổng thể từ danh sách findings."""
    if not findings:
        return "None"

    has_critical = any(f["severity"] == "Critical" for f in findings)
    has_high     = any(f["severity"] == "High"     for f in findings)
    has_medium   = any(f["severity"] == "Medium"   for f in findings)

    if has_critical:
        return "Critical"
    elif has_high:
        return "High"
    elif has_medium:
        return "Medium"
    return "Low"


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def collect(system_manufacturer: str = "N/A") -> Dict[str, Any]:
    """
    Thu thập toàn bộ thông tin bản quyền và scan crack.

    Args:
        system_manufacturer: Tên hãng máy từ motherboard_collector
                             (dùng để so sánh với SLIC OEM ID)

    Returns:
        Dict với:
          windows: thông tin bản quyền Windows
          office: thông tin bản quyền Office
          adobe: thông tin Adobe products
          crack_scan: {risk_level, findings}
    """
    result: Dict[str, Any] = {}

    # ─── Bản quyền phần mềm ──────────────────────────────────────────────────
    result["windows"] = _get_windows_license()
    result["office"]  = _get_office_license()
    result["adobe"]   = _get_adobe_license()

    # ─── Quét crack Windows & Office ─────────────────────────────────────────
    all_findings: List[Dict] = []

    all_findings += _check_hosts_file()          # 1. Hosts file KMS hijack
    all_findings += _check_scheduled_tasks()     # 2. Scheduled task nghi ngờ (Windows & Office)
    all_findings += _check_port_1688()           # 3. Port 1688 listener
    all_findings += _check_spp_file_signatures() # 4. SPP file signature
    all_findings += _check_registry_tamper()     # 5. Registry tamper
    all_findings += _check_known_crack_files()   # 7. Known crack files
    all_findings += _check_crack_services()      # 8. Crack services
    all_findings += _check_unsigned_drivers()    # 9. Unsigned drivers

    # --- 5 Kiểm tra chuyên sâu cho Microsoft Office ---
    all_findings += _check_office_kms_emulation(result["office"])         # Office 1. KMS Emulation
    all_findings += _check_office_r2v_conversion(result["office"])        # Office 2. Retail -> Volume / GVLK
    all_findings += _check_office_file_integrity()                        # Office 3. Patch file thực thi
    all_findings += _check_office_license_cache_injection()               # Office 4. License file cắm sẵn / Ohook
    all_findings += _check_office_registry_bypass()                       # Office 5. Registry-only bypass

    risk_level = _calculate_risk_level(all_findings)

    result["crack_scan"] = {
        "risk_level":      risk_level,
        "risk_color":      {
            "None":     "good",
            "Low":      "good",
            "Medium":   "warn",
            "High":     "danger",
            "Critical": "danger",
        }.get(risk_level, "unknown"),
        "total_findings":  len(all_findings),
        "critical_count":  sum(1 for f in all_findings if f["severity"] == "Critical"),
        "high_count":      sum(1 for f in all_findings if f["severity"] == "High"),
        "medium_count":    sum(1 for f in all_findings if f["severity"] == "Medium"),
        "findings":        all_findings,
    }

    return result
