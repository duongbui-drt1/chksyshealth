"""
utils/wmi_helper.py
Helper functions cho WMI (Windows Management Instrumentation) queries.
Bọc tất cả WMI calls trong try/except để tránh crash khi:
  - WMI class không tồn tại trên máy
  - Không đủ quyền đọc namespace cụ thể
  - Dịch vụ WMI (winmgmt) bị lỗi
"""
from __future__ import annotations
from typing import Any, Dict, List, Optional
import wmi


# Cache các kết nối WMI để tránh kết nối lại nhiều lần
# Key: namespace string, Value: wmi.WMI object hoặc None nếu lỗi
_wmi_cache: Dict[str, Optional[wmi.WMI]] = {}


def get_wmi_connection(namespace: str = r"root\cimv2") -> Optional[wmi.WMI]:
    """
    Lấy (hoặc tạo mới) kết nối WMI tới namespace chỉ định.
    Kết nối được cache lại để tái sử dụng.

    Args:
        namespace: WMI namespace, ví dụ 'root\\cimv2', 'root\\wmi', 'root\\LibreHardwareMonitor'

    Returns:
        Đối tượng wmi.WMI hoặc None nếu kết nối thất bại
    """
    global _wmi_cache
    if namespace not in _wmi_cache:
        try:
            _wmi_cache[namespace] = wmi.WMI(namespace=namespace)
        except Exception as exc:
            # Namespace không tồn tại hoặc không có quyền truy cập
            _wmi_cache[namespace] = None
    return _wmi_cache[namespace]


def wmi_query(namespace: str, wql: str) -> List[Any]:
    """
    Thực hiện WMI query (WQL) và trả về kết quả dạng list.
    Trả về list rỗng nếu có lỗi bất kỳ.

    Args:
        namespace: WMI namespace
        wql: Câu lệnh WQL, ví dụ "SELECT * FROM Win32_Processor"

    Returns:
        List các WMI object, hoặc [] nếu lỗi
    """
    conn = get_wmi_connection(namespace)
    if conn is None:
        return []
    try:
        return list(conn.query(wql))
    except Exception:
        return []


def wmi_first(namespace: str, wql: str) -> Optional[Any]:
    """
    Thực hiện WMI query và trả về phần tử đầu tiên.
    Trả về None nếu không có kết quả hoặc lỗi.
    """
    results = wmi_query(namespace, wql)
    return results[0] if results else None


def safe_get(obj: Any, attr: str, default: Any = "N/A") -> Any:
    """
    Lấy giá trị property của WMI object một cách an toàn.
    Trả về default nếu không tìm thấy hoặc giá trị là None/rỗng.

    Ví dụ:
        safe_get(cpu_obj, 'Name')              → 'Intel Core i7'
        safe_get(cpu_obj, 'MaxClockSpeed', 0)  → 3600
    """
    try:
        val = getattr(obj, attr, None)
        if val is None:
            return default
        # Chuẩn hóa: nếu là string rỗng → trả về default
        if isinstance(val, str) and val.strip() == "":
            return default
        return val
    except Exception:
        return default


def clear_cache() -> None:
    """Xóa toàn bộ cache kết nối WMI (dùng khi cần reset)."""
    global _wmi_cache
    _wmi_cache.clear()


def safe_int(obj: Any, attr: str, default: int = 0) -> int:
    """
    Lấy giá trị integer từ WMI object một cách an toàn.
    Trả về default nếu giá trị là None, 'N/A', rỗng, hoặc không phải số.
    """
    val = safe_get(obj, attr, default)
    if val in (None, "N/A", ""):
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def safe_float(obj: Any, attr: str, default: float = 0.0) -> float:
    """
    Lấy giá trị float từ WMI object một cách an toàn.
    Trả về default nếu giá trị không hợp lệ.
    """
    val = safe_get(obj, attr, default)
    if val in (None, "N/A", ""):
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default
