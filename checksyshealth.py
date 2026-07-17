"""
checksyshealth.py
Entry point chính của ứng dụng CheckSysHealth.

Luồng thực thi:
  1. Kiểm tra quyền Administrator → UAC prompt nếu chưa có
  2. Kiểm tra kết nối internet sơ bộ
  3. (Nếu online) Tải LibreHardwareMonitor + CrystalDiskInfo ngầm
  4. Thu thập thông tin từ tất cả collectors (có progress bar)
  5. Tạo HTML report
  6. Lưu report ra Desktop
  7. Mở report trong trình duyệt mặc định

Yêu cầu:
  - Python 3.8+
  - Các thư viện: psutil, wmi, pywin32, colorama, requests (xem requirements.txt)
  - Quyền Administrator (tự xin qua UAC)
  - Windows 10/11

Đóng gói:
  pyinstaller --onefile --uac-admin --name CheckSysHealth checksyshealth.py
"""
import os
import sys
import socket
import webbrowser
import datetime
import traceback
from pathlib import Path

# Đảm bảo console Windows không bị crash khi in tiếng Việt (UnicodeEncodeError trên cp1252)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


# ─── Đảm bảo đường dẫn import đúng khi chạy từ PyInstaller ──────────────────
# Khi đóng gói bằng PyInstaller, sys._MEIPASS chứa thư mục temp của bundle.
# Khi chạy script thông thường, dùng thư mục của script này.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys._MEIPASS)
    # Thêm thư mục base vào sys.path để import được các module
    sys.path.insert(0, str(BASE_DIR))
else:
    BASE_DIR = Path(__file__).parent
    sys.path.insert(0, str(BASE_DIR))

# ─── Bước đầu tiên: kiểm tra và xin quyền admin ──────────────────────────────
# Phải làm trước khi import các module khác để tránh lỗi khi chưa có quyền
from utils.admin_check import ensure_admin
ensure_admin()

# ─── Import sau khi đã có quyền admin ────────────────────────────────────────
import colorama
from utils.progress import (
    print_banner, print_section, print_step, print_ok,
    print_warn, print_error, print_done
)

# Collectors
from collectors import (
    cpu_collector,
    motherboard_collector,
    ram_collector,
    disk_collector,
    battery_collector,
    gpu_collector,
    license_collector,
    network_collector,
)

# Tool managers
from tools import ohm_manager, cdi_manager

# Report builder
from report.html_builder import build_html


# ─── KIỂM TRA INTERNET SƠ BỘ ─────────────────────────────────────────────────

def check_online_quick() -> bool:
    """
    Kiểm tra nhanh kết nối internet (chỉ dùng để quyết định có tải tool không).
    Dùng TCP connect thay vì ICMP để không bị block bởi firewall.
    """
    try:
        sock = socket.create_connection(("8.8.8.8", 53), timeout=3)
        sock.close()
        return True
    except Exception:
        try:
            sock = socket.create_connection(("1.1.1.1", 53), timeout=3)
            sock.close()
            return True
        except Exception:
            return False


# ─── TẢI CHART.JS ─────────────────────────────────────────────────────────────

def get_chartjs(is_online: bool) -> str:
    """
    Lấy nội dung Chart.js để nhúng inline vào HTML report.

    Ưu tiên:
      1. File cache local (từ lần tải trước)
      2. Tải từ CDN nếu online
      3. Trả về rỗng nếu không có (chart sẽ không hiển thị nhưng report vẫn đẹp)
    """
    import tempfile
    cache_path = Path(tempfile.gettempdir()) / "CheckSysHealth" / "chartjs.min.js"

    # Kiểm tra cache
    if cache_path.exists() and cache_path.stat().st_size > 10_000:
        try:
            return cache_path.read_text(encoding="utf-8")
        except Exception:
            pass

    if not is_online:
        return ""

    # Tải từ CDN
    try:
        import requests
        print_step("Tải Chart.js để vẽ biểu đồ")
        cdn_urls = [
            "https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js",
            "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.0/chart.umd.min.js",
        ]
        for url in cdn_urls:
            try:
                resp = requests.get(url, timeout=15)
                if resp.status_code == 200 and len(resp.content) > 10_000:
                    code = resp.text
                    # Lưu cache
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    cache_path.write_text(code, encoding="utf-8")
                    print_ok(f"Chart.js đã tải ({len(code)//1024} KB)")
                    return code
            except Exception:
                continue
    except ImportError:
        pass

    print_warn("Không tải được Chart.js — biểu đồ sẽ không hiển thị")
    return ""


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    """Hàm chính — điều phối toàn bộ luồng thu thập và tạo report."""
    print_banner()

    # ─── 0. Kiểm tra internet ──────────────────────────────────────────────
    print_section("Kiểm tra kết nối")
    is_online = check_online_quick()
    if is_online:
        print_ok("Máy đang có kết nối internet")
    else:
        print_warn("Không có kết nối internet — sẽ bỏ qua các tính năng cần mạng")

    # ─── 1. Tải công cụ ngoài (ngầm nếu online) ───────────────────────────
    sensor_data = {}
    cdi_data    = []

    if is_online:
        print_section("Chuẩn bị công cụ bổ sung")
        # LibreHardwareMonitor — đọc nhiệt độ
        sensor_data = ohm_manager.get_sensor_data(is_online=True)
        # CrystalDiskInfo — đọc SMART chi tiết
        cdi_data = cdi_manager.get_smart_data(is_online=True)
    else:
        # Thử dùng tool đã cache từ lần trước
        sensor_data = ohm_manager.get_sensor_data(is_online=False)
        cdi_data    = cdi_manager.get_smart_data(is_online=False)

    # ─── 2. Thu thập thông tin phần cứng ──────────────────────────────────
    print_section("Thu thập thông tin hệ thống")
    all_data = {}

    total_steps = 8
    step = 0

    step += 1; print_step("CPU", step, total_steps)
    try:
        all_data["cpu"] = cpu_collector.collect(sensor_data=sensor_data)
        print_ok(f"CPU: {all_data['cpu'].get('name','N/A')}")
    except Exception as e:
        print_warn(f"CPU collector lỗi: {e}")
        all_data["cpu"] = {}

    step += 1; print_step("Mainboard & BIOS", step, total_steps)
    try:
        all_data["motherboard"] = motherboard_collector.collect()
        mb = all_data["motherboard"]
        print_ok(f"MB: {mb.get('mb_manufacturer','')} {mb.get('mb_model','')}")
    except Exception as e:
        print_warn(f"Motherboard collector lỗi: {e}")
        all_data["motherboard"] = {}

    step += 1; print_step("RAM", step, total_steps)
    try:
        all_data["ram"] = ram_collector.collect()
        r = all_data["ram"]
        print_ok(f"RAM: {r.get('total_gb',0):.1f} GB ({r.get('slots_used',0)}/{r.get('slots_total',0)} khe)")
    except Exception as e:
        print_warn(f"RAM collector lỗi: {e}")
        all_data["ram"] = {}

    step += 1; print_step("Ổ cứng & SMART", step, total_steps)
    try:
        all_data["disk"] = disk_collector.collect(cdi_data=cdi_data)
        drives = all_data["disk"].get("drives", [])
        print_ok(f"Disk: {len(drives)} ổ đĩa phát hiện")
    except Exception as e:
        print_warn(f"Disk collector lỗi: {e}")
        all_data["disk"] = {"drives": [], "partitions": {}}

    step += 1; print_step("Pin (Battery)", step, total_steps)
    try:
        all_data["battery"] = battery_collector.collect()
        batt = all_data["battery"]
        if batt.get("present"):
            print_ok(f"Battery: {batt.get('charge_pct',0)}% | Wear: {batt.get('wear_level_pct','N/A')}%")
        else:
            print_ok("Battery: Không có pin (Desktop PC)")
    except Exception as e:
        print_warn(f"Battery collector lỗi: {e}")
        all_data["battery"] = {"present": False}

    step += 1; print_step("GPU", step, total_steps)
    try:
        all_data["gpu"] = gpu_collector.collect(sensor_data=sensor_data)
        gpus = all_data["gpu"].get("gpus", [])
        if gpus:
            print_ok(f"GPU: {gpus[0].get('name','N/A')}")
    except Exception as e:
        print_warn(f"GPU collector lỗi: {e}")
        all_data["gpu"] = {"gpus": []}

    step += 1; print_step("Mạng & Firewall", step, total_steps)
    try:
        all_data["network"] = network_collector.collect()
        adps = all_data["network"].get("adapters", [])
        online_str = "Online" if all_data["network"].get("internet", {}).get("online") else "Offline"
        print_ok(f"Network: {len(adps)} adapter | {online_str}")
    except Exception as e:
        print_warn(f"Network collector lỗi: {e}")
        all_data["network"] = {"hostname": socket.gethostname(), "adapters": [], "internet": {}, "firewall": {}}

    step += 1; print_step("Bản quyền & Security Scan", step, total_steps)
    try:
        sys_mfr = all_data.get("motherboard", {}).get("system_manufacturer", "N/A")
        all_data["license"] = license_collector.collect(system_manufacturer=sys_mfr)
        win_lic = all_data["license"].get("windows", {})
        crack   = all_data["license"].get("crack_scan", {})
        print_ok(f"Windows: {win_lic.get('activation_status','N/A')} ({win_lic.get('license_type','N/A')})")
        risk = crack.get("risk_level", "Unknown")
        n    = crack.get("total_findings", 0)
        if risk in ("None", "Low"):
            print_ok(f"Security: Không phát hiện dấu hiệu crack ({n} findings)")
        elif risk == "Medium":
            print_warn(f"Security: {n} phát hiện nghi ngờ (Medium risk)")
        else:
            print_error(f"Security: {n} phát hiện nghi ngờ ({risk} risk)!")
    except Exception as e:
        print_warn(f"License collector lỗi: {e}")
        all_data["license"] = {}

    # ─── 3. Tải Chart.js ──────────────────────────────────────────────────
    print_section("Tạo báo cáo HTML")
    print_step("Tải Chart.js (biểu đồ)")
    chartjs_code = get_chartjs(is_online)

    # ─── 4. Tạo HTML report ───────────────────────────────────────────────
    print_step("Tạo nội dung báo cáo")
    try:
        html_content = build_html(all_data, chartjs_code=chartjs_code)
        print_ok("HTML report đã tạo xong")
    except Exception as e:
        print_error(f"Lỗi tạo HTML report: {e}")
        traceback.print_exc()
        input("Nhấn Enter để thoát...")
        sys.exit(1)

    # ─── 5. Lưu report ────────────────────────────────────────────────────
    now       = datetime.datetime.now()
    hostname  = all_data.get("network", {}).get("hostname", "PC")
    ts_str    = now.strftime("%Y%m%d_%H%M%S")
    filename  = f"CheckSysHealth_{hostname}_{ts_str}.html"

    # Ưu tiên lưu ra Desktop → fallback Documents → thư mục hiện tại
    desktop   = Path.home() / "Desktop"
    documents = Path.home() / "Documents"
    save_dirs = [desktop, documents, Path.cwd()]

    report_path = None
    for save_dir in save_dirs:
        try:
            save_dir.mkdir(parents=True, exist_ok=True)
            report_path = save_dir / filename
            report_path.write_text(html_content, encoding="utf-8")
            break
        except Exception:
            continue

    if report_path is None:
        print_error("Không thể lưu report vào bất kỳ thư mục nào!")
        input("Nhấn Enter để thoát...")
        sys.exit(1)

    print_ok(f"Đã lưu report: {report_path}")

    # ─── 6. Mở trong trình duyệt ──────────────────────────────────────────
    print_done()
    try:
        webbrowser.open(report_path.as_uri())
        print_ok(f"Đã mở trong trình duyệt: {report_path.name}")
    except Exception:
        print_warn(f"Vui lòng mở file thủ công: {report_path}")

    print(f"\n  Nhấn Enter để thoát...")
    input()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  [!] Đã hủy bởi người dùng.")
    except Exception as exc:
        print(f"\n  [LỖI NGHIÊM TRỌNG] {exc}")
        traceback.print_exc()
        input("Nhấn Enter để thoát...")
        sys.exit(1)
    finally:
        # Đảm bảo dọn dẹp LibreHardwareMonitor nếu đang chạy
        try:
            ohm_manager.stop_lhm()
        except Exception:
            pass
