"""
tools/gpuz_manager.py
Trình quản lý và tự động hóa GPU-Z (TechPowerUp) — công cụ đọc thông tin cấu hình GPU chi tiết nhất.

Luồng hoạt động:
  1. Kiểm tra xem file `GPU-Z.exe` đã có trong cache chưa (%TEMP%/CheckSysHealth/gpuz)
  2. Nếu online và chưa có -> tải xuống bản portable chính thức/mirrors
  3. Chạy `GPU-Z.exe -xml=gpuz_report.xml` (chạy ngầm không hiện cửa sổ)
  4. Phân tích file XML xuất ra để lấy chi tiết cấu hình GPU (Architecture, Shaders, Transistors, Die Size,
     Memory Type, Bus Width, Clock speeds, Subvendor, Temperature, v.v.)
  5. Trả về list các dict GPU để merge vào gpu_collector.
"""
from __future__ import annotations

import os
import sys
import time
import shutil
import tempfile
import zipfile
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Any, List, Optional

from utils.progress import print_step, print_ok, print_warn, make_download_callback

# URLs tải GPU-Z Portable (từ TechPowerUp / tin cậy)
GPUZ_URLS = [
    "https://github.com/duongbui-drt1/chksyshealth-bin/raw/main/GPU-Z.exe",
    "https://us1-dl.techpowerup.com/files/SysInfo/GPU-Z/GPU-Z.2.59.0.exe",
    "https://us2-dl.techpowerup.com/files/SysInfo/GPU-Z/GPU-Z.2.59.0.exe"
]

_CACHE_DIR = Path(tempfile.gettempdir()) / "CheckSysHealth" / "gpuz"


def _get_cached_exe() -> Optional[Path]:
    """Tìm file GPU-Z.exe trong thư mục cache."""
    if not _CACHE_DIR.exists():
        return None
    for name in ["GPU-Z.exe", "gpuz.exe"]:
        p = _CACHE_DIR / name
        if p.exists() and p.stat().st_size > 500_000:
            return p
    return None


def _download_gpuz() -> Optional[Path]:
    """Tải GPU-Z Portable về thư mục cache qua hệ thống mirror TechPowerUp."""
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        return None

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    exe_path = _CACHE_DIR / "GPU-Z.exe"

    print_step("Tải xuống GPU-Z (TechPowerUp Portable Tool)...")
    success = False

    # 1. Thử tải qua cơ chế scrape token động từ TechPowerUp chính chủ
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        s = requests.Session()
        s.headers.update(headers)

        # Bước 1: Vào trang tải chính và lấy version id
        r1 = s.get("https://www.techpowerup.com/download/techpowerup-gpu-z/", timeout=15)
        if r1.status_code == 200:
            soup1 = BeautifulSoup(r1.text, 'html.parser')
            version_inp = soup1.find('input', {'name': 'id'})
            if version_inp and version_inp.get('value'):
                version_id = version_inp['value']

                # Bước 2: POST version id để lấy danh sách mirror server
                r2 = s.post("https://www.techpowerup.com/download/techpowerup-gpu-z/", data={'id': version_id}, timeout=15)
                if r2.status_code == 200:
                    soup2 = BeautifulSoup(r2.text, 'html.parser')
                    # Tìm button server_id (ưu tiên các server ổn định hoặc server đầu tiên tìm thấy)
                    server_btn = soup2.find('button', {'name': 'server_id'})
                    if server_btn and server_btn.get('value'):
                        server_id = server_btn['value']

                        # Bước 3: POST server_id để nhận trực tiếp luồng nhị phân file .exe
                        callback = make_download_callback("GPU-Z")
                        r3 = s.post("https://www.techpowerup.com/download/techpowerup-gpu-z/",
                                    data={'id': version_id, 'server_id': server_id},
                                    stream=True, timeout=30)
                        if r3.status_code == 200:
                            total_size = int(r3.headers.get("content-length", 0))
                            downloaded = 0
                            with open(exe_path, "wb") as f:
                                for chunk in r3.iter_content(chunk_size=16384):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded += len(chunk)
                                        if total_size > 0:
                                            callback(downloaded, total_size)
                            if exe_path.exists() and exe_path.stat().st_size > 500_000:
                                success = True
    except Exception as exc:
        pass

    # 2. Fallback sang danh sách URL trực tiếp nếu scrape lỗi
    if not success:
        for url in GPUZ_URLS:
            try:
                callback = make_download_callback("GPU-Z")
                headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CheckSysHealth/1.0"}
                resp = requests.get(url, headers=headers, stream=True, timeout=15)
                if resp.status_code == 200 and int(resp.headers.get("content-length", 0)) > 500_000:
                    with open(exe_path, "wb") as f:
                        f.write(resp.content)
                    success = True
                    break
            except Exception:
                continue

    if not success or not exe_path.exists():
        print_warn("Không thể tải tự động GPU-Z — sẽ dùng fallback WMI")
        return None

    print_ok(f"GPU-Z sẵn sàng: {exe_path.name}")
    return exe_path


def _parse_gpuz_xml(xml_path: Path) -> List[Dict[str, Any]]:
    """Phân tích file XML xuất ra từ GPU-Z (`-xml=...`)."""
    results: List[Dict[str, Any]] = []
    if not xml_path.exists():
        return results

    try:
        content = xml_path.read_text(encoding="utf-8", errors="replace")
        # Xử lý nếu XML bị lỗi header
        if not content.strip().startswith("<"):
            return results
        root = ET.fromstring(content)
    except Exception:
        return results

    # Mỗi thẻ <card> hoặc con của root đại diện cho một card đồ họa
    cards = root.findall(".//card")
    if not cards and root.tag == "card":
        cards = [root]
    elif not cards:
        cards = [root]

    for c in cards:
        def get_tag(tag_name, default="N/A"):
            el = c.find(tag_name)
            if el is not None and el.text:
                return el.text.strip()
            # Thử tìm theo thuộc tính hoặc lowercase
            for child in c:
                if child.tag.lower() == tag_name.lower() and child.text:
                    return child.text.strip()
            return default

        name = get_tag("cardname", get_tag("name", "Unknown GPU"))
        if "Microsoft Basic Display" in name or name == "Unknown GPU" and len(cards) > 1:
            continue

        gpu_dict = {
            "name": name,
            "architecture": get_tag("architecture", "N/A"),
            "revision": get_tag("revision", "N/A"),
            "die_size": get_tag("diesize", "N/A"),
            "transistors": get_tag("transistors", "N/A"),
            "release_date": get_tag("releasedate", "N/A"),
            "subvendor": get_tag("subvendor", "N/A"),
            "bus_interface": get_tag("businterface", "N/A"),
            "shaders": get_tag("shaders", "N/A"),
            "directx": get_tag("directx", "N/A"),
            "memory_type": get_tag("memorytype", "N/A"),
            "memory_bus_width": get_tag("memorybuswidth", "N/A"),
            "memory_size_str": get_tag("memorysize", "N/A"),
            "gpu_clock": get_tag("gpuclock", "N/A"),
            "memory_clock": get_tag("memoryclock", "N/A"),
            "driver_version": get_tag("driverversion", "N/A"),
        }

        # Thử parse temperature nếu có
        temp_str = get_tag("gpu_temperature", get_tag("temperature", ""))
        if temp_str:
            try:
                gpu_dict["temperature_c"] = float(temp_str.replace("°C", "").strip())
            except ValueError:
                pass

        results.append(gpu_dict)

    return results


def get_gpuz_data(is_online: bool = False) -> List[Dict[str, Any]]:
    """
    Điểm truy cập chính lấy thông tin cấu hình GPU từ GPU-Z.
    """
    exe_path = _get_cached_exe()
    if not exe_path and is_online:
        exe_path = _download_gpuz()

    if not exe_path:
        return []

    print_step("Trích xuất cấu hình GPU chi tiết qua GPU-Z (-xml dump)...")
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    xml_file = _CACHE_DIR / "gpuz_report.xml"
    try:
        if xml_file.exists():
            xml_file.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        # Ghi đè registry để bỏ qua màn hình hỏi Install / Portable của GPU-Z
        try:
            import winreg
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Software\techPowerUp\GPU-Z")
            winreg.SetValueEx(key, "Install_Dir", 0, winreg.REG_SZ, "no")
            winreg.CloseKey(key)
        except Exception:
            pass

        # Chạy ngầm GPU-Z.exe -dump ...
        cmd = [str(exe_path), "-dump", str(xml_file)]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.Popen(
            cmd,
            cwd=str(_CACHE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags
        )

        # Chờ GPU-Z xuất file XML (tối đa 12s)
        start_t = time.time()
        while time.time() - start_t < 12:
            if xml_file.exists() and xml_file.stat().st_size > 300:
                time.sleep(0.5)
                break
            if proc.poll() is not None:
                time.sleep(0.5)
                break
            time.sleep(0.5)

        # Ensure killed
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass

        data = _parse_gpuz_xml(xml_file)
        if data:
            print_ok(f"GPU-Z phát hiện: {len(data)} card đồ họa ({data[0].get('name', '')})")
            return data
        else:
            print_warn("GPU-Z không xuất ra dữ liệu hợp lệ")
            return []

    except Exception as e:
        print_warn(f"Lỗi khi thực thi GPU-Z: {e}")
        return []
