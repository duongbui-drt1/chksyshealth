"""
utils/admin_check.py
Kiểm tra và yêu cầu quyền Administrator thông qua UAC prompt.
Công cụ cần quyền admin để đọc WMI/SMART data đầy đủ.
"""
import ctypes
import sys
import os

# Đảm bảo console Windows không bị crash khi in tiếng Việt (UnicodeEncodeError trên cp1252)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def is_admin() -> bool:
    """
    Kiểm tra xem tiến trình hiện tại đang chạy với quyền Administrator không.
    Dùng Windows API IsUserAnAdmin() qua ctypes.
    """
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> None:
    """
    Re-launch ứng dụng với quyền Administrator thông qua UAC prompt.
    Dùng ShellExecuteW với verb 'runas' để Windows hiện UAC dialog.

    Khi UAC được chấp nhận:
    - Tiến trình mới sẽ chạy với elevated privilege
    - Tiến trình hiện tại (không có quyền) sẽ thoát

    Khi UAC bị từ chối:
    - Hiển thị thông báo lỗi và thoát
    """
    # Lấy đường dẫn executable đang chạy
    # sys.frozen: True khi chạy từ PyInstaller .exe
    if getattr(sys, "frozen", False):
        # Đang chạy từ .exe đóng gói — dùng chính file exe này
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
        work_dir = os.path.dirname(exe)
    else:
        # Đang chạy từ Python script thông thường
        exe = sys.executable
        script = os.path.abspath(sys.argv[0])
        rest = " ".join(f'"{a}"' for a in sys.argv[1:])
        params = f'"{script}" {rest}'
        work_dir = os.path.dirname(script)

    print("[UAC] Đang yêu cầu quyền Administrator...")

    # ShellExecuteW với verb 'runas' → Windows hiện UAC prompt
    ret = ctypes.windll.shell32.ShellExecuteW(
        None,    # hwnd: không có cửa sổ cha
        "runas", # verb: yêu cầu quyền cao hơn
        exe,     # file: executable cần chạy
        params,  # parameters: tham số truyền vào
        work_dir,# directory: thư mục làm việc chuẩn xác
        1        # nShowCmd: SW_SHOWNORMAL = 1
    )

    if ret > 32:
        # UAC được chấp nhận, tiến trình mới đang chạy → thoát tiến trình cũ
        sys.exit(0)
    else:
        # UAC bị từ chối hoặc lỗi
        error_codes = {
            2: "File không tìm thấy",
            3: "Đường dẫn không tìm thấy",
            5: "Truy cập bị từ chối (UAC declined)",
            8: "Không đủ bộ nhớ",
        }
        msg = error_codes.get(ret, f"Lỗi không xác định (code: {ret})")
        print(f"[LỖI] Không thể lấy quyền Administrator: {msg}")
        input("Nhấn Enter để thoát...")
        sys.exit(1)


def ensure_admin() -> None:
    """
    Đảm bảo ứng dụng đang chạy với quyền Administrator.
    Nếu chưa có quyền, tự động kích hoạt UAC prompt và thoát tiến trình hiện tại.
    Gọi hàm này ngay đầu chương trình, trước mọi thao tác khác.
    """
    if not is_admin():
        relaunch_as_admin()
        # Nếu đến đây → re-launch thất bại
        sys.exit(1)
