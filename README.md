```
╔══════════════════════════════════════════════════════════════╗
║          CheckSysHealth v1.0 — System Diagnostic Tool        ║
║           Created by Duli Software & Antigravity             ║
║       Công cụ kiểm tra & kiểm kê hệ thống Windows           ║
╚══════════════════════════════════════════════════════════════╝
```

> **Read-Only** · Không chỉnh sửa hệ thống · Cần quyền Administrator · **Duli Software & Antigravity**

`CheckSysHealth` là bộ công cụ chẩn đoán, kiểm kê phần cứng và phát hiện chuyên sâu các rủi ro bảo mật / dấu hiệu sử dụng phần mềm bẻ khóa (Crack) trên hệ thống Windows.

---

## ⚡ Cài đặt & Khởi chạy nhanh (PowerShell One-Liner)

Chúng tôi cung cấp **2 phiên bản** khởi chạy nhanh qua PowerShell tuỳ thuộc vào nhu cầu của bạn:

### 1️⃣ Phiên bản Độc lập Siêu nhanh — `CheckSysHealth.ps1` (Khuyên dùng)
* 🚀 **Tốc độ siêu nhanh (~3 - 5 giây)** | **Không cần cài Python** | **Không tải thư viện DLL bên thứ ba**.
* Loại bỏ phần đo nhiệt độ CPU/GPU để đạt tốc độ tối đa, sử dụng 100% WMI/CIM thuần túy của Windows.
* Giao diện tiếng Việt không dấu / tiếng Anh chuẩn ASCII (chống lỗi font tuyệt đối trên mọi máy).
* Tự động xuất báo cáo HTML Dark Mode ra Desktop và mở trên trình duyệt.

Mở **PowerShell (Run as Administrator)** và chạy dòng lệnh:
```powershell
irm https://raw.githubusercontent.com/duongbui-drt1/chksyshealth/main/CheckSysHealth.ps1 | iex
```

---

### 2️⃣ Phiên bản Đầy đủ — `run.ps1` (Python + Đo nhiệt độ CPU)
* 🌡️ Tự động tải & tích hợp **LibreHardwareMonitor (LHM)** cùng **CrystalDiskInfo** để đo chi tiết nhiệt độ CPU, GPU và dữ liệu SMART chuyên sâu.
* Tự động kiểm tra Python trên máy (hoặc tải bản Standalone `.exe` nếu chưa có Python).

Mở **PowerShell (Run as Administrator)** và chạy dòng lệnh:
```powershell
irm https://raw.githubusercontent.com/duongbui-drt1/chksyshealth/main/run.ps1 | iex
```

---

## 🛠️ Chạy từ mã nguồn gốc (dành cho Developer)

```bash
# 1. Cài đặt các thư viện yêu cầu
pip install -r requirements.txt

# 2. Khởi chạy trực tiếp (script sẽ tự xin quyền Admin qua UAC)
python checksyshealth.py

# 3. Đóng gói thành file thực thi độc lập (CheckSysHealth.exe)
build.bat
```

---

## 📊 Bảng so sánh tính năng

| Module | Phiên bản Standalone (`CheckSysHealth.ps1`) | Phiên bản Đầy đủ (`run.ps1` / Python) |
| :--- | :--- | :--- |
| **🖥️ CPU** | Tên, hãng, số nhân/luồng, xung nhịp, % tải, Socket | Tên, hãng, nhân/luồng, xung nhịp, % tải, **nhiệt độ từng nhân (qua LHM)** |
| **🔧 Mainboard** | Hãng, model, serial, BIOS version/date, SLIC OEM ID | Hãng, model, serial, BIOS version/date, SLIC OEM ID |
| **🧠 RAM** | Tổng dung lượng, chi tiết từng thanh (Dung lượng, hãng, bus speed, part number, khe cắm) | Tổng dung lượng, chi tiết từng thanh (Dung lượng, hãng, bus speed, part number, khe cắm) |
| **💾 Ổ cứng** | Model, dung lượng, giao tiếp NVMe/SATA, tình trạng SMART (Good/Bad), phân vùng | Model, dung lượng, NVMe/SATA, SMART health%, bad sector, POH, TBW (**qua CrystalDiskInfo**) |
| **🔋 Pin** | Trạng thái pin, % dung lượng ước tính hiện tại | Wear Level%, chu kỳ sạc, dung lượng thiết kế vs hiện tại |
| **🎮 GPU** | Tên card, hãng, dung lượng VRAM, phiên bản Driver, độ phân giải | Tên card, hãng, VRAM, Driver, **nhiệt độ GPU (qua LHM)** |
| **🌐 Mạng** | Danh sách NIC, MAC, IP, DHCP, kiểm tra kết nối Internet | Danh sách NIC, MAC, IP, DHCP, kiểm tra kết nối Internet, cấu hình Firewall |
| **🔑 Bản quyền** | Kiểm tra chi tiết trạng thái kích hoạt Windows & Microsoft Office (OSPP + C2R hybrid) | Kiểm tra chi tiết trạng thái kích hoạt Windows & Microsoft Office (OSPP + C2R hybrid) |
| **🛡️ Quét Crack** | **14 hạng mục quét chuyên sâu** (Windows KMS, Office R2V, KMS Emulator, Tasks, Ports, Registry...) | **14 hạng mục quét chuyên sâu** (Windows KMS, Office R2V, KMS Emulator, Tasks, Ports, Registry...) |
| **📁 Báo cáo** | Tự động tạo báo cáo HTML Dark Mode đẹp mắt tại `Desktop` | Tự động tạo báo cáo HTML Dark Mode đẹp mắt tại `Desktop` |

---

## 🛡️ 14 Phương pháp Kiểm tra Bảo mật & Phát hiện Crack

Bộ công cụ kiểm tra tổng cộng **14 hạng mục** nhằm phát hiện các công cụ kích hoạt trái phép và rủi ro bảo mật:

1. **Hosts file hijacking** — Phát hiện chặn hoặc chuyển hướng các domain kích hoạt của Microsoft (`kms`, `sls`, `ospp`, `msguides`...) trong file `C:\Windows\System32\drivers\etc\hosts`.
2. **Scheduled Tasks** — Phát hiện các tác vụ tự động gia hạn bản quyền bất hợp pháp (`KMSpico`, `AAct`, `KMS_VL_ALL`, `Ohook`, `OSPPHook`...).
3. **KMS Port Listener (Port 1688)** — Phát hiện các tiến trình lạ (không thuộc hệ thống) đang lắng nghe trên cổng 1688 để giả lập máy chủ KMS nội bộ.
4. **Registry Run Keys & Auto-start** — Kiểm tra các khóa khởi động tự động trong Registry (`CurrentVersion\Run`, `Wow6432Node\...\Run`).
5. **Known Crack Paths** — Quét sự tồn tại của các thư mục/file công cụ crack phổ biến (`C:\Program Files\KMSpico`, `AAct Network`, `SECOH-QAD.exe`, `KMS_VL_ALL`...).
6. **Office KMS Emulator** — Kiểm tra địa chỉ máy chủ KMS của Office có bị trỏ ngược về IP nội bộ / Loopback (`127.0.0.1`, `localhost`, `192.168.x.x`...) hay không.
7. **Office Retail-to-Volume Conversion (C2R-R2V)** — Phát hiện dấu hiệu biến đổi bộ cài Office bản lẻ (Retail) sang Volume License trái phép để kích hoạt bằng KMS.
8. **Digital Signature Check** — Kiểm tra tính toàn vẹn và chữ ký số Authenticode của các file hệ thống quan trọng (`sppsvc.exe`, `ospp.vbs`, `OSPPC.DLL`...).
9. **OSPP Cache Injection** — Quét sự thay đổi cấu trúc hoặc tiêm nhiễm token vào thư mục bộ nhớ đệm giấy phép Office (`ohook`, `tokens.dat`).
10. **Windows KMS Emulation** — Kiểm tra `KeyManagementServiceMachine` và cấu hình cổng của SPP Windows.
11. **OOBE Bypass Check** — Kiểm tra khóa cấu hình bỏ qua yêu cầu kết nối mạng khi cài đặt Windows 11 (`BypassNRO`).
12. **System Services Check** — Quét các dịch vụ nền ngầm có tên nghi ngờ (`KMService`, `AutoPico`, `KMSELDI`...).
13. **Unsigned Kernel Drivers** — Thống kê các driver hạt nhân đang chạy nhưng không có chữ ký số hợp lệ.
14. **Crack Environment Variables & Overrides** — Kiểm tra các biến môi trường hoặc khóa Registry ghi đè trạng thái bản quyền (`LicenseStatusOverride`).

---

## 📋 Yêu cầu hệ thống
- **Hệ điều hành**: Windows 10 / Windows 11 (64-bit)
- **Quyền hạn**: Administrator (script tự động yêu cầu quyền qua UAC nếu chưa có)
- **PowerShell**: Version 5.1 trở lên (có sẵn trên mọi máy Windows hiện đại)
- **Python**: 3.8+ (chỉ cần nếu bạn muốn chạy từ mã nguồn gốc hoặc chạy bản `run.ps1` có đo nhiệt độ)

---

## 👥 Tác giả & Bản quyền
Dự án được phát triển bởi **Duli Software & Antigravity**.  
Mọi báo cáo được xuất ra dưới chế độ **Chỉ đọc (Read-Only)**, cam kết không tác động hay sửa đổi bất kỳ tệp tin hay thiết lập nào trên hệ thống của bạn.
