#!/usr/bin/env python3
"""
OMEN Battery  ─  A beautiful charge-limit monitor for HP OMEN on Linux
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Since HP OMEN 16-xd0 has no kernel threshold API, this tool:
  • Watches capacity every 30s via /sys/class/power_supply/BAT1/
  • Sends a KDE notification (with sound) when you should unplug
  • Tracks "Top Up" mode: suppress the 80% alert for one full cycle
  • Shows a beautiful translucent panel widget when you click the tray icon

Install:  See README.md
Run:      python3 -m src.omen_battery.main
"""

import sys
import os
import math
import json
import subprocess
from pathlib import Path

from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget,
    QPushButton, QLabel, QFrame, QGraphicsBlurEffect
)
from PyQt6.QtCore import (
    Qt, QTimer, QPoint, QRect, QSize, QPropertyAnimation,
    QEasingCurve, QThread, pyqtSignal, QObject, pyqtProperty,
    QPointF
)
from PyQt6.QtGui import (
    QPainter, QPen, QColor, QBrush, QFont, QFontDatabase,
    QLinearGradient, QRadialGradient, QConicalGradient,
    QIcon, QPixmap, QPainterPath, QRegion, QCursor,
    QFontMetrics
)

# ── sysfs paths ───────────────────────────────────────────────────────────────
BAT = Path("/sys/class/power_supply/BAT1")
AC  = Path("/sys/class/power_supply/ACAD")
STATE_FILE = Path.home() / ".local/share/omen-battery/state.json"

def sysread(p):
    try: return Path(p).read_text().strip()
    except: return None

def sysint(p):
    v = sysread(p)
    return int(v) if v and v.lstrip('-').isdigit() else 0

# ── Battery data snapshot ─────────────────────────────────────────────────────
class BattData:
    def __init__(self):
        self.capacity     = sysint(BAT / "capacity")
        self.status       = sysread(BAT / "status") or "Unknown"
        self.energy_now   = sysint(BAT / "energy_now")   / 1_000_000
        self.energy_full  = sysint(BAT / "energy_full")  / 1_000_000
        self.energy_design= sysint(BAT / "energy_full_design") / 1_000_000
        self.power_w      = sysint(BAT / "power_now")    / 1_000_000
        self.voltage_v    = sysint(BAT / "voltage_now")  / 1_000_000
        self.cycle_count  = sysint(BAT / "cycle_count")
        self.ac_online    = sysint(AC  / "online")
        # derived
        self.bios_cap_pct = round(self.energy_full / self.energy_design * 100, 1) if self.energy_design else 0
        # time estimate
        self.time_str = "—"
        if self.power_w > 0.1:
            if self.status == "Discharging":
                h = self.energy_now / self.power_w
            elif self.status in ("Charging", "Not charging"):
                h = max(0, (self.energy_full - self.energy_now) / self.power_w)
            else:
                h = 0
            if h > 0:
                hi, m = int(h), int((h % 1) * 60)
                self.time_str = f"{hi}h {m:02d}m"

# ── State persistence ─────────────────────────────────────────────────────────
def load_state():
    try:
        return json.loads(STATE_FILE.read_text())
    except:
        return {"limit": 80, "top_up_active": False, "notified_at": -1}

def save_state(s):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(s))

# ── KDE notification ──────────────────────────────────────────────────────────
def notify(title, body, urgency="normal", icon="battery-caution"):
    subprocess.Popen([
        "notify-send",
        f"--urgency={urgency}",
        f"--icon={icon}",
        "--app-name=OMEN Battery",
        title, body
    ])

# ── Colour palette ────────────────────────────────────────────────────────────
C = {
    "bg":         QColor(12, 12, 14, 210),
    "bg2":        QColor(20, 20, 24, 180),
    "border":     QColor(255, 255, 255, 18),
    "arc_track":  QColor(40, 40, 50, 200),
    "arc_charge": QColor(0, 210, 120),      # green
    "arc_limit":  QColor(255, 170, 0),      # amber warning
    "arc_topup":  QColor(80, 160, 255),     # blue top-up
    "text_main":  QColor(240, 240, 245),
    "text_dim":   QColor(140, 140, 160),
    "text_green": QColor(0, 210, 120),
    "text_amber": QColor(255, 170, 0),
    "text_blue":  QColor(80, 160, 255),
    "btn_normal": QColor(35, 35, 45, 220),
    "btn_hover":  QColor(50, 50, 65, 240),
    "btn_active": QColor(0, 160, 90, 200),
    "dot_ac":     QColor(0, 220, 120),
    "dot_bat":    QColor(255, 140, 0),
    "separator":  QColor(255, 255, 255, 12),
}

# ── Arc gauge widget ──────────────────────────────────────────────────────────
class ArcGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(160, 160)  # matches GAUGE_SIZE=160 defined at module level
        self._pct   = 0.0
        self._limit = 80
        self._topup = False
        self._status = "Unknown"
        self._animated_pct = 0.0
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._step_anim)
        self._anim_timer.start(16)

    def _step_anim(self):
        target = float(self._pct)
        diff = target - self._animated_pct
        if abs(diff) > 0.2:
            self._animated_pct += diff * 0.08
            self.update()
        elif abs(diff) > 0.01:
            self._animated_pct = target
            self.update()

    def set_data(self, pct, limit, topup, status):
        self._pct = pct
        self._limit = limit
        self._topup = topup
        self._status = status
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        r_outer = min(w, h) / 2 - 10
        r_inner = r_outer - 14

        # Arc angles: start at 225° (bottom-left), sweep 270°
        START = 225
        SPAN  = 270

        # Track arc
        pen = QPen(C["arc_track"], 13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        rect = QRect(int(cx - r_outer), int(cy - r_outer),
                     int(r_outer * 2), int(r_outer * 2))
        p.drawArc(rect, int(START * 16), int(-SPAN * 16))

        # Limit marker line
        limit_angle = START - (self._limit / 100.0) * SPAN
        lrad = math.radians(limit_angle)
        lx1 = cx + (r_outer - 18) * math.cos(lrad)
        ly1 = cy - (r_outer - 18) * math.sin(lrad)
        lx2 = cx + (r_outer + 2) * math.cos(lrad)
        ly2 = cy - (r_outer + 2) * math.sin(lrad)
        lpen = QPen(C["arc_limit"] if not self._topup else C["arc_topup"], 2.5,
                    Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(lpen)
        p.drawLine(QPointF(lx1, ly1), QPointF(lx2, ly2))

        # Value arc (animated)
        pct = max(0, min(100, self._animated_pct))
        arc_color = C["arc_charge"]
        if not self._topup and pct >= self._limit:
            arc_color = C["arc_limit"]
        elif self._topup:
            arc_color = C["arc_topup"]

        sweep = (pct / 100.0) * SPAN
        grad = QConicalGradient(cx, cy, START)
        c1 = QColor(arc_color)
        c2 = QColor(arc_color)
        c1.setAlpha(255)
        c2.setAlpha(160)
        grad.setColorAt(0.0, c1)
        grad.setColorAt(1.0, c2)
        pen2 = QPen(QBrush(grad), 13, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        p.setPen(pen2)
        p.drawArc(rect, int(START * 16), int(-sweep * 16))

        # Percentage text
        pct_font = QFont("Helvetica Neue", 32, QFont.Weight.Light)
        p.setFont(pct_font)
        p.setPen(C["text_main"])
        pct_str = f"{int(self._pct)}"
        fm = QFontMetrics(pct_font)
        tw = fm.horizontalAdvance(pct_str)
        th = fm.height()
        p.drawText(int(cx - tw / 2), int(cy + th / 4), pct_str)

        # % symbol
        sym_font = QFont("Helvetica Neue", 13, QFont.Weight.Light)
        p.setFont(sym_font)
        p.setPen(C["text_dim"])
        sfm = QFontMetrics(sym_font)
        sw = sfm.horizontalAdvance("%")
        p.drawText(int(cx + tw / 2 + 2), int(cy + th / 4), "%")

        # Status text below
        status_font = QFont("Helvetica Neue", 9)
        p.setFont(status_font)
        p.setPen(C["text_dim"])
        st = self._status.upper()
        sfm2 = QFontMetrics(status_font)
        stw = sfm2.horizontalAdvance(st)
        p.drawText(int(cx - stw / 2), int(cy + th / 4 + 22), st)

        p.end()

# ── Stat row widget ───────────────────────────────────────────────────────────
class StatRow(QWidget):
    def __init__(self, label, value="—", color=None, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self._label = label
        self._value = value
        self._color = color or C["text_main"]

    def set_value(self, v, color=None):
        self._value = v
        if color:
            self._color = color
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        lf = QFont("SF Pro Text", 10) if sys.platform == "darwin" else QFont("Noto Sans", 9)
        vf = QFont("SF Pro Text", 10, QFont.Weight.Medium) if sys.platform == "darwin" \
             else QFont("Noto Sans", 9, QFont.Weight.Medium)
        p.setFont(lf)
        p.setPen(C["text_dim"])
        p.drawText(0, 16, self._label)
        p.setFont(vf)
        p.setPen(self._color)
        fm = QFontMetrics(vf)
        tw = fm.horizontalAdvance(self._value)
        p.drawText(self.width() - tw, 16, self._value)
        p.end()

# ── Power source indicator ────────────────────────────────────────────────────
class PowerBar(QWidget):
    """Shows a split bar: % from battery vs % from AC"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self._ac_online = False
        self._status = "Unknown"
        self._capacity = 0
        self._power_w = 0.0

    def set_data(self, ac_online, status, capacity, power_w):
        self._ac_online = ac_online
        self._status = status
        self._capacity = capacity
        self._power_w = power_w
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Background pill
        bg = QPainterPath()
        bg.addRoundedRect(0, 8, w, 20, 10, 10)
        p.fillPath(bg, C["arc_track"])

        if self._ac_online:
            # AC providing power
            ac_color = QColor(0, 200, 110)
            ac_path = QPainterPath()
            ac_path.addRoundedRect(0, 8, w, 20, 10, 10)
            p.fillPath(ac_path, ac_color)
            label = f"  ⚡ AC  {self._power_w:.1f}W" if self._power_w > 0.1 else "  ⚡ AC Power"
            lcolor = QColor(10, 10, 14)
        else:
            # Battery providing power
            bat_w = int(w * self._capacity / 100)
            bat_path = QPainterPath()
            bat_path.addRoundedRect(0, 8, max(bat_w, 20), 20, 10, 10)
            p.fillPath(bat_path, QColor(255, 130, 0))
            label = f"  🔋 Battery  {self._power_w:.1f}W" if self._power_w > 0.1 else "  🔋 Battery"
            lcolor = QColor(240, 240, 245)

        lf = QFont("Noto Sans", 9, QFont.Weight.Medium)
        p.setFont(lf)
        p.setPen(lcolor)
        p.drawText(QRect(0, 8, w, 20), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)
        p.end()

# ── Animated button ───────────────────────────────────────────────────────────
class OmenButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._hovered = False
        self._active_color = QColor(0, 160, 90)
        self.setFixedHeight(36)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setStyleSheet("background: transparent; border: none; color: transparent;")

    def set_active_color(self, c: QColor):
        self._active_color = c

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        if self.isChecked():
            bg = self._active_color
            bg.setAlpha(220)
        elif self._hovered:
            bg = C["btn_hover"]
        else:
            bg = C["btn_normal"]

        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 8, 8)
        p.fillPath(path, bg)

        border_color = QColor(255, 255, 255, 30 if self._hovered else 18)
        p.setPen(QPen(border_color, 1))
        p.drawPath(path)

        tf = QFont("Noto Sans", 9, QFont.Weight.Medium)
        p.setFont(tf)
        tc = QColor(240, 240, 245) if self.isChecked() or self._hovered else C["text_dim"]
        p.setPen(tc)
        p.drawText(QRect(0, 0, w, h), Qt.AlignmentFlag.AlignCenter, self.text())
        p.end()

# ── Layout constants ──────────────────────────────────────────────────────────
W          = 290
MARGIN     = 20
GAUGE_SIZE = 160          # slightly smaller gauge to give stats room to breathe
GAUGE_Y    = 28
POWERBAR_Y = GAUGE_Y + GAUGE_SIZE + 6        # 194
PB_H       = 32
SEP1_Y     = POWERBAR_Y + PB_H + 6          # 232
STATS_Y    = SEP1_Y + 8                     # 240
ROW_H      = 16
ROW_GAP    = 18
N_ROWS     = 6
SEP2_Y     = STATS_Y + N_ROWS * ROW_GAP + 4 # 352
BTN_Y      = SEP2_Y + 8                     # 360
BTN_H      = 36
PANEL_H    = BTN_Y + BTN_H + 14             # 410

# ── Main panel window ─────────────────────────────────────────────────────────
class BatteryPanel(QWidget):
    def __init__(self):
        super().__init__()
        # Popup: dismissed on click-outside; FramelessHint: no titlebar;
        # Tool: no taskbar entry; WindowStaysOnTop: above normal windows
        self.setWindowFlags(
            Qt.WindowType.Popup |
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(W, PANEL_H)

        self._state    = load_state()
        self._data     = BattData()
        self._drag_pos = None

        self._build_ui()
        self._refresh()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(8000)

    def _build_ui(self):
        # Arc gauge — centred horizontally
        self._gauge = ArcGauge(self)
        self._gauge.move((W - GAUGE_SIZE) // 2, GAUGE_Y)

        # Power source bar
        self._power_bar = PowerBar(self)
        self._power_bar.setGeometry(MARGIN, POWERBAR_Y, W - MARGIN * 2, PB_H)

        # Separator 1
        sep = QFrame(self)
        sep.setGeometry(MARGIN, SEP1_Y, W - MARGIN * 2, 1)
        sep.setStyleSheet("background: rgba(255,255,255,12); border: none;")

        # Stat rows
        y = STATS_Y
        self._row_energy   = StatRow("Energy",     parent=self)
        self._row_design   = StatRow("Design cap", parent=self)
        self._row_bios_cap = StatRow("BIOS cap",   parent=self)
        self._row_cycles   = StatRow("Cycles",     parent=self)
        self._row_time     = StatRow("Time left",  parent=self)
        self._row_voltage  = StatRow("Voltage",    parent=self)

        for row in [self._row_energy, self._row_design, self._row_bios_cap,
                    self._row_cycles, self._row_time, self._row_voltage]:
            row.setGeometry(MARGIN, y, W - MARGIN * 2, ROW_H)
            y += ROW_GAP

        # Separator 2
        sep2 = QFrame(self)
        sep2.setGeometry(MARGIN, SEP2_Y, W - MARGIN * 2, 1)
        sep2.setStyleSheet("background: rgba(255,255,255,12); border: none;")

        # Top Up button — full width with margins, properly pinned
        self._btn_topup = OmenButton("Top Up to 100%", self)
        self._btn_topup.setCheckable(True)
        self._btn_topup.setGeometry(MARGIN, BTN_Y, W - MARGIN * 2, BTN_H)
        self._btn_topup.set_active_color(QColor(60, 120, 255))
        self._btn_topup.clicked.connect(self._toggle_topup)

    def _toggle_topup(self):
        self._state["top_up_active"] = self._btn_topup.isChecked()
        self._state["notified_at"] = -1
        save_state(self._state)
        if self._btn_topup.isChecked():
            notify("Top Up activated", "Will notify when battery reaches 100%", icon="battery-full")
        self._refresh()

    def _refresh(self):
        d = BattData()
        self._data = d
        s = self._state
        limit = s.get("limit", 80)
        topup = s.get("top_up_active", False)
        effective_limit = 100 if topup else limit

        # Gauge
        self._gauge.set_data(d.capacity, effective_limit, topup, d.status)

        # Update button state to match persisted state
        self._btn_topup.setChecked(topup)
        self._btn_topup.setText("Cancel Top Up" if topup else "Top Up to 100%")

        # Power bar
        self._power_bar.set_data(d.ac_online, d.status, d.capacity, d.power_w)

        # Stat rows
        self._row_energy.set_value(
            f"{d.energy_now:.1f} / {d.energy_full:.1f} Wh",
            C["text_main"]
        )
        self._row_design.set_value(f"{d.energy_design:.0f} Wh")
        self._row_bios_cap.set_value(
            f"{d.bios_cap_pct:.0f}%",
            C["text_amber"] if d.bios_cap_pct < 85 else C["text_green"]
        )
        self._row_cycles.set_value(str(d.cycle_count) if d.cycle_count else "—")
        self._row_time.set_value(d.time_str)
        self._row_voltage.set_value(f"{d.voltage_v:.2f} V" if d.voltage_v else "—")

        # Charge limit logic
        notified_at = s.get("notified_at", -1)
        if d.ac_online and d.capacity >= effective_limit and notified_at != d.capacity:
            if topup:
                notify(
                    "🔋 Battery Full",
                    "Reached 100% — safe to unplug now.",
                    urgency="normal", icon="battery-full"
                )
                self._state["top_up_active"] = False
                self._btn_topup.setChecked(False)
                self._btn_topup.setText("Top Up to 100%")
            else:
                notify(
                    f"🔋 {d.capacity}% — Unplug Now",
                    f"Battery hit your {limit}% limit. Unplug to protect battery life.",
                    urgency="critical", icon="battery-caution"
                )
            self._state["notified_at"] = d.capacity
            save_state(self._state)

        # Clear notified_at when unplugged (so next plug-in triggers again)
        if not d.ac_online and notified_at != -1:
            self._state["notified_at"] = -1
            save_state(self._state)

        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Main background
        path = QPainterPath()
        path.addRoundedRect(0, 0, w, h, 16, 16)

        # Subtle gradient bg
        grad = QLinearGradient(0, 0, 0, h)
        grad.setColorAt(0.0, QColor(18, 18, 22, 215))
        grad.setColorAt(1.0, QColor(10, 10, 13, 215))
        p.fillPath(path, QBrush(grad))

        # Border
        p.setPen(QPen(C["border"], 1))
        p.drawPath(path)

        # Top accent line (OMEN red accent)
        accent = QPainterPath()
        accent.addRoundedRect(0, 0, w, 3, 1.5, 1.5)
        ag = QLinearGradient(0, 0, w, 0)
        ag.setColorAt(0.0, QColor(200, 30, 30, 0))
        ag.setColorAt(0.3, QColor(220, 40, 40, 200))
        ag.setColorAt(0.7, QColor(220, 40, 40, 200))
        ag.setColorAt(1.0, QColor(200, 30, 30, 0))
        p.fillPath(accent, QBrush(ag))

        # Header text
        hf = QFont("Noto Sans", 8, QFont.Weight.Medium)
        p.setFont(hf)
        p.setPen(QColor(180, 180, 200, 140))
        p.drawText(QRect(0, 8, w, 16), Qt.AlignmentFlag.AlignHCenter, "OMEN BATTERY")

        # AC/BAT dot indicator
        d = self._data
        dot_color = C["dot_ac"] if d.ac_online else C["dot_bat"]
        dp = QPainterPath()
        dp.addEllipse(QPointF(w - 18, 14), 4, 4)
        p.fillPath(dp, dot_color)

        p.end()

    # drag to move
    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e):
        if self._drag_pos and e.buttons() == Qt.MouseButton.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e):
        self._drag_pos = None

    def changeEvent(self, event):
        # Hide when panel loses focus — works reliably on Wayland with Popup flag
        if (event.type() == event.Type.ActivationChange
                and not self.isActiveWindow()):
            self.hide()
        super().changeEvent(event)

    def show_at_cursor(self):
        """
        Position the panel near the cursor, clamped to screen edges.
        On Wayland we can't read the tray icon's exact position, so
        cursor position at click-time is the most reliable anchor.
        """
        cursor  = QCursor.pos()
        screen  = QApplication.screenAt(cursor)
        if screen is None:
            screen = QApplication.primaryScreen()
        sg = screen.geometry()

        # Open just above and centred on the cursor
        x = cursor.x() - self.width() // 2
        y = cursor.y() - self.height() - 8

        # Clamp so panel never goes off-screen
        x = max(sg.left() + 8, min(x, sg.right()  - self.width()  - 8))
        y = max(sg.top()  + 8, min(y, sg.bottom() - self.height() - 8))

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()

# ── Tray icon ─────────────────────────────────────────────────────────────────
def make_tray_icon(pct: int, ac: bool) -> QIcon:
    size = 22
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # outer ring
    p.setPen(QPen(QColor(60, 60, 70), 1.5))
    p.setBrush(QColor(20, 20, 25))
    p.drawEllipse(2, 2, 18, 18)

    # fill arc
    color = QColor(0, 200, 100) if ac else QColor(255, 140, 0)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(color)
    span = int(-(pct / 100.0) * 5760)
    p.drawPie(QRect(3, 3, 16, 16), 1440, span)

    # center cover
    p.setBrush(QColor(20, 20, 25))
    p.drawEllipse(6, 6, 10, 10)

    # pct text
    f = QFont("Noto Sans", 5, QFont.Weight.Bold)
    p.setFont(f)
    p.setPen(QColor(230, 230, 240))
    p.drawText(QRect(0, 0, size, size), Qt.AlignmentFlag.AlignCenter, str(pct))

    p.end()
    return QIcon(px)

# ── Background poller (runs in main thread via timer for simplicity) ──────────
class App:
    def __init__(self):
        self.panel = BatteryPanel()
        self.tray  = QSystemTrayIcon()
        self._setup_tray()
        self._tray_timer = QTimer()
        self._tray_timer.timeout.connect(self._update_tray)
        self._tray_timer.start(15000)
        self._update_tray()

    def _setup_tray(self):
        menu = QMenu()
        show_action = menu.addAction("Show Battery")
        show_action.triggered.connect(self._show_panel)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(QApplication.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_click)
        self.tray.show()

    def _on_tray_click(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show_panel()

    def _show_panel(self):
        if self.panel.isVisible():
            self.panel.hide()
        else:
            self.panel.show_at_cursor()

    def _update_tray(self):
        d = BattData()
        icon = make_tray_icon(d.capacity, bool(d.ac_online))
        self.tray.setIcon(icon)
        status_str = "AC" if d.ac_online else "Battery"
        power_str = f"  {d.power_w:.1f}W" if d.power_w > 0.1 else ""
        self.tray.setToolTip(
            f"OMEN Battery  {d.capacity}%  {status_str}{power_str}\n"
            f"{d.status}  •  {d.time_str}"
        )

def main():
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("OMEN Battery")

    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray available.", file=sys.stderr)
        sys.exit(1)

    a = App()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
