"""
collectors/network_collector.py
Thu thập thông tin mạng: phần cứng NIC, cấu hình IP, kiểm tra kết nối internet,
kiểm tra firewall và phát hiện dấu hiệu nghi ngờ (port 1688 rule, v.v.)

API sử dụng:
  - WMI Win32_NetworkAdapter: thông tin NIC vật lý (hãng, driver, MAC, tốc độ)
  - WMI Win32_NetworkAdapterConfiguration: IP, gateway, DNS
  - psutil.net_if_stats(): trạng thái adapter
  - socket: kiểm tra kết nối internet (ping TCP)
  - subprocess netsh: kiểm tra Windows Firewall
  - WMI Win32_NetworkLoginProfile: thông tin domain (nếu join domain)
"""
from __future__ import annotations

import socket
import subprocess
import time
from typing import Dict, Any, List, Optional

import psutil
from utils.wmi_helper import wmi_query, safe_get


# ─── Kiểm tra kết nối internet ───────────────────────────────────────────────

def _check_internet_connectivity() -> Dict[str, Any]:
    """
    Kiểm tra kết nối internet bằng TCP connect tới Google DNS (8.8.8.8:53).
    Không dùng ICMP ping để tránh bị block bởi firewall.
    Đo latency trung bình từ 3 lần kết nối.

    Returns:
        Dict với online (bool), ping_ms (float), ping_target (str)
    """
    result = {
        "online":       False,
        "ping_ms":      None,
        "ping_target":  "8.8.8.8",
        "dns_reachable": False,
    }

    targets = [
        ("8.8.8.8",       53,  "Google DNS"),
        ("1.1.1.1",       53,  "Cloudflare DNS"),
        ("223.5.5.5",     53,  "AliDNS (fallback)"),
    ]

    for ip, port, name in targets:
        latencies = []
        for _ in range(3):
            try:
                t_start = time.perf_counter()
                sock = socket.create_connection((ip, port), timeout=3)
                t_end = time.perf_counter()
                sock.close()
                latencies.append((t_end - t_start) * 1000)
            except Exception:
                break

        if latencies:
            result["online"]      = True
            result["ping_ms"]     = round(sum(latencies) / len(latencies), 1)
            result["ping_target"] = f"{ip} ({name})"
            break

    return result


# ─── Phần cứng và cấu hình NIC ───────────────────────────────────────────────

def _get_adapters() -> List[Dict]:
    """
    Lấy thông tin chi tiết từng NIC (Network Interface Card).
    Kết hợp dữ liệu từ:
      - Win32_NetworkAdapter: thông tin phần cứng (hãng, driver, MAC)
      - Win32_NetworkAdapterConfiguration: cấu hình IP
      - psutil net_if_stats: tốc độ thực tế, trạng thái
    """
    adapters = []

    # Lấy cấu hình IP (indexed by InterfaceIndex)
    configs = wmi_query(
        r"root\cimv2",
        "SELECT * FROM Win32_NetworkAdapterConfiguration WHERE IPEnabled=True"
    )
    config_by_index: Dict[int, Any] = {}
    for cfg in configs:
        idx = safe_get(cfg, "InterfaceIndex", None)
        if idx is not None:
            config_by_index[int(idx)] = cfg

    # psutil stats (speed, isup)
    psutil_stats = {}
    try:
        psutil_stats = psutil.net_if_stats()
    except Exception:
        pass

    psutil_addrs = {}
    try:
        psutil_addrs = psutil.net_if_addrs()
    except Exception:
        pass

    # Lấy danh sách toàn bộ adapter từ WMI
    hw_adapters = wmi_query(
        r"root\cimv2",
        "SELECT * FROM Win32_NetworkAdapter"
    )

    for hw in hw_adapters:
        name       = safe_get(hw, "Name",              "N/A").strip()
        name_lower = name.lower()

        # Bỏ qua các driver ảo dạng tunnel mặc định của hệ thống Windows
        if any(k in name_lower for k in ["wan miniport", "kernel debugger", "ras async adapter", "ndis virtual", "microsoft kernel"]):
            continue

        idx        = int(safe_get(hw, "InterfaceIndex", 0))
        net_type   = safe_get(hw, "NetworkConnectionID", "").strip()
        mac        = safe_get(hw, "MACAddress",         "N/A").strip()
        driver_ver = safe_get(hw, "DriverVersion",      "N/A").strip()
        manufacturer = safe_get(hw, "Manufacturer",    "N/A").strip()
        is_physical = bool(safe_get(hw, "PhysicalAdapter", False))

        # Tốc độ kết nối (bit/s → Mbps)
        speed_bps  = int(safe_get(hw, "Speed", 0))
        speed_mbps = round(speed_bps / 1_000_000, 0) if speed_bps > 0 else 0

        # Trạng thái adapter
        net_status = safe_get(hw, "NetConnectionStatus", 2)
        status_map = {
            0: "Disconnected", 1: "Connecting", 2: "Connected",
            3: "Disconnecting", 4: "Hardware not present",
            5: "Hardware disabled", 6: "Hardware malfunction",
            7: "Media disconnected", 8: "Authenticating",
            9: "Authentication succeeded", 10: "Authentication failed",
            11: "Invalid address", 12: "Credentials required",
        }
        status = status_map.get(int(net_status), "Unknown")

        # Thông tin IP từ config
        ip4_list  = []
        ip6_list  = []
        gateways  = []
        dns_list  = []
        subnet    = "N/A"
        dhcp      = False

        if idx in config_by_index:
            cfg = config_by_index[idx]
            ip4_addrs = safe_get(cfg, "IPAddress", [])
            if isinstance(ip4_addrs, (list, tuple)):
                for ip in ip4_addrs:
                    if ip and "." in ip:
                        ip4_list.append(ip)
                    elif ip and ":" in ip:
                        ip6_list.append(ip)
            elif ip4_addrs and ip4_addrs != "N/A":
                ip4_list.append(str(ip4_addrs))

            subnet_masks = safe_get(cfg, "IPSubnet", [])
            if isinstance(subnet_masks, (list, tuple)) and subnet_masks:
                subnet = subnet_masks[0]
            elif isinstance(subnet_masks, str):
                subnet = subnet_masks

            gw = safe_get(cfg, "DefaultIPGateway", [])
            if isinstance(gw, (list, tuple)):
                gateways = list(gw)
            elif gw and gw != "N/A":
                gateways = [gw]

            dns = safe_get(cfg, "DNSServerSearchOrder", [])
            if isinstance(dns, (list, tuple)):
                dns_list = list(dns)
            elif dns and dns != "N/A":
                dns_list = [dns]

            dhcp = bool(safe_get(cfg, "DHCPEnabled", False))

        # Fallback: psutil addresses nếu WMI không có IP
        if not ip4_list and name in psutil_addrs:
            for addr in psutil_addrs[name]:
                if addr.family == socket.AF_INET:
                    ip4_list.append(addr.address)
                elif addr.family == socket.AF_INET6:
                    ip6_list.append(addr.address.split("%")[0])

        # Loại adapter (WiFi, Ethernet, Virtual...)
        adapter_type = "Ethernet"
        if not is_physical:
            adapter_type = "Virtual"
        elif any(k in name_lower for k in ["wi-fi", "wireless", "wlan", "wifi", "802.11"]):
            adapter_type = "Wi-Fi"
        elif any(k in name_lower for k in ["virtual", "vmware", "virtualbox", "hyper-v", "loopback"]):
            adapter_type = "Virtual"
        elif "bluetooth" in name_lower:
            adapter_type = "Bluetooth"

        adapter_info = {
            "name":         name,
            "type":         adapter_type,
            "manufacturer": manufacturer,
            "mac":          mac,
            "driver_ver":   driver_ver,
            "speed_mbps":   speed_mbps,
            "status":       status,
            "ip4":          ip4_list[0] if ip4_list else "N/A",
            "ip4_list":     ip4_list,
            "ip6":          ip6_list[0] if ip6_list else "N/A",
            "subnet":       subnet,
            "gateways":     gateways,
            "dns":          dns_list,
            "dhcp":         dhcp,
            "is_physical":  is_physical,
        }
        adapters.append(adapter_info)

    return adapters


# ─── Kiểm tra Windows Firewall ───────────────────────────────────────────────

def _check_firewall() -> Dict[str, Any]:
    """
    Kiểm tra trạng thái Windows Defender Firewall và rules nghi ngờ.

    Kiểm tra:
      1. Firewall profile (Domain/Private/Public) có bật không
      2. Có rule nào allow port 1688 từ bên ngoài không (KMS allow rule)
      3. Có rule nào block Windows Update không (trick của crack tool)
    """
    firewall_info: Dict[str, Any] = {
        "domain_profile":  "Unknown",
        "private_profile": "Unknown",
        "public_profile":  "Unknown",
        "all_enabled":     False,
        "suspicious_rules": [],
    }

    # ─── Trạng thái từng profile ──────────────────────────────────────────────
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "show", "allprofiles", "state"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output = result.stdout

        # Parse output: "Domain Profile Settings: State ON"
        profile_map = {
            "domain":  "domain_profile",
            "private": "private_profile",
            "public":  "public_profile",
        }
        for line in output.splitlines():
            line_lower = line.lower().strip()
            for profile, key in profile_map.items():
                if profile in line_lower:
                    if "on" in line_lower:
                        firewall_info[key] = "Enabled"
                    elif "off" in line_lower:
                        firewall_info[key] = "Disabled"

        # Tất cả enabled?
        firewall_info["all_enabled"] = all(
            firewall_info[k] == "Enabled"
            for k in ["domain_profile", "private_profile", "public_profile"]
        )

    except Exception:
        pass

    # ─── Kiểm tra rule cho port 1688 (KMS) ───────────────────────────────────
    try:
        # Tìm rule inbound cho port 1688
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule",
             "protocol=TCP", "localport=1688", "dir=in"],
            capture_output=True, text=True, timeout=10,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        if "Rule Name" in result.stdout and "No rules match" not in result.stdout:
            firewall_info["suspicious_rules"].append({
                "port":     1688,
                "direction": "Inbound",
                "note":     "Rule TCP 1688 inbound — KMS emulator có thể đang được phép",
                "raw":      result.stdout[:300],
            })
    except Exception:
        pass

    # ─── Kiểm tra firewall block Windows Update ───────────────────────────────
    wu_domains = ["windowsupdate.microsoft.com", "update.microsoft.com"]
    try:
        result = subprocess.run(
            ["netsh", "advfirewall", "firewall", "show", "rule", "name=all"],
            capture_output=True, text=True, timeout=15,
            encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        output_lower = result.stdout.lower()
        for wu_domain in wu_domains:
            if wu_domain in output_lower:
                # Tìm context quanh domain này
                idx = output_lower.find(wu_domain)
                ctx = result.stdout[max(0, idx-100):idx+200]
                if "block" in ctx.lower():
                    firewall_info["suspicious_rules"].append({
                        "port":     None,
                        "direction": "Any",
                        "note":     f"Rule BLOCK Windows Update domain '{wu_domain}' — crack tool thường block WU",
                        "raw":      ctx[:300],
                    })
    except Exception:
        pass

    return firewall_info


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

def collect() -> Dict[str, Any]:
    """
    Thu thập toàn bộ thông tin mạng.

    Returns:
        Dict với:
          hostname: tên máy tính
          adapters: list NIC info
          internet: trạng thái internet
          firewall: trạng thái firewall
    """
    result: Dict[str, Any] = {
        "hostname": socket.gethostname(),
        "adapters": [],
        "internet": {},
        "firewall": {},
    }

    # Thu thập adapter info
    result["adapters"] = _get_adapters()

    # Kiểm tra internet
    result["internet"] = _check_internet_connectivity()

    # Kiểm tra firewall
    result["firewall"] = _check_firewall()

    return result
