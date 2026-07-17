"""
tools/cpuz_manager.py
Trình quản lý và tự động hóa CPU-Z (CPUID) — công cụ đọc thông tin phần cứng CPU chi tiết nhất.

Luồng hoạt động:
  1. Kiểm tra xem file `cpuz.exe` (hoặc `cpuz64.exe`) đã có trong cache chưa (%TEMP%/CheckSysHealth/cpuz)
  2. Nếu online và chưa có -> tải xuống bản portable ZIP chính thức từ CPUID
  3. Giải nén vào thư mục cache
  4. Chạy `cpuz64.exe -txt=cpuz_report` (chạy ngầm không hiện cửa sổ)
  5. Phân tích file `cpuz_report.txt` để trích xuất toàn bộ cấu trúc CPU (Codename, Package, Technology nm,
     Instructions, L1/L2/L3 Cache, Clock Speeds, Stepping, v.v.)
  6. Trả về dict chi tiết để merge vào cpu_collector.
"""
from __future__ import annotations

import os
import re
import sys
import time
import shutil
import tempfile
import zipfile
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional

from utils.progress import print_step, print_ok, print_warn, make_download_callback

# URLs tải CPU-Z Portable ZIP từ CPUID (thử nhiều phiên bản từ mới nhất xuống)
CPUZ_URLS = [
    "https://download.cpuid.com/cpu-z/cpu-z_2.12-en.zip",
    "https://download.cpuid.com/cpu-z/cpu-z_2.11-en.zip",
    "https://download.cpuid.com/cpu-z/cpu-z_2.10-en.zip"
]

_CACHE_DIR = Path(tempfile.gettempdir()) / "CheckSysHealth" / "cpuz"


def _get_cached_exe() -> Optional[Path]:
    """Tìm file cpuz64.exe hoặc cpuz.exe trong thư mục cache."""
    if not _CACHE_DIR.exists():
        return None
    # Ưu tiên bản 64-bit
    for name in ["cpuz64.exe", "cpuz.exe", "cpuz_x64.exe"]:
        p = _CACHE_DIR / name
        if p.exists() and p.stat().st_size > 100_000:
            return p
    return None


def _download_and_extract() -> Optional[Path]:
    """Tải và giải nén CPU-Z Portable từ CPUID về thư mục cache."""
    try:
        import requests
    except ImportError:
        return None

    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = _CACHE_DIR / "cpuz.zip"

    print_step("Tải xuống CPU-Z (CPUID Portable Tool)...")
    success = False
    for url in CPUZ_URLS:
        try:
            callback = make_download_callback("CPU-Z")
            resp = requests.get(url, stream=True, timeout=15)
            if resp.status_code == 200:
                total_size = int(resp.headers.get("content-length", 0))
                downloaded = 0
                with open(zip_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=16384):
                        if chunk:
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                callback(downloaded, total_size)
                success = True
                break
        except Exception:
            continue

    if not success or not zip_path.exists():
        print_warn("Không thể tải CPU-Z từ máy chủ CPUID — sẽ dùng fallback WMI")
        return None

    print_step("Giải nén CPU-Z...")
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(_CACHE_DIR)
        try:
            zip_path.unlink(missing_ok=True)
        except Exception:
            pass
        exe = _get_cached_exe()
        if exe:
            print_ok(f"CPU-Z sẵn sàng: {exe.name}")
            return exe
    except Exception as e:
        print_warn(f"Lỗi giải nén CPU-Z: {e}")

    return None


def _parse_cpuz_report(report_path: Path) -> Dict[str, Any]:
    """Phân tích file text report xuất ra từ CPU-Z (`-txt=...`)."""
    data: Dict[str, Any] = {}
    if not report_path.exists():
        return data

    try:
        content = report_path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        try:
            content = report_path.read_text(encoding="cp1252", errors="replace")
        except Exception:
            return data

    lines = content.splitlines()
    current_section = ""

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("-----"):
            continue

        # Phát hiện header section: dòng tiếp theo là gạch ngang ("-----")
        if i + 1 < len(lines) and lines[i + 1].strip().startswith("-----"):
            current_section = stripped.lower()
            continue

        # Chỉ phân tích các trường thông tin CPU khi đang ở section liên quan đến Processor / CPU
        if not any(k in current_section for k in ["processor", "cpu"]):
            continue

        if "\t" not in line and "  " not in line:
            continue
        # Split by multiple spaces or tabs
        parts = re.split(r"\t+|\s{2,}", stripped)
        if len(parts) < 2:
            continue
        key = parts[0].strip().lower()
        val = parts[1].strip()

        if key == "specification" and val:
            data["specification"] = val
            data["cpuz_name"] = val  # Specification luôn chính xác và đầy đủ nhất cho tên CPU
        elif key == "name" and "cpuz_name" not in data and val:
            data["cpuz_name"] = val
        elif key == "codename":
            data["codename"] = val
        elif "package" in key or "platform id" in key:
            data["package_socket"] = val
        elif key == "technology":
            data["technology_nm"] = val
        elif key == "core stepping":
            data["stepping"] = val
        elif "instructions" in key:
            data["instructions"] = val
        elif "core speed" in key:
            data["core_speed"] = val
        elif "bus speed" in key:
            data["bus_speed"] = val
        elif "multiplier" in key:
            data["multiplier"] = val
        elif "l1 data cache" in key:
            data["l1_data_cache"] = val
        elif "l1 instruction cache" in key:
            data["l1_inst_cache"] = val
        elif "l2 cache" in key:
            data["l2_cache"] = val
        elif "l3 cache" in key:
            data["l3_cache"] = val
        elif "number of cores" in key:
            m = re.search(r"(\d+)", val)
            if m: data["cores"] = int(m.group(1))
        elif "number of threads" in key:
            m = re.search(r"(\d+)", val)
            if m: data["threads"] = int(m.group(1))

    # Nếu sau khi quét xong mà có specification nhưng cpuz_name bị set bằng name ngắn, gán lại theo specification
    if data.get("specification"):
        data["cpuz_name"] = data["specification"]

    return data


def get_cpuz_data(is_online: bool = False) -> Dict[str, Any]:
    """
    Điểm truy cập chính lấy thông tin CPU từ CPU-Z.
    """
    exe_path = _get_cached_exe()
    if not exe_path and is_online:
        exe_path = _download_and_extract()

    if not exe_path:
        return {}

    print_step("Trích xuất cấu hình CPU chi tiết qua CPU-Z (-txt dump)...")
    report_file = _CACHE_DIR / "cpuz_report.txt"
    try:
        if report_file.exists():
            report_file.unlink(missing_ok=True)
    except Exception:
        pass

    try:
        # Chạy ngầm cpuz -txt=cpuz_report
        cmd = [str(exe_path), "-txt=cpuz_report"]
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        proc = subprocess.Popen(
            cmd,
            cwd=str(_CACHE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags
        )
        
        # Chờ CPU-Z ghi file (tối đa 10s)
        start_t = time.time()
        while time.time() - start_t < 10:
            if report_file.exists() and report_file.stat().st_size > 500:
                # Đợi thêm chút để file ghi xong hoàn toàn
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

        data = _parse_cpuz_report(report_file)
        if data:
            print_ok(f"CPU-Z đọc thành công: {data.get('codename', 'CPU')} ({data.get('technology_nm', '')})")
            return data
        else:
            print_warn("CPU-Z không xuất ra dữ liệu hợp lệ")
            return {}

    except Exception as e:
        print_warn(f"Lỗi khi thực thi CPU-Z: {e}")
        return {}
