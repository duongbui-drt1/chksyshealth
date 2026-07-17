"""
utils/progress.py
Hiển thị tiến trình và thông báo trong console với màu sắc (dùng colorama).
Tất cả output đều dùng UTF-8 để hiển thị ký tự Unicode (emoji, box drawing).
"""
import sys
import time
from colorama import init, Fore, Back, Style

# Khởi tạo colorama để hỗ trợ ANSI color trên Windows console
init(autoreset=True)

# Đảm bảo stdout/stderr dùng UTF-8 một cách an toàn
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _can_encode(text: str) -> bool:
    try:
        text.encode(sys.stdout.encoding or "utf-8")
        return True
    except (UnicodeEncodeError, LookupError):
        return False


# ─── Ký tự giao diện ─────────────────────────────────────────────────────────
if _can_encode("✓⚠✗→⬇"):
    ICON_OK    = "✓"
    ICON_WARN  = "⚠"
    ICON_ERROR = "✗"
    ICON_SPIN  = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    ICON_ARROW = "→"
    ICON_DOWNLOAD = "⬇"
else:
    ICON_OK    = "[+]"
    ICON_WARN  = "[!]"
    ICON_ERROR = "[-]"
    ICON_SPIN  = ["|", "/", "-", "\\"]
    ICON_ARROW = "->"
    ICON_DOWNLOAD = "[v]"


def print_banner() -> None:
    """In banner ASCII art khi khởi động ứng dụng."""
    banner = f"""
{Fore.CYAN}{Style.BRIGHT}
  ╔══════════════════════════════════════════════════════════════╗
  ║          CheckSysHealth v1.0 — System Diagnostic Tool        ║
  ║      Công cụ kiểm tra & kiểm kê hệ thống Windows            ║
  ║      Chỉ đọc (Read-Only) | Yêu cầu quyền Administrator      ║
  ╚══════════════════════════════════════════════════════════════╝
{Style.RESET_ALL}"""
    print(banner)


def print_section(title: str) -> None:
    """In tiêu đề section với đường kẻ."""
    width = 60
    line = "─" * width
    print(f"\n{Fore.CYAN}{Style.BRIGHT}  {line}")
    print(f"  {ICON_ARROW} {title.upper()}")
    print(f"  {line}{Style.RESET_ALL}")


def print_step(message: str, step: int = 0, total: int = 0) -> None:
    """
    In bước hiện tại đang thực hiện.
    Nếu step và total được cung cấp, hiển thị [step/total].
    """
    prefix = f"[{step}/{total}] " if step and total else ""
    print(f"  {Fore.CYAN}⟳  {prefix}{message}...{Style.RESET_ALL}")


def print_ok(message: str) -> None:
    """In thông báo thành công màu xanh lá."""
    print(f"  {Fore.GREEN}{ICON_OK}  {message}{Style.RESET_ALL}")


def print_warn(message: str) -> None:
    """In cảnh báo màu vàng."""
    print(f"  {Fore.YELLOW}{ICON_WARN}  {message}{Style.RESET_ALL}")


def print_error(message: str) -> None:
    """In thông báo lỗi màu đỏ."""
    print(f"  {Fore.RED}{ICON_ERROR}  {message}{Style.RESET_ALL}")


def print_info(message: str) -> None:
    """In thông tin bình thường màu trắng."""
    print(f"  {Fore.WHITE}   {message}{Style.RESET_ALL}")


def print_progress_bar(
    current: int,
    total: int,
    prefix: str = "Đang tải",
    bar_width: int = 35,
    suffix: str = "",
    end_char: str = "\r"
) -> None:
    """
    Vẽ thanh tiến trình trong console (cập nhật trên cùng 1 dòng).
    Gọi với current == total để hoàn thành và xuống dòng.

    Args:
        current: Số bytes/items đã xử lý
        total: Tổng số bytes/items
        prefix: Text hiển thị trước progress bar
        bar_width: Độ rộng thanh progress (số ký tự)
        suffix: Text hiển thị sau phần trăm
        end_char: Ký tự kết thúc dòng (\\r để ghi đè, \\n để xuống dòng)
    """
    if total <= 0:
        sys.stdout.write(f"\r  {Fore.CYAN}{ICON_DOWNLOAD} {prefix}... {current:,} bytes{Style.RESET_ALL}")
        sys.stdout.flush()
        return

    pct = min(current / total, 1.0)
    filled = int(bar_width * pct)
    bar_filled = "█" * filled
    bar_empty  = "░" * (bar_width - filled)
    pct_str    = f"{int(pct * 100):3d}%"

    # Chọn màu theo % hoàn thành
    if pct < 0.33:
        color = Fore.RED
    elif pct < 0.66:
        color = Fore.YELLOW
    else:
        color = Fore.GREEN

    line = (
        f"\r  {Fore.CYAN}{ICON_DOWNLOAD} {prefix} "
        f"[{color}{bar_filled}{Fore.WHITE}{bar_empty}{Fore.CYAN}] "
        f"{color}{pct_str}{Style.RESET_ALL} {suffix}"
    )
    sys.stdout.write(line)
    sys.stdout.flush()

    if current >= total:
        # Xuống dòng khi hoàn thành
        print()


def make_download_callback(filename: str):
    """
    Tạo callback function cho download streaming.
    Dùng với requests response.iter_content().

    Returns:
        Callable(downloaded_bytes, total_bytes) -> None
    """
    def callback(downloaded: int, total: int) -> None:
        if total > 0:
            suffix = f"({downloaded/1024/1024:.1f} / {total/1024/1024:.1f} MB)"
        else:
            suffix = f"({downloaded/1024/1024:.1f} MB)"
        print_progress_bar(downloaded, total, prefix=f"Tải {filename}", suffix=suffix)

    return callback


def print_done() -> None:
    """In dòng hoàn thành cuối cùng."""
    print(f"\n  {Fore.GREEN}{Style.BRIGHT}{'═' * 60}")
    print(f"  {ICON_OK}  Hoàn tất! Đang mở báo cáo trong trình duyệt...")
    print(f"  {'═' * 60}{Style.RESET_ALL}\n")
