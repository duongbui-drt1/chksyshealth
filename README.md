# CheckSysHealth — Công cụ kiểm tra hệ thống Windows

> **Read-Only** · Không chỉnh sửa hệ thống · Cần quyền Administrator

## Tính năng

| Module | Nội dung |
|--------|----------|
| 🖥️ **CPU** | Tên, hãng, nhân/luồng, xung nhịp, nhiệt độ (nếu có LHM), % tải, Processor ID |
| 🔧 **Mainboard** | Hãng, model, serial, BIOS version/date, SLIC OEM ID |
| 🧠 **RAM** | Tổng dung lượng, từng thanh (capacity, hãng, tốc độ, serial, khe) |
| 💾 **Ổ cứng** | Model, dung lượng, NVMe/SATA, SMART health%, bad sector, POH, TBW |
| 🔋 **Pin** | Wear Level%, chu kỳ sạc, dung lượng thiết kế vs hiện tại |
| 🎮 **GPU** | Tên, VRAM, driver version, nhiệt độ (nếu có LHM) |
| 🌐 **Mạng** | NIC hardware (hãng, MAC, driver), IP config, kiểm tra internet, firewall |
| 🔑 **Bản quyền** | Windows/Office/Adobe activation status, license type |
| 🛡️ **Security** | 9 phương pháp phát hiện crack Windows (hosts, task, port, signature, registry...) |

## Cài đặt & Chạy

### Chạy nhanh bằng 1 câu lệnh PowerShell (One-Liner - Khuyên dùng)
Mở PowerShell và chạy dòng lệnh sau (sẽ tự xin quyền Admin, tải về từ GitHub và chạy tự động):
```powershell
irm https://raw.githubusercontent.com/duongbui-drt1/chksyshealth/main/run.ps1 | iex
```

### Chạy từ source (Python)
```bash
# 1. Cài dependencies
pip install -r requirements.txt

# 2. Chạy (sẽ tự xin quyền admin qua UAC)
python checksyshealth.py
```

### Build thành .exe (chạy một lần)
```bash
build.bat
# Output: dist\CheckSysHealth.exe
```

### Chạy .exe
Double-click `CheckSysHealth.exe` → UAC prompt → Accept → chờ ~30-60 giây → báo cáo mở trong trình duyệt.

## Yêu cầu hệ thống
- **OS**: Windows 10/11 (64-bit)
- **Quyền**: Administrator (tự xin qua UAC)
- **Python**: 3.8+ (nếu chạy từ source)
- **.NET**: 4.7.2+ (cần cho LibreHardwareMonitor nếu tải về)
- **Internet**: Tuỳ chọn (để tải LHM + CrystalDiskInfo + Chart.js)

## Các công cụ bổ sung (tự tải nếu online)

| Công cụ | Mục đích | Tải từ |
|---------|----------|--------|
| LibreHardwareMonitor | Đọc nhiệt độ CPU/GPU | GitHub Releases |
| CrystalDiskInfo | SMART data chi tiết | GitHub Releases |
| Chart.js | Biểu đồ trong HTML report | jsDelivr CDN |

Tất cả được tải vào `%TEMP%\CheckSysHealth\` và tự dọn dẹp.

## Cấu trúc dự án

```
CheckSysHealth/
├── checksyshealth.py        # Entry point chính
├── requirements.txt
├── build.bat                # Build PyInstaller
├── collectors/
│   ├── cpu_collector.py
│   ├── motherboard_collector.py
│   ├── ram_collector.py
│   ├── disk_collector.py
│   ├── battery_collector.py
│   ├── gpu_collector.py
│   ├── license_collector.py  # Bản quyền + crack detection
│   └── network_collector.py  # NIC + firewall
├── tools/
│   ├── ohm_manager.py        # LibreHardwareMonitor manager
│   └── cdi_manager.py        # CrystalDiskInfo manager
├── report/
│   └── html_builder.py       # HTML report generator
└── utils/
    ├── admin_check.py
    ├── wmi_helper.py
    └── progress.py
```

## Crack Detection Methods

1. **Hosts file hijacking** — Tìm domain KMS Microsoft bị trỏ về IP nội bộ
2. **Scheduled Task automation** — Task tên/lệnh liên quan KMS/activator
3. **Port 1688 listener** — Process lạ đang mở KMS port
4. **SPP file integrity** — Kiểm tra chữ ký Authenticode của sppsvc.exe, SppExtComObj.dll
5. **Registry tampering** — KMS server registry trỏ về localhost/IP nội bộ
6. **Known crack files** — KMSpico, AAct, RemoveWAT, v.v. tại các path đã biết
7. **Crack services** — Service tên KMService, AutoPico, KMSELDI...
8. **Unsigned kernel drivers** — Driver không có chữ ký số hợp lệ
9. **Registry Run keys** — Crack tool đăng ký tự khởi động

## Giới hạn đã biết

- Nhiệt độ CPU/GPU: cần LibreHardwareMonitor → chỉ có khi online hoặc đã cache
- SMART NVMe qua WMI: ít chi tiết; CrystalDiskInfo cho kết quả đầy đủ hơn
- PSU (nguồn máy bàn): Windows không expose qua API chuẩn → bỏ qua
- Kết quả crack detection là **chỉ số nghi ngờ**, không phải kết luận cuối cùng
