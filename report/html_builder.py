"""
report/html_builder.py
Tạo báo cáo HTML đẹp, responsive, dark/light mode từ dữ liệu đã thu thập.

Thiết kế:
  - Dashboard tổng quan với health cards ở đầu
  - Sections chi tiết cho từng linh kiện
  - Bảng màu cảnh báo (xanh/vàng/đỏ) theo mức health
  - Section bản quyền với icon trạng thái
  - Section security scan với findings
  - Chart.js biểu đồ (hoặc CSS progress bar nếu Chart.js không có)
  - Dark mode / Light mode toggle
  - Nút Print/PDF

Tất cả CSS và JS được nhúng inline (self-contained HTML, hoạt động offline).
"""
from __future__ import annotations

import datetime
import socket
from typing import Dict, Any, Optional


# ─── Màu sắc theo mức độ health ──────────────────────────────────────────────
def _color_class(color: str) -> str:
    return {"good": "status-good", "warn": "status-warn",
            "danger": "status-danger", "unknown": "status-unknown"}.get(color, "status-unknown")

def _health_color(pct: Optional[float]) -> str:
    if pct is None: return "unknown"
    if pct >= 80:   return "good"
    if pct >= 50:   return "warn"
    return "danger"

def _fmt(val: Any, unit: str = "", default: str = "N/A") -> str:
    """Format giá trị với đơn vị, trả về default nếu None/0."""
    if val is None or val == "N/A":
        return default
    if isinstance(val, float):
        return f"{val:,.1f}{unit}"
    if isinstance(val, int) and val == 0:
        return default
    return f"{val}{unit}"

def _status_badge(status: str, color: str = None) -> str:
    """Tạo badge HTML cho trạng thái."""
    if color is None:
        color = _color_class({"Good": "good", "Weak": "warn", "Bad": "danger",
                               "Licensed": "good", "Activated": "good",
                               "Unlicensed": "danger", "Not Activated": "danger"}.get(status, "unknown"))
    return f'<span class="badge {color}">{status}</span>'


# ─── CSS hoàn chỉnh ──────────────────────────────────────────────────────────
_CSS = """
:root {
  --bg:        #0f172a;
  --surface:   #1e293b;
  --surface2:  #334155;
  --border:    #475569;
  --text:      #f1f5f9;
  --text-muted:#94a3b8;
  --accent:    #38bdf8;
  --good:      #4ade80;
  --warn:      #fb923c;
  --danger:    #f87171;
  --good-bg:   rgba(74,222,128,0.12);
  --warn-bg:   rgba(251,146,60,0.12);
  --danger-bg: rgba(248,113,113,0.12);
  --radius:    12px;
  --shadow:    0 4px 24px rgba(0,0,0,0.4);
  font-size:   15px;
}
[data-theme="light"] {
  --bg:        #f0f4f8;
  --surface:   #ffffff;
  --surface2:  #e2e8f0;
  --border:    #cbd5e1;
  --text:      #0f172a;
  --text-muted:#64748b;
  --shadow:    0 4px 24px rgba(0,0,0,0.10);
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{
  font-family:'Segoe UI',system-ui,-apple-system,sans-serif;
  background:var(--bg);color:var(--text);
  line-height:1.6;min-height:100vh;
  transition:background .3s,color .3s;
}
a{color:var(--accent);text-decoration:none}

/* ── Layout ── */
.container{max-width:1200px;margin:0 auto;padding:24px 20px}
.section{margin-bottom:36px}
.section-title{
  font-size:1.1rem;font-weight:700;letter-spacing:.05em;
  text-transform:uppercase;color:var(--text-muted);
  border-left:3px solid var(--accent);padding-left:12px;
  margin-bottom:16px;
}

/* ── Header ── */
.header{
  background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#0f172a 100%);
  border-bottom:1px solid var(--border);
  padding:28px 20px;
  position:sticky;top:0;z-index:100;
}
[data-theme="light"] .header{
  background:linear-gradient(135deg,#1e40af 0%,#3b82f6 50%,#1e40af 100%);
}
.header-inner{
  max-width:1200px;margin:0 auto;
  display:flex;align-items:center;justify-content:space-between;
  flex-wrap:wrap;gap:12px;
}
.header-title{font-size:1.5rem;font-weight:800;color:#fff;letter-spacing:-.02em}
.header-title span{color:var(--accent)}
.header-meta{font-size:.82rem;color:#94a3b8;margin-top:4px}
.header-actions{display:flex;gap:10px;align-items:center}

/* ── Buttons ── */
.btn{
  display:inline-flex;align-items:center;gap:6px;
  padding:8px 16px;border-radius:8px;font-size:.85rem;font-weight:600;
  border:none;cursor:pointer;transition:all .2s;
}
.btn-primary{background:var(--accent);color:#0f172a}
.btn-primary:hover{background:#7dd3fc;transform:translateY(-1px)}
.btn-outline{
  background:transparent;color:var(--text);
  border:1px solid var(--border);
}
.btn-outline:hover{background:var(--surface2)}

/* ── Health Cards ── */
.cards-grid{
  display:grid;
  grid-template-columns:repeat(auto-fit,minmax(180px,1fr));
  gap:16px;margin-bottom:32px;
}
.card{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:20px 18px;
  box-shadow:var(--shadow);transition:transform .2s,box-shadow .2s;
  position:relative;overflow:hidden;
}
.card:hover{transform:translateY(-3px);box-shadow:0 8px 32px rgba(0,0,0,.5)}
.card::before{
  content:'';position:absolute;top:0;left:0;right:0;height:3px;
  background:var(--accent-color,var(--accent));
}
.card.good::before{--accent-color:var(--good)}
.card.warn::before{--accent-color:var(--warn)}
.card.danger::before{--accent-color:var(--danger)}
.card-icon{font-size:1.8rem;margin-bottom:8px}
.card-label{font-size:.78rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em}
.card-value{font-size:1.8rem;font-weight:800;line-height:1;margin:4px 0}
.card-sub{font-size:.8rem;color:var(--text-muted);margin-top:4px}
.card.good .card-value{color:var(--good)}
.card.warn .card-value{color:var(--warn)}
.card.danger .card-value{color:var(--danger)}
.card.unknown .card-value{color:var(--text-muted)}

/* ── Progress Bar ── */
.progress-wrap{margin:8px 0}
.progress-label{
  display:flex;justify-content:space-between;
  font-size:.78rem;color:var(--text-muted);margin-bottom:4px;
}
.progress{background:var(--surface2);border-radius:999px;height:8px;overflow:hidden}
.progress-fill{
  height:100%;border-radius:999px;
  transition:width 1s cubic-bezier(.4,0,.2,1);
  background:linear-gradient(90deg,var(--fill-start),var(--fill-end));
}
.progress-fill.good{--fill-start:#22c55e;--fill-end:#4ade80}
.progress-fill.warn{--fill-start:#f97316;--fill-end:#fb923c}
.progress-fill.danger{--fill-start:#dc2626;--fill-end:#f87171}
.progress-fill.unknown{--fill-start:#64748b;--fill-end:#94a3b8}

/* ── Detail Panels ── */
.panel{
  background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);box-shadow:var(--shadow);
  overflow:hidden;margin-bottom:16px;
}
.panel-header{
  padding:14px 20px;
  background:var(--surface2);
  border-bottom:1px solid var(--border);
  display:flex;align-items:center;gap:10px;
  font-weight:700;font-size:.95rem;
}
.panel-body{padding:20px}
.panel-grid{
  display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));
  gap:12px 24px;
}
.info-row{display:flex;flex-direction:column;gap:2px}
.info-label{font-size:.75rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.05em}
.info-value{font-size:.92rem;font-weight:500}

/* ── Tables ── */
.table-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:.87rem}
th{
  background:var(--surface2);color:var(--text-muted);
  font-size:.75rem;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;padding:10px 14px;
  text-align:left;white-space:nowrap;
}
td{padding:10px 14px;border-bottom:1px solid var(--border)}
tr:last-child td{border-bottom:none}
tr:hover td{background:var(--surface2)}
.tr-good td{background:var(--good-bg)}
.tr-warn td{background:var(--warn-bg)}
.tr-danger td{background:var(--danger-bg)}

/* ── Badges ── */
.badge{
  display:inline-flex;align-items:center;gap:4px;
  padding:3px 10px;border-radius:999px;
  font-size:.75rem;font-weight:700;
}
.status-good{background:var(--good-bg);color:var(--good);border:1px solid rgba(74,222,128,.3)}
.status-warn{background:var(--warn-bg);color:var(--warn);border:1px solid rgba(251,146,60,.3)}
.status-danger{background:var(--danger-bg);color:var(--danger);border:1px solid rgba(248,113,113,.3)}
.status-unknown{background:rgba(148,163,184,.1);color:var(--text-muted);border:1px solid var(--border)}

/* ── Findings list ── */
.finding{
  border-radius:8px;padding:14px 16px;margin-bottom:10px;
  border-left:4px solid var(--sev-color);
  background:var(--sev-bg);
}
.finding.sev-Critical{--sev-color:var(--danger);--sev-bg:var(--danger-bg)}
.finding.sev-High{--sev-color:var(--warn);--sev-bg:var(--warn-bg)}
.finding.sev-Medium{--sev-color:#a78bfa;--sev-bg:rgba(167,139,250,.1)}
.finding.sev-Low{--sev-color:var(--good);--sev-bg:var(--good-bg)}
.finding-title{font-weight:700;font-size:.9rem;margin-bottom:4px}
.finding-desc{font-size:.82rem;color:var(--text-muted);margin-bottom:4px}
.finding-evidence{
  font-family:'Cascadia Code','Consolas',monospace;
  font-size:.75rem;color:var(--accent);
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  max-width:100%;
}
.sev-pill{
  display:inline-block;padding:2px 8px;border-radius:4px;
  font-size:.7rem;font-weight:800;text-transform:uppercase;
  margin-left:8px;
}
.sev-Critical .sev-pill{background:var(--danger);color:#fff}
.sev-High     .sev-pill{background:var(--warn);color:#0f172a}
.sev-Medium   .sev-pill{background:#a78bfa;color:#0f172a}
.sev-Low      .sev-pill{background:var(--good);color:#0f172a}

/* ── Charts ── */
.chart-row{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:20px;margin-bottom:24px}
.chart-box{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:20px;text-align:center}
.chart-box h4{font-size:.8rem;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px}
.chart-container{position:relative;max-width:180px;margin:0 auto}

/* ── Alerts ── */
.alert{
  padding:14px 16px;border-radius:8px;margin-bottom:16px;
  display:flex;align-items:flex-start;gap:12px;
}
.alert-success{background:var(--good-bg);border:1px solid rgba(74,222,128,.3);color:var(--good)}
.alert-warning{background:var(--warn-bg);border:1px solid rgba(251,146,60,.3);color:var(--warn)}
.alert-danger{background:var(--danger-bg);border:1px solid rgba(248,113,113,.3);color:var(--danger)}

/* ── SMART table ── */
.smart-grid{
  display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
  gap:8px;margin-top:12px;
}
.smart-item{
  background:var(--surface2);border-radius:6px;padding:10px 12px;
  font-size:.8rem;
}
.smart-item-name{color:var(--text-muted);font-size:.72rem;margin-bottom:2px}
.smart-item-val{font-weight:700;font-size:.95rem}

/* ── Print ── */
@media print {
  .header-actions,.btn{display:none!important}
  .header{position:relative}
  body{background:#fff;color:#000}
  .card,.panel{box-shadow:none;border:1px solid #ccc}
}

/* ── Animations ── */
@keyframes fadeIn{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:translateY(0)}}
.section{animation:fadeIn .4s ease both}

/* ── Summary banner ── */
.summary-banner{
  background:linear-gradient(135deg,#1e293b,#0f2d4a);
  border:1px solid var(--border);border-radius:var(--radius);
  padding:20px;margin-bottom:28px;
  display:flex;align-items:center;gap:16px;flex-wrap:wrap;
}
[data-theme="light"] .summary-banner{background:linear-gradient(135deg,#dbeafe,#bfdbfe)}
.summary-stat{text-align:center;min-width:80px}
.summary-stat-val{font-size:1.5rem;font-weight:800}
.summary-stat-label{font-size:.72rem;color:var(--text-muted);text-transform:uppercase}
.summary-divider{width:1px;height:48px;background:var(--border)}
"""


# ─── JavaScript (dark mode toggle + Chart.js loader + animations) ─────────────
_JS = """
// Dark/Light mode toggle
function toggleTheme() {
  const html = document.documentElement;
  const current = html.getAttribute('data-theme');
  const next = current === 'light' ? 'dark' : 'light';
  html.setAttribute('data-theme', next);
  document.getElementById('themeIcon').textContent = next === 'light' ? '🌙' : '☀️';
  localStorage.setItem('checksyshealth-theme', next);
}
// Khôi phục theme từ localStorage
const savedTheme = localStorage.getItem('checksyshealth-theme');
if (savedTheme === 'light') {
  document.documentElement.setAttribute('data-theme', 'light');
  document.addEventListener('DOMContentLoaded', () => {
    const icon = document.getElementById('themeIcon');
    if (icon) icon.textContent = '☀️';
  });
}

// Animate progress bars khi vào viewport
const observer = new IntersectionObserver((entries) => {
  entries.forEach(entry => {
    if (entry.isIntersecting) {
      const fill = entry.target.querySelector('.progress-fill');
      if (fill) {
        const target = fill.getAttribute('data-width');
        fill.style.width = target + '%';
      }
      observer.unobserve(entry.target);
    }
  });
}, { threshold: 0.1 });

document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.progress').forEach(p => {
    const fill = p.querySelector('.progress-fill');
    if (fill) {
      fill.style.width = '0%';  // reset before animation
      observer.observe(p);
    }
  });
  initCharts();
});

// Chart.js initialization
function initCharts() {
  if (typeof Chart === 'undefined') {
    // Chart.js không có — fallback graceful
    document.querySelectorAll('.chart-container').forEach(c => {
      c.innerHTML = '<p style="color:var(--text-muted);font-size:.8rem">Biểu đồ không khả dụng</p>';
    });
    return;
  }
  Chart.defaults.color = getComputedStyle(document.documentElement)
    .getPropertyValue('--text-muted').trim() || '#94a3b8';

  // Khởi tạo từng chart từ data-* attributes
  document.querySelectorAll('canvas[data-chart]').forEach(canvas => {
    const type  = canvas.getAttribute('data-chart');
    const value = parseFloat(canvas.getAttribute('data-value') || '0');
    const color = canvas.getAttribute('data-color') || '#38bdf8';
    const label = canvas.getAttribute('data-label') || '';

    if (type === 'doughnut') {
      new Chart(canvas, {
        type: 'doughnut',
        data: {
          datasets: [{
            data: [value, 100 - value],
            backgroundColor: [color, 'rgba(255,255,255,0.08)'],
            borderWidth: 0,
          }]
        },
        options: {
          cutout: '72%',
          plugins: {
            legend: { display: false },
            tooltip: {
              callbacks: {
                label: (ctx) => ctx.dataIndex === 0 ? `${value.toFixed(0)}%` : ''
              }
            }
          },
          animation: { animateRotate: true, duration: 1200 }
        }
      });
      // Overlay text
      const wrap = canvas.parentElement;
      const overlay = document.createElement('div');
      overlay.style.cssText = 'position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);text-align:center;pointer-events:none';
      overlay.innerHTML = `<div style="font-size:1.3rem;font-weight:800;color:${color}">${value.toFixed(0)}%</div><div style="font-size:.65rem;color:var(--text-muted)">${label}</div>`;
      wrap.appendChild(overlay);
    }
  });
}

// Print
function printReport() { window.print(); }

// Collapsible sections
document.addEventListener('click', (e) => {
  const toggle = e.target.closest('[data-collapse]');
  if (toggle) {
    const target = document.getElementById(toggle.getAttribute('data-collapse'));
    if (target) {
      const hidden = target.style.display === 'none';
      target.style.display = hidden ? '' : 'none';
      toggle.querySelector('.collapse-icon').textContent = hidden ? '▲' : '▼';
    }
  }
});
"""


# ─── Các hàm tạo section HTML ────────────────────────────────────────────────

def _progress_bar(pct: Optional[float], label: str = "", show_pct: bool = True) -> str:
    """Tạo progress bar với animation."""
    if pct is None:
        pct_val   = 0
        color_cls = "unknown"
        pct_str   = "N/A"
    else:
        pct_val   = min(max(float(pct), 0), 100)
        color_cls = _health_color(pct_val)
        pct_str   = f"{pct_val:.0f}%"

    label_html = f'<span>{label}</span>' if label else ''
    pct_html   = f'<span>{pct_str}</span>' if show_pct else ''
    return f"""
<div class="progress-wrap">
  <div class="progress-label">{label_html}{pct_html}</div>
  <div class="progress">
    <div class="progress-fill {color_cls}" data-width="{pct_val:.0f}" style="width:{pct_val:.0f}%"></div>
  </div>
</div>"""


def _doughnut_chart(value: Optional[float], label: str, color: str = "#38bdf8") -> str:
    """Tạo doughnut chart với Chart.js."""
    val = value if value is not None else 0
    color_map = {"good": "#4ade80", "warn": "#fb923c", "danger": "#f87171", "unknown": "#64748b"}
    clr = color_map.get(_health_color(val), "#38bdf8")
    return f"""
<div class="chart-box">
  <h4>{label}</h4>
  <div class="chart-container" style="position:relative">
    <canvas data-chart="doughnut" data-value="{val:.0f}" data-color="{clr}" data-label="{label}" width="180" height="180"></canvas>
  </div>
</div>"""


def _info_row(label: str, value: Any, unit: str = "") -> str:
    val_str = _fmt(value, unit) if value not in (None, "N/A", "", 0) else "N/A"
    return f"""
<div class="info-row">
  <div class="info-label">{label}</div>
  <div class="info-value">{val_str}</div>
</div>"""


# ─── SECTIONS ────────────────────────────────────────────────────────────────

def _build_summary_cards(data: Dict) -> str:
    """Dashboard cards tổng quan ở đầu báo cáo."""
    cpu    = data.get("cpu", {})
    ram    = data.get("ram", {})
    disks  = data.get("disk", {}).get("drives", [])
    batt   = data.get("battery", {})
    net    = data.get("network", {})

    cpu_load  = cpu.get("load_pct", 0)
    cpu_color = "warn" if cpu_load > 80 else "good" if cpu_load < 60 else "warn"

    ram_pct   = ram.get("used_pct", 0)
    ram_color = _health_color(100 - ram_pct)  # Đảo: RAM dùng ít = tốt

    # Lấy ổ SSD chính (ổ đầu tiên)
    disk_health = None
    disk_color  = "unknown"
    if disks:
        disk_health = disks[0].get("health_pct")
        disk_color  = disks[0].get("health_color", "unknown")

    # Pin
    wear     = batt.get("wear_level_pct") if batt.get("present") else None
    batt_color = batt.get("status_color", "unknown")

    # Internet
    online    = net.get("internet", {}).get("online", False)
    net_color = "good" if online else "warn"
    net_label = "Online" if online else "Offline"

    def card(icon, label, value, sub, color):
        return f"""
<div class="card {color}">
  <div class="card-icon">{icon}</div>
  <div class="card-label">{label}</div>
  <div class="card-value">{value}</div>
  <div class="card-sub">{sub}</div>
</div>"""

    cpu_name_short = cpu.get("name", "CPU").split("@")[0].strip()[:25]
    ram_total_str  = f"{ram.get('total_gb', 0):.0f} GB"
    disk_str       = f"{disk_health:.0f}%" if disk_health is not None else "N/A"
    batt_str       = f"{wear:.0f}%" if wear is not None else ("N/A" if batt.get("present") else "Desktop")
    ping_ms        = net.get("internet", {}).get("ping_ms")
    net_str        = f"{ping_ms:.0f}ms" if ping_ms else net_label

    return f"""
<div class="cards-grid">
  {card("🖥️", "CPU Load", f"{cpu_load:.0f}%", cpu_name_short, cpu_color)}
  {card("🧠", "RAM Used", f"{ram_pct:.0f}%", f"{ram.get('used_gb',0):.1f} / {ram_total_str}", ram_color)}
  {card("💾", "Disk Health", disk_str, disks[0].get('model','')[:25] if disks else 'N/A', disk_color)}
  {card("🔋", "Battery Wear", batt_str, batt.get('status','N/A') if batt.get('present') else 'No battery', batt_color)}
  {card("🌐", "Network", net_str, net_label, net_color)}
</div>"""


def _build_cpu_section(cpu: Dict) -> str:
    temp_c = cpu.get("temperature_c")
    temp_str = f"{temp_c}°C" if temp_c is not None else "N/A (cần LHM)"
    temp_color = cpu.get("temp_status", "unknown")

    return f"""
<div class="section">
  <div class="section-title">🖥️ CPU — Bộ vi xử lý</div>
  <div class="panel">
    <div class="panel-header">
      <span>⚙️</span>
      <span>{cpu.get('name','N/A')}</span>
      <span style="margin-left:auto">{_status_badge(cpu.get('temp_status','unknown').title(), _color_class(cpu.get('temp_status','unknown')))}</span>
    </div>
    <div class="panel-body">
      <div class="panel-grid">
        {_info_row("Hãng sản xuất", cpu.get('manufacturer'))}
        {_info_row("Số nhân / Luồng", f"{cpu.get('cores',0)} nhân / {cpu.get('threads',0)} luồng")}
        {_info_row("Xung nhịp cơ bản", cpu.get('base_clock_mhz'), " MHz")}
        {_info_row("Xung nhịp hiện tại", cpu.get('current_clock_mhz'), " MHz")}
        {_info_row("Cache L2", cpu.get('l2_cache_kb'), " KB")}
        {_info_row("Cache L3", cpu.get('l3_cache_kb'), " KB")}
        {_info_row("Socket", cpu.get('socket'))}
        {_info_row("Kiến trúc", cpu.get('architecture'))}
        {_info_row("Processor ID", cpu.get('processor_id'))}
      </div>
      <hr style="border-color:var(--border);margin:16px 0">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
        <div>
          {_progress_bar(cpu.get('load_pct'), "Tải CPU hiện tại")}
          <div style="font-size:.78rem;color:var(--text-muted)">{cpu.get('load_pct',0):.1f}% utilization</div>
        </div>
        <div>
          <div class="progress-label"><span>Nhiệt độ</span><span class="{_color_class(temp_color)}">{temp_str}</span></div>
          {_progress_bar(((temp_c or 50) / 100) * 100 if temp_c else None, "", show_pct=False) if temp_c else '<div style="color:var(--text-muted);font-size:.8rem;margin-top:8px">Cần LibreHardwareMonitor để đọc nhiệt độ</div>'}
        </div>
      </div>
    </div>
  </div>
</div>"""


def _build_ram_section(ram: Dict) -> str:
    sticks = ram.get("sticks", [])
    used_pct = ram.get("used_pct", 0)

    stick_rows = ""
    for s in sticks:
        stick_rows += f"""
<tr>
  <td>{s.get('slot','N/A')}</td>
  <td><strong>{s.get('capacity_gb',0):.0f} GB</strong></td>
  <td>{s.get('manufacturer','N/A')}</td>
  <td>{s.get('memory_type','N/A')}</td>
  <td>{s.get('speed_mhz',0)} MHz</td>
  <td style="font-family:monospace;font-size:.8rem">{s.get('part_number','N/A')}</td>
  <td style="font-family:monospace;font-size:.75rem">{s.get('serial','N/A')}</td>
</tr>"""

    return f"""
<div class="section">
  <div class="section-title">🧠 RAM — Bộ nhớ</div>
  <div class="panel">
    <div class="panel-header">
      <span>💾</span>
      <span>{ram.get('total_gb',0):.1f} GB Total — {ram.get('slots_used',0)}/{ram.get('slots_total',0)} khe đang dùng</span>
    </div>
    <div class="panel-body">
      <div style="margin-bottom:16px">
        {_progress_bar(used_pct, f"RAM đang dùng: {ram.get('used_gb',0):.1f} GB / {ram.get('total_gb',0):.1f} GB")}
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Khe</th><th>Dung lượng</th><th>Hãng</th><th>Loại</th><th>Tốc độ</th><th>Part Number</th><th>Serial</th></tr></thead>
          <tbody>{stick_rows if stick_rows else '<tr><td colspan="7" style="text-align:center;color:var(--text-muted)">Không đọc được thông tin thanh RAM</td></tr>'}</tbody>
        </table>
      </div>
    </div>
  </div>
</div>"""


def _build_disk_section(disk_data: Dict) -> str:
    drives     = disk_data.get("drives", [])
    partitions = disk_data.get("partitions", {})

    drives_html = ""
    for drv in drives:
        health_pct  = drv.get("health_pct")
        health_str  = f"{health_pct:.0f}%" if health_pct is not None else "N/A"
        health_clr  = drv.get("health_color", "unknown")
        poh         = drv.get("power_on_hours")
        temp        = drv.get("temperature_c")
        tbw         = drv.get("tbw_gb")
        bad_sectors = drv.get("bad_sectors", 0)
        source      = drv.get("source", "WMI")

        tbw_str = f"{tbw/1024:.2f} TB" if tbw and tbw >= 1024 else (f"{tbw:.1f} GB" if tbw else "N/A")
        poh_str = f"{poh:,} giờ" if poh else "N/A"
        temp_str = f"{temp}°C" if temp else "N/A"

        bad_html = f'<span class="badge status-danger">⚠ {bad_sectors} bad sectors</span>' if bad_sectors and bad_sectors > 0 else '<span class="badge status-good">✓ Không có bad sector</span>'

        drives_html += f"""
<div class="panel" style="margin-bottom:12px">
  <div class="panel-header">
    <span>{'💿' if drv.get('interface')=='NVMe' else '🖥️'}</span>
    <span>{drv.get('model','Unknown')}</span>
    <span style="margin-left:auto;font-size:.8rem;color:var(--text-muted)">{drv.get('interface','N/A')} · {source}</span>
  </div>
  <div class="panel-body">
    <div class="panel-grid">
      {_info_row("Dung lượng", f"{drv.get('size_gb',0):.1f} GB")}
      {_info_row("Giao tiếp", drv.get('interface'))}
      {_info_row("Serial Number", drv.get('serial'))}
      {_info_row("Firmware", drv.get('firmware'))}
      {_info_row("Nhiệt độ", temp_str)}
      {_info_row("Số giờ hoạt động", poh_str)}
      {_info_row("Tổng dữ liệu ghi (TBW)", tbw_str)}
    </div>
    <div style="margin:16px 0">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:8px">
        <strong>Tình trạng SMART:</strong>
        {_status_badge(drv.get('health_status','Unknown'), _color_class(health_clr))}
        {bad_html}
      </div>
      {_progress_bar(health_pct, f"Độ khỏe: {health_str}")}
    </div>
  </div>
</div>"""

    # Partition table
    part_rows = ""
    for dev, part in partitions.items():
        pct = part.get("used_pct", 0)
        color = "good" if pct < 80 else "warn" if pct < 90 else "danger"
        part_rows += f"""
<tr class="tr-{color}">
  <td><strong>{part.get('mountpoint','N/A')}</strong></td>
  <td>{dev}</td>
  <td>{part.get('fstype','N/A')}</td>
  <td>{part.get('total_gb',0):.1f} GB</td>
  <td>{part.get('used_gb',0):.1f} GB</td>
  <td>{part.get('free_gb',0):.1f} GB</td>
  <td><span class="badge status-{color}">{pct:.0f}%</span></td>
</tr>"""

    return f"""
<div class="section">
  <div class="section-title">💾 Ổ cứng (HDD/SSD)</div>
  {drives_html if drives_html else '<div class="panel"><div class="panel-body">Không phát hiện ổ đĩa</div></div>'}
  {'<div class="panel"><div class="panel-header"><span>📁</span><span>Phân vùng</span></div><div class="panel-body"><div class="table-wrap"><table><thead><tr><th>Ổ</th><th>Device</th><th>FS</th><th>Tổng</th><th>Đã dùng</th><th>Còn trống</th><th>%</th></tr></thead><tbody>' + part_rows + '</tbody></table></div></div></div>' if part_rows else ''}
</div>"""


def _build_battery_section(batt: Dict) -> str:
    if not batt.get("present"):
        return f"""
<div class="section">
  <div class="section-title">🔋 Pin (Battery)</div>
  <div class="alert alert-success">
    <span>🖥️</span>
    <span>Máy tính này không có pin (Desktop PC hoặc pin đã tháo).</span>
  </div>
</div>"""

    wear       = batt.get("wear_level_pct")
    wear_str   = f"{wear:.1f}%" if wear is not None else "N/A"
    design_mwh = batt.get("design_capacity_mwh", 0)
    full_mwh   = batt.get("full_charge_mwh", 0)
    design_wh  = design_mwh / 1000 if design_mwh else 0
    full_wh    = full_mwh / 1000 if full_mwh else 0
    cycles     = batt.get("cycle_count")
    status_clr = batt.get("status_color", "unknown")

    return f"""
<div class="section">
  <div class="section-title">🔋 Pin (Battery)</div>
  <div class="panel">
    <div class="panel-header">
      <span>🔋</span>
      <span>{batt.get('name','Battery')}</span>
      <span style="margin-left:auto">{_status_badge(batt.get('status','N/A'), _color_class(status_clr))}</span>
    </div>
    <div class="panel-body">
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:24px;align-items:start">
        <div>
          <div class="panel-grid" style="margin-bottom:16px">
            {_info_row("Pin hiện tại", f"{batt.get('charge_pct',0)}%")}
            {_info_row("Dung lượng thiết kế", f"{design_wh:.1f} Wh" if design_wh else "N/A")}
            {_info_row("Dung lượng hiện tại (đầy)", f"{full_wh:.1f} Wh" if full_wh else "N/A")}
            {_info_row("Wear Level (còn lại)", wear_str)}
            {_info_row("Số chu kỳ sạc", str(cycles) if cycles is not None else "N/A")}
            {_info_row("Đang sạc", "Có" if batt.get('is_charging') else "Không")}
          </div>
          {_progress_bar(batt.get('charge_pct'), "Pin hiện tại")}
          {_progress_bar(wear, f"Sức khỏe pin (Wear Level): {wear_str}")}
        </div>
        <div>
          {_doughnut_chart(wear, "Battery Health", "#4ade80" if (wear or 0)>=80 else "#fb923c" if (wear or 0)>=50 else "#f87171")}
        </div>
      </div>
    </div>
  </div>
</div>"""


def _build_gpu_section(gpu_data: Dict) -> str:
    gpus = gpu_data.get("gpus", [])
    if not gpus:
        return ""

    panels = ""
    for gpu in gpus:
        temp = gpu.get("temperature_c")
        temp_str = f"{temp}°C" if temp is not None else "N/A"
        load = gpu.get("load_pct")
        panels += f"""
<div class="panel" style="margin-bottom:12px">
  <div class="panel-header"><span>🎮</span><span>{gpu.get('name','Unknown GPU')}</span></div>
  <div class="panel-body">
    <div class="panel-grid">
      {_info_row("VRAM", gpu.get('vram_str','N/A'))}
      {_info_row("Driver Version", gpu.get('driver_version','N/A'))}
      {_info_row("Driver Date", gpu.get('driver_date','N/A'))}
      {_info_row("Resolution", gpu.get('resolution','N/A'))}
      {_info_row("Nhiệt độ GPU", temp_str)}
      {_info_row("Tải GPU", f"{load:.0f}%" if load is not None else "N/A")}
    </div>
  </div>
</div>"""

    return f"""
<div class="section">
  <div class="section-title">🎮 GPU — Card đồ họa</div>
  {panels}
</div>"""


def _build_network_section(net: Dict) -> str:
    adapters = net.get("adapters", [])
    internet = net.get("internet", {})
    firewall = net.get("firewall", {})

    online    = internet.get("online", False)
    ping_ms   = internet.get("ping_ms")
    inet_html = f"""
<div class="alert {'alert-success' if online else 'alert-warning'}">
  <span>{'✅' if online else '⚠️'}</span>
  <div>
    <strong>{'Kết nối Internet: OK' if online else 'Không có kết nối Internet'}</strong><br>
    <span style="font-size:.82rem">{'Latency: ' + str(ping_ms) + 'ms tới ' + internet.get('ping_target','') if ping_ms else 'Không ping được'}</span>
  </div>
</div>"""

    # Firewall status
    fw_all = firewall.get("all_enabled", False)
    fw_html = f"""
<div class="panel" style="margin-bottom:12px">
  <div class="panel-header"><span>🛡️</span><span>Windows Firewall</span>
    <span style="margin-left:auto">{_status_badge('Bật' if fw_all else 'Tắt/Một phần', _color_class('good' if fw_all else 'warn'))}</span>
  </div>
  <div class="panel-body">
    <div class="panel-grid">
      {_info_row("Domain Profile", firewall.get('domain_profile','N/A'))}
      {_info_row("Private Profile", firewall.get('private_profile','N/A'))}
      {_info_row("Public Profile", firewall.get('public_profile','N/A'))}
    </div>"""

    susp_rules = firewall.get("suspicious_rules", [])
    if susp_rules:
        fw_html += f"""
    <div style="margin-top:12px">
      <strong style="color:var(--warn)">⚠️ {len(susp_rules)} rule nghi ngờ:</strong>
"""
        for rule in susp_rules:
            fw_html += f"""
      <div class="finding sev-Medium" style="margin-top:8px">
        <div class="finding-title">{rule.get('note','')}</div>
      </div>"""
    fw_html += "</div></div></div>"

    # Adapter list
    adapter_html = ""
    for adp in adapters:
        if adp.get("status") == "Connected" or adp.get("ip4") != "N/A":
            adapter_html += f"""
<div class="panel" style="margin-bottom:10px">
  <div class="panel-header">
    <span>{'📶' if adp.get('type')=='Wi-Fi' else '🔌'}</span>
    <span>{adp.get('name','N/A')}</span>
    <span style="margin-left:auto">{_status_badge(adp.get('status','N/A'), _color_class('good' if adp.get('status')=='Connected' else 'unknown'))}</span>
  </div>
  <div class="panel-body">
    <div class="panel-grid">
      {_info_row("Loại", adp.get('type','N/A'))}
      {_info_row("Hãng sản xuất NIC", adp.get('manufacturer','N/A'))}
      {_info_row("MAC Address", adp.get('mac','N/A'))}
      {_info_row("Driver Version", adp.get('driver_ver','N/A'))}
      {_info_row("Tốc độ", f"{adp.get('speed_mbps',0):.0f} Mbps" if adp.get('speed_mbps') else 'N/A')}
      {_info_row("IPv4", adp.get('ip4','N/A'))}
      {_info_row("IPv6", adp.get('ip6','N/A')[:40] + '...' if (adp.get('ip6','N/A') or '') != 'N/A' and len(adp.get('ip6','')) > 40 else adp.get('ip6','N/A'))}
      {_info_row("Gateway", ', '.join(adp.get('gateways',[])) or 'N/A')}
      {_info_row("DNS", ', '.join(adp.get('dns',[])) or 'N/A')}
      {_info_row("DHCP", 'Có' if adp.get('dhcp') else 'Không')}
    </div>
  </div>
</div>"""

    return f"""
<div class="section">
  <div class="section-title">🌐 Mạng (Network)</div>
  {inet_html}
  {fw_html}
  {adapter_html if adapter_html else '<div class="alert alert-warning"><span>⚠️</span><span>Không tìm thấy adapter đang hoạt động</span></div>'}
</div>"""


def _build_license_section(lic: Dict) -> str:
    win  = lic.get("windows", {})
    off  = lic.get("office", {})
    ado  = lic.get("adobe", {})
    scan = lic.get("crack_scan", {})

    # Windows
    win_activated = win.get("activation_status", "Unknown") in {"Licensed", "Activated"}
    win_icon   = "✅" if win_activated else "❌"
    win_color  = "good" if win_activated else "danger"

    # Office
    off_ok    = off.get("activation_status", "") in {"Licensed", "Activated"}
    off_icon  = "✅" if off_ok else ("⚠️" if off.get("installed") else "—")
    off_color = "good" if off_ok else "warn"

    # Crack scan summary
    risk       = scan.get("risk_level", "Unknown")
    risk_color = scan.get("risk_color", "unknown")
    n_findings = scan.get("total_findings", 0)
    findings   = scan.get("findings", [])

    scan_icon = "✅" if risk in ("None", "Low") else "⚠️" if risk == "Medium" else "❌"

    findings_html = ""
    if findings:
        for f in findings:
            sev = f.get("severity", "Medium")
            findings_html += f"""
<div class="finding sev-{sev}">
  <div class="finding-title">
    {f.get('title','')}
    <span class="sev-pill">{sev}</span>
  </div>
  <div class="finding-desc">{f.get('description','')}</div>
  <div class="finding-evidence" title="{f.get('evidence','')}">📎 {f.get('evidence','')[:120]}</div>
</div>"""
    else:
        findings_html = '<div class="alert alert-success"><span>✅</span><span>Không phát hiện dấu hiệu crack hoặc can thiệp trái phép.</span></div>'

    return f"""
<div class="section">
  <div class="section-title">🔑 Bản quyền phần mềm</div>

  <!-- Windows License -->
  <div class="panel" style="margin-bottom:12px">
    <div class="panel-header">
      <span>{win_icon}</span>
      <span>Microsoft Windows</span>
      <span style="margin-left:auto">{_status_badge(win.get('activation_status','Unknown'), _color_class(win_color))}</span>
    </div>
    <div class="panel-body">
      <div class="panel-grid">
        {_info_row("Tên sản phẩm", win.get('product_name'))}
        {_info_row("Edition", win.get('edition'))}
        {_info_row("Build Number", win.get('build_number'))}
        {_info_row("Loại License", win.get('license_type'))}
        {_info_row("Product ID", win.get('product_id'))}
        {_info_row("Partial Key", win.get('partial_key'))}
        {_info_row("Ngày cài đặt", win.get('install_date'))}
        {_info_row("KMS Server", win.get('kms_server','N/A'))}
      </div>
    </div>
  </div>

  <!-- Office License -->
  <div class="panel" style="margin-bottom:12px">
    <div class="panel-header">
      <span>{off_icon}</span>
      <span>Microsoft Office</span>
      <span style="margin-left:auto">{_status_badge(off.get('activation_status','Not installed') if off.get('installed') else 'Not installed', _color_class(off_color if off.get('installed') else 'unknown'))}</span>
    </div>
    <div class="panel-body">
      {'<div class="panel-grid">' +
        _info_row("Sản phẩm", off.get('product_name')) +
        _info_row("Phiên bản", off.get('version')) +
        _info_row("Channel", off.get('channel')) +
        _info_row("Loại License", off.get('license_type')) +
        _info_row("Partial Key", off.get('partial_key', 'N/A')) +
        _info_row("KMS Server", off.get('kms_server', 'N/A')) +
        (_info_row("Ghi chú / Lỗi", off.get('error_desc')) if off.get('error_desc') else "") +
      '</div>' if off.get('installed') else '<span style="color:var(--text-muted)">Microsoft Office không được cài đặt.</span>'}
    </div>
  </div>

  <!-- Adobe -->
  <div class="panel" style="margin-bottom:12px">
    <div class="panel-header">
      <span>🎨</span>
      <span>Adobe Products</span>
      <span style="margin-left:auto">{_status_badge('Detected' if ado.get('installed') else 'Not installed', _color_class('good' if ado.get('installed') else 'unknown'))}</span>
    </div>
    <div class="panel-body">
      {'<div class="panel-grid">' + ''.join(_info_row(p.get('name',''), p.get('status','')) for p in ado.get('products',[])[:6]) + '</div>' if ado.get('products') else '<span style="color:var(--text-muted)">Không phát hiện sản phẩm Adobe.</span>'}
    </div>
  </div>

  <!-- Security / Crack Scan -->
  <div class="section-title" style="margin-top:24px">🛡️ Kiểm tra bảo mật & phát hiện crack</div>
  <div class="panel">
    <div class="panel-header">
      <span>{scan_icon}</span>
      <span>Kết quả quét</span>
      <span style="margin-left:auto">
        Mức rủi ro: {_status_badge(risk, _color_class(risk_color))}
      </span>
    </div>
    <div class="panel-body">
      <div class="summary-banner" style="margin-bottom:20px">
        <div class="summary-stat"><div class="summary-stat-val" style="color:var(--danger)">{scan.get('critical_count',0)}</div><div class="summary-stat-label">Critical</div></div>
        <div class="summary-divider"></div>
        <div class="summary-stat"><div class="summary-stat-val" style="color:var(--warn)">{scan.get('high_count',0)}</div><div class="summary-stat-label">High</div></div>
        <div class="summary-divider"></div>
        <div class="summary-stat"><div class="summary-stat-val" style="color:#a78bfa">{scan.get('medium_count',0)}</div><div class="summary-stat-label">Medium</div></div>
        <div class="summary-divider"></div>
        <div class="summary-stat"><div class="summary-stat-val">{n_findings}</div><div class="summary-stat-label">Tổng</div></div>
      </div>
      {findings_html}
    </div>
  </div>
</div>"""


def _build_motherboard_section(mb: Dict) -> str:
    return f"""
<div class="section">
  <div class="section-title">🔧 Mainboard & BIOS</div>
  <div class="panel">
    <div class="panel-header"><span>🔧</span><span>{mb.get('mb_manufacturer','N/A')} {mb.get('mb_model','N/A')}</span></div>
    <div class="panel-body">
      <div class="panel-grid">
        {_info_row("Mainboard", f"{mb.get('mb_manufacturer','')} {mb.get('mb_model','')}")}
        {_info_row("Serial (MB)", mb.get('mb_serial'))}
        {_info_row("Version", mb.get('mb_version'))}
        {_info_row("Hãng máy", mb.get('system_manufacturer'))}
        {_info_row("Model máy", mb.get('system_model'))}
        {_info_row("BIOS Hãng", mb.get('bios_manufacturer'))}
        {_info_row("BIOS Version", mb.get('bios_version'))}
        {_info_row("BIOS Date", mb.get('bios_date'))}
        {_info_row("SMBIOS Version", mb.get('bios_smbios_version'))}
        {_info_row("BIOS Serial", mb.get('bios_serial'))}
      </div>
    </div>
  </div>
</div>"""


# ─── MAIN BUILD FUNCTION ──────────────────────────────────────────────────────

def build_html(data: Dict[str, Any], chartjs_code: str = "") -> str:
    """
    Tạo HTML report hoàn chỉnh từ dữ liệu đã thu thập.

    Args:
        data: Dict chứa toàn bộ dữ liệu từ các collector
        chartjs_code: Chart.js minified code (nhúng inline, có thể rỗng)

    Returns:
        Chuỗi HTML hoàn chỉnh
    """
    now       = datetime.datetime.now()
    timestamp = now.strftime("%d/%m/%Y %H:%M:%S")
    hostname  = data.get("network", {}).get("hostname", socket.gethostname())
    os_name   = data.get("license", {}).get("windows", {}).get("product_name", "Windows")
    build_no  = data.get("license", {}).get("windows", {}).get("build_number", "N/A")

    chartjs_script = f"<script>{chartjs_code}</script>" if chartjs_code else ""

    html = f"""<!DOCTYPE html>
<html lang="vi" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>CheckSysHealth — {hostname} — {timestamp}</title>
  <meta name="description" content="System diagnostic report cho {hostname} tạo lúc {timestamp}">
  <style>{_CSS}</style>
  {chartjs_script}
</head>
<body>
<header class="header">
  <div class="header-inner">
    <div>
      <div class="header-title">Check<span>Sys</span>Health</div>
      <div class="header-meta">🖥️ {hostname} &nbsp;|&nbsp; {os_name} (Build {build_no}) &nbsp;|&nbsp; 📅 {timestamp}</div>
    </div>
    <div class="header-actions">
      <button class="btn btn-outline" onclick="toggleTheme()"><span id="themeIcon">☀️</span> Theme</button>
      <button class="btn btn-primary" onclick="printReport()">🖨️ In / PDF</button>
    </div>
  </div>
</header>

<div class="container">
  <!-- ═══ SUMMARY CARDS ═══ -->
  {_build_summary_cards(data)}

  <!-- ═══ CHARTS ROW ═══ -->
  <div class="chart-row">
    {_doughnut_chart(data.get('ram',{}).get('used_pct'), "RAM Used %")}
    {_doughnut_chart(
        data.get('disk',{}).get('drives',[{}])[0].get('health_pct') if data.get('disk',{}).get('drives') else None,
        "Disk Health %"
    )}
    {_doughnut_chart(
        data.get('battery',{}).get('wear_level_pct') if data.get('battery',{}).get('present') else None,
        "Battery Wear %"
    )}
    {_doughnut_chart(data.get('cpu',{}).get('load_pct'), "CPU Load %")}
  </div>

  <!-- ═══ CPU ═══ -->
  {_build_cpu_section(data.get('cpu', {}))}

  <!-- ═══ MAINBOARD ═══ -->
  {_build_motherboard_section(data.get('motherboard', {}))}

  <!-- ═══ RAM ═══ -->
  {_build_ram_section(data.get('ram', {}))}

  <!-- ═══ DISK ═══ -->
  {_build_disk_section(data.get('disk', {}))}

  <!-- ═══ BATTERY ═══ -->
  {_build_battery_section(data.get('battery', {}))}

  <!-- ═══ GPU ═══ -->
  {_build_gpu_section(data.get('gpu', {}))}

  <!-- ═══ NETWORK ═══ -->
  {_build_network_section(data.get('network', {}))}

  <!-- ═══ LICENSE & SECURITY ═══ -->
  {_build_license_section(data.get('license', {}))}

  <!-- Footer -->
  <div style="text-align:center;padding:32px 0;color:var(--text-muted);font-size:.8rem;border-top:1px solid var(--border);margin-top:40px">
    <div>CheckSysHealth v1.0 &nbsp;—&nbsp; Công cụ chẩn đoán hệ thống Windows</div>
    <div>Báo cáo tạo lúc {timestamp} &nbsp;·&nbsp; Read-Only — Không chỉnh sửa hệ thống</div>
  </div>
</div>

<script>{_JS}</script>
</body>
</html>"""

    return html
