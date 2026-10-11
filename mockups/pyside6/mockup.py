#!/usr/bin/env python3
"""RetroShelf main window mock-up in PySide6 (Qt 6): sample data, no backend.

    python3 -m pip install PySide6        # in a venv; about 200 MB
    python3 mockups/pyside6/mockup.py

Same screen, data and keys as the Electron mock-up next to it, so the two can be compared side by side.
Gamepads use RetroShelf's own lib/gamepad.py (Qt 6 has no gamepad module), mapped onto the same keys."""
import json, math, os, sys, time

from PySide6.QtCore import (QAbstractListModel, QEasingCurve, QModelIndex, QPoint, QPointF, QPropertyAnimation, QRect,
                            QRectF, QSize, Qt, QTimer, QVariantAnimation, Property, Signal)
from PySide6.QtGui import (QBrush, QColor, QFont, QFontMetrics, QIcon, QImage, QKeySequence, QLinearGradient,
                           QPainter, QPainterPath, QPalette, QPen, QPixmap, QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QFrame, QGraphicsBlurEffect,
                               QGraphicsDropShadowEffect, QGraphicsOpacityEffect, QGraphicsPixmapItem, QGraphicsScene,
                               QHBoxLayout, QLabel, QLineEdit, QListView, QPushButton, QScrollArea, QSizePolicy,
                               QStyledItemDelegate, QVBoxLayout, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "lib"))

BG, SURFACE, SURFACE2, SURFACE3, BORDER = "#0e1016", "#161922", "#1d212c", "#262b38", "#2a3040"
TEXT, MUTED, ACCENT, KEEP, MOVE, STAR = "#e9ecf3", "#8d94a7", "#57c8ff", "#4ade80", "#ff8a65", "#ffd166"
ROW_H = 56
FONT = ["Inter", "Segoe UI Variable", "Segoe UI", "Cantarell", "Noto Sans"]

QSS = f"""
QWidget {{ color: {TEXT}; font-size: 14px; }}
#card {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 12px; }}
#card[active="true"] {{ border-color: #33405a; }}
#colhead {{ border-bottom: 1px solid {BORDER}; }}
QLabel#muted {{ color: {MUTED}; }}
QLabel#brand {{ font-size: 16px; font-weight: 700; }}
QPushButton#system {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 19px; padding: 0 14px 0 6px;
  height: 36px; text-align: left; }}
QPushButton#system:hover {{ background: {SURFACE3}; border-color: #3a4256; }}
QLabel#tag {{ background: {ACCENT}; color: #062033; font-weight: 800; font-size: 12px; border-radius: 10px;
  padding: 0 9px; min-height: 22px; max-height: 22px; }}
QLineEdit#search {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 19px; padding: 0 16px; height: 36px;
  selection-background-color: {ACCENT}; }}
QLineEdit#search:focus {{ border-color: {ACCENT}; }}
QPushButton#chip {{ background: {SURFACE}; border: 1px solid {BORDER}; border-radius: 15px; padding: 0 12px; height: 30px;
  color: {MUTED}; font-size: 13px; }}
QPushButton#chip:hover {{ border-color: #3a4256; color: {TEXT}; }}
QPushButton#chip:checked {{ background: rgba(87,200,255,36); border-color: rgba(87,200,255,128); color: {TEXT}; }}
QLabel#genre {{ background: {SURFACE3}; border-radius: 10px; padding: 0 10px; font-size: 12px; min-height: 22px; max-height: 22px; }}
QPushButton#ghost {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; height: 40px; padding: 0 18px; }}
QPushButton#ghost:hover {{ background: {SURFACE3}; }}
QPushButton#primary {{ border: 0; border-radius: 10px; height: 40px; padding: 0 18px; color: #04263a; font-weight: 700;
  background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #6fd3ff, stop:1 #3bb6f5); }}
QPushButton#primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #86dbff, stop:1 #52c0f7); }}
QFrame#video {{ background: {SURFACE2}; border: 1px solid {BORDER}; border-radius: 10px; }}
QFrame#video:hover {{ background: {SURFACE3}; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 4px 2px; }}
QScrollBar::handle:vertical {{ background: {SURFACE3}; border-radius: 3px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ height: 0; background: none; }}
QListView {{ background: transparent; border: 0; outline: 0; }}
QScrollArea {{ background: transparent; border: 0; }}
"""


def ease_out(t):
    return 1 - (1 - t) ** 3


def mb(n):
    return f"{n:.1f} MB" if n >= 1 else f"{round(n * 1024)} KB"


def fnv(s):
    h = 2166136261
    for c in s:
        h = ((h ^ ord(c)) * 16777619) & 0xFFFFFFFF
    return h


# ---------- placeholder box art (the real app shows ES-DE's scraped covers) ----------
_covers = {}


def cover(name, w, h, radius=4):
    key = (name, w, h)
    if key in _covers:
        return _covers[key]
    dpr = 2
    img = QImage(w * dpr, h * dpr, QImage.Format_ARGB32_Premultiplied)
    img.setDevicePixelRatio(dpr)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    clip = QPainterPath()
    clip.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(clip)
    hv = fnv(name)
    h1 = hv % 360
    h2 = (h1 + 40 + (hv >> 9) % 80) % 360
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0, QColor.fromHslF(h1 / 360, .65, .48))
    g.setColorAt(1, QColor.fromHslF(h2 / 360, .70, .20))
    p.fillRect(QRectF(0, 0, w, h), g)
    p.setPen(QPen(QColor(255, 255, 255, 18), w / 14))
    x = -h
    while x < w:
        p.drawLine(QPointF(x, h), QPointF(x + h, 0))
        x += w / 5
    p.fillRect(QRectF(0, 0, w, h * .11), QColor(0, 0, 0, 115))
    f = QFont(FONT)
    f.setWeight(QFont.ExtraBold)
    f.setPixelSize(max(1, int(h * .06)))
    p.setFont(f)
    p.setPen(QColor(255, 255, 255, 217))
    p.drawText(QRectF(w * .07, 0, w, h * .11), Qt.AlignVCenter | Qt.AlignLeft, "SNES")
    words = [x for x in name.removeprefix("The ").replace("-", " ").split() if x[:1].isalnum()]
    initials = "".join(x[0] for x in words[:2]).upper()
    f.setPixelSize(max(1, int(w * .36)))
    p.setFont(f)
    p.setPen(QColor(0, 0, 0, 70))
    p.drawText(QRectF(0, h * .12 + 2, w, h * .8), Qt.AlignCenter, initials)
    p.setPen(QColor(255, 255, 255, 235))
    p.drawText(QRectF(0, h * .12, w, h * .8), Qt.AlignCenter, initials)
    p.end()
    _covers[key] = pix = QPixmap.fromImage(img)
    return pix


def blurred(pix, radius):
    """pix blurred (Qt can blur any widget or picture; Tk can't)."""
    scene = QGraphicsScene()
    item = QGraphicsPixmapItem(pix)
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    item.setGraphicsEffect(effect)
    scene.addItem(item)
    size = pix.size() / pix.devicePixelRatio()
    out = QImage(size.width() + 2 * radius, size.height() + 2 * radius, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    scene.render(p, QRectF(0, 0, out.width(), out.height()),
                 QRectF(-radius, -radius, out.width(), out.height()))
    p.end()
    return QPixmap.fromImage(out)


def with_shadow(pix, blur=24, dy=16):
    """pix over a soft drop shadow, baked into one picture (a live shadow effect can't sit inside a fading panel)."""
    w, h = int(pix.width() / pix.devicePixelRatio()), int(pix.height() / pix.devicePixelRatio())
    silhouette = QPixmap(w, h)
    silhouette.fill(QColor(0, 0, 0, 170))
    shadow = blurred(silhouette, blur)
    out = QImage(w + 2 * blur, h + 2 * blur + dy, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    p.drawPixmap(0, dy, shadow)
    p.drawPixmap(QRect(blur, blur, w, h), pix)
    p.end()
    return QPixmap.fromImage(out)


# ---------- data ----------
class Game:
    def __init__(self, row, why=None):
        self.name, self.region, self.rating, self.genre, self.size, self.year, self.dev, self.pub = row[:8]
        self.why = why if why is not None else (row[8] if len(row) > 8 else None)
        self.id = f"{self.name}|{self.region}"

    def key(self):
        return (self.name.lower(), self.region)


class Fx:
    """Per-row effect values (hover, glow, slide offset) eased toward their targets on one 60 fps timer."""

    def __init__(self, view):
        self.view = view
        self.hover, self.glow, self.offset, self.hidden = {}, {}, {}, set()
        self.hover_target = None
        self.timer = QTimer(view, interval=15, timeout=self.step)
        self.last = time.monotonic()

    def kick(self):
        if not self.timer.isActive():
            self.last = time.monotonic()
            self.timer.start()

    def step(self):
        now = time.monotonic()
        dt, self.last = now - self.last, now
        busy = False
        for gid in set(self.hover) | ({self.hover_target} - {None}):
            target = 1.0 if gid == self.hover_target else 0.0
            v = self.hover.get(gid, 0.0)
            v += (target - v) * min(1, dt * 14)
            if abs(target - v) < .01:
                v = target
            if v == 0:
                self.hover.pop(gid, None)
            else:
                self.hover[gid] = v
            busy |= v != target
        for d, speed in ((self.glow, 1.2),):
            for gid in list(d):
                d[gid] -= dt * speed
                if d[gid] <= 0:
                    del d[gid]
                busy = True
        for gid, (start, t0, dur) in list(self.offset.items()):
            k = min(1, (now - t0) / dur)
            if k >= 1:
                del self.offset[gid]
            busy = True
        self.view.viewport().update()
        if not busy:
            self.timer.stop()

    def offset_of(self, gid):
        o = self.offset.get(gid)
        if not o:
            return 0
        start, t0, dur = o
        return start * (1 - ease_out(min(1, (time.monotonic() - t0) / dur)))


class GameModel(QAbstractListModel):
    def __init__(self, kind):
        super().__init__()
        self.kind, self.all, self.query, self.marked = kind, [], "", set()
        self.items = []

    def refresh(self):
        self.beginResetModel()
        q = self.query
        self.items = [g for g in sorted(self.all, key=Game.key) if not q or q in g.name.lower()]
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return len(self.items)

    def data(self, index, role=Qt.DisplayRole):
        if role == Qt.UserRole and index.isValid():
            return self.items[index.row()]
        return None


class RowDelegate(QStyledItemDelegate):
    def __init__(self, view):
        super().__init__(view)
        self.view = view
        self.font = QFont(FONT)
        self.font.setPixelSize(14)
        self.font.setWeight(QFont.Medium)
        self.small = QFont(FONT)
        self.small.setPixelSize(12)
        self.bold_small = QFont(self.small)
        self.bold_small.setWeight(QFont.DemiBold)

    def sizeHint(self, option, index):
        return QSize(option.rect.width(), ROW_H)

    def paint(self, p, option, index):
        g = index.data(Qt.UserRole)
        fx = self.view.fx
        if g.id in fx.hidden:
            return
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        r = QRectF(option.rect).adjusted(6, 0, -6, 0)
        r.translate(0, fx.offset_of(g.id))
        selected = index.row() == self.view.current
        bg = QColor(255, 255, 255, int(10 * fx.hover.get(g.id, 0)))
        if selected:
            bg = QColor(87, 200, 255, 26)
        glow = fx.glow.get(g.id, 0)
        if glow:
            t = ease_out(glow)
            bg = QColor(87, 200, 255, int(26 + 90 * t))
            p.setPen(Qt.NoPen)
            for i in range(4, 0, -1):
                p.setBrush(QColor(87, 200, 255, int(18 * t)))
                p.drawRoundedRect(r.adjusted(-i * 2, -i * 2, i * 2, i * 2), 10 + i * 2, 10 + i * 2)
        if bg.alpha():
            p.setPen(Qt.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(r, 10, 10)
        if g.id in self.view.model().marked:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(r.left(), r.top() + 12, 3, r.height() - 24), 1.5, 1.5)
        art = cover(g.name, 34, 46)
        ar = QRectF(r.left() + 10, r.center().y() - 23, 34, 46)
        p.setBrush(QColor(0, 0, 0, 90))
        p.drawRoundedRect(ar.translated(0, 2), 4, 4)
        p.drawPixmap(ar.toRect(), art)
        right_w = 70
        text = QRectF(ar.right() + 12, r.top(), r.right() - ar.right() - 22 - right_w, r.height())
        p.setFont(self.font)
        p.setPen(QColor(TEXT))
        fm = QFontMetrics(self.font)
        p.drawText(QRectF(text.left(), r.top() + 9, text.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
                   fm.elidedText(g.name, Qt.ElideRight, int(text.width())))
        p.setFont(self.small)
        fms = QFontMetrics(self.small)
        y2 = QRectF(text.left(), r.top() + 29, text.width(), 18)
        if self.view.model().kind == "move" and g.why:
            p.setPen(QColor(MOVE))
            why = fms.elidedText(g.why, Qt.ElideRight, int(text.width()))
            p.drawText(y2, Qt.AlignLeft | Qt.AlignVCenter, why)
            p.setPen(QColor(MUTED))
            rest = fms.elidedText(f" · {g.region}", Qt.ElideRight, int(text.width() - fms.horizontalAdvance(why)))
            p.drawText(y2.adjusted(fms.horizontalAdvance(why), 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, rest)
        else:
            p.setPen(QColor(MUTED))
            p.drawText(y2, Qt.AlignLeft | Qt.AlignVCenter,
                       fms.elidedText(f"{g.region} · {g.genre}", Qt.ElideRight, int(text.width())))
        rr = QRectF(r.right() - right_w - 10, r.top(), right_w, r.height())
        p.setFont(self.bold_small)
        p.setPen(QColor(STAR))
        p.drawText(QRectF(rr.left(), r.top() + 9, rr.width(), 18), Qt.AlignRight | Qt.AlignVCenter, f"★ {g.rating:.1f}")
        p.setFont(self.small)
        p.setPen(QColor(MUTED))
        p.drawText(QRectF(rr.left(), r.top() + 29, rr.width(), 18), Qt.AlignRight | Qt.AlignVCenter, mb(g.size))
        p.restore()


class FocusRing(QWidget):
    """The gliding highlight on the current row (the real app's padfocus, drawn with real glow)."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._pulse = 0.0
        self.anim = QPropertyAnimation(self, b"pos", self)
        self.anim.setDuration(160)
        self.anim.setEasingCurve(QEasingCurve.OutCubic)
        self.pulse_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=350)
        self.pulse_anim.valueChanged.connect(self._set_pulse)

    def _set_pulse(self, v):
        self._pulse = math.sin(v * math.pi)
        self.update()

    def pulse(self):
        self.pulse_anim.stop()
        self.pulse_anim.start()

    def glide(self, pos, animate=True):
        if not animate or not self.isVisible():
            self.anim.stop()
            self.move(pos)
            return
        if self.anim.state() == QPropertyAnimation.Running and self.anim.endValue() == pos:
            return
        self.anim.stop()
        self.anim.setStartValue(self.pos())
        self.anim.setEndValue(pos)
        self.anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(6, 8, -6, -8)
        spread = 4 + 4 * self._pulse
        for i in range(6, 0, -1):
            a = int((10 + 14 * self._pulse) * (7 - i) / 6)
            p.setPen(QPen(QColor(87, 200, 255, a), 2))
            p.setBrush(Qt.NoBrush)
            d = i * spread / 6
            p.drawRoundedRect(r.adjusted(-d, -d, d, d), 10 + d, 10 + d)
        p.setPen(QPen(QColor(ACCENT), 2))
        p.drawRoundedRect(r, 10, 10)


class GameList(QListView):
    activated_row = Signal()

    def __init__(self, model):
        super().__init__()
        self.setModel(model)
        self.current = 0
        self.fx = Fx(self)
        self.setItemDelegate(RowDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setUniformItemSizes(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setSelectionMode(QAbstractItemView.NoSelection)
        self.setSpacing(0)
        self.viewport().setContentsMargins(0, 6, 0, 6)
        self.ring = FocusRing(self.viewport())
        self.ring.hide()
        self.scroll_anim = QPropertyAnimation(self.verticalScrollBar(), b"value", self)
        self.scroll_anim.setDuration(260)
        self.scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
        self.verticalScrollBar().valueChanged.connect(lambda _: self.place_ring(False))

    # smooth wheel: quick flicks add up into one longer glide
    def wheelEvent(self, e):
        sb = self.verticalScrollBar()
        base = self.scroll_anim.endValue() if self.scroll_anim.state() == QPropertyAnimation.Running else sb.value()
        target = max(sb.minimum(), min(sb.maximum(), base - e.angleDelta().y() * 1.2))
        self.scroll_to(target)

    def scroll_to(self, target):
        self.scroll_anim.stop()
        self.scroll_anim.setStartValue(self.verticalScrollBar().value())
        self.scroll_anim.setEndValue(int(target))
        self.scroll_anim.start()

    def mouseMoveEvent(self, e):
        idx = self.indexAt(e.position().toPoint())
        self.fx.hover_target = idx.data(Qt.UserRole).id if idx.isValid() else None
        self.fx.kick()
        super().mouseMoveEvent(e)

    def leaveEvent(self, e):
        self.fx.hover_target = None
        self.fx.kick()
        super().leaveEvent(e)

    def row_rect(self, row):
        return self.visualRect(self.model().index(row, 0))

    def place_ring(self, animate=True):
        n = self.model().rowCount()
        if not n or not self.ring.isEnabled():
            self.ring.hide()
            return
        self.current = max(0, min(self.current, n - 1))
        r = self.row_rect(self.current)
        self.ring.resize(self.viewport().width(), ROW_H + 16)
        self.ring.glide(QPoint(0, r.top() - 8), animate)
        self.viewport().update()

    def ensure_visible(self):
        r = self.row_rect(self.current)
        sb = self.verticalScrollBar()
        vh = self.viewport().height()
        target = self.scroll_anim.endValue() if self.scroll_anim.state() == QPropertyAnimation.Running else sb.value()
        top = r.top() + sb.value()
        if top < target:
            self.scroll_to(top)
        elif top + ROW_H > target + vh:
            self.scroll_to(top + ROW_H - vh)


class SpaceRing(QWidget):
    def __init__(self, used):
        super().__init__()
        self.setFixedSize(36, 36)
        self.value = 0.0
        self.anim = QVariantAnimation(self, startValue=0.0, endValue=used, duration=1000,
                                      easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: (setattr(self, "value", v), self.update()))
        QTimer.singleShot(300, self.anim.start)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, 28, 28)
        p.setPen(QPen(QColor(SURFACE3), 4))
        p.drawEllipse(r)
        pen = QPen(QColor(ACCENT), 4)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawArc(r, 90 * 16, int(-self.value * 360 * 16))


class RollingLabel(QLabel):
    def __init__(self, fmt, **kw):
        super().__init__(**kw)
        self.fmt, self.v = fmt, None
        self.anim = QVariantAnimation(self, duration=380, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(lambda v: self.setText(self.fmt(v)))

    def roll(self, to):
        if self.v is None:
            self.v = to
            self.setText(self.fmt(to))
            return
        self.anim.stop()
        self.anim.setStartValue(float(self.v))
        self.anim.setEndValue(float(to))
        self.v = to
        self.anim.start()


class Card(QFrame):
    def __init__(self):
        super().__init__(objectName="card")
        self.setAttribute(Qt.WA_StyledBackground)

    def set_active(self, on):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class Dot(QWidget):
    def __init__(self, color):
        super().__init__()
        self.color = QColor(color)
        self.setFixedSize(18, 18)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        g = QRadialGradient(9, 9, 9)
        c = QColor(self.color)
        c.setAlpha(110)
        g.setColorAt(0, c)
        c.setAlpha(0)
        g.setColorAt(1, c)
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(0, 0, 18, 18)
        p.setBrush(self.color)
        p.drawEllipse(QRectF(5, 5, 8, 8))


class Details(Card):
    """Right-hand panel: blurred artwork behind, the cover, the game's details; fades in on each new game."""

    def __init__(self, library):
        super().__init__()
        self.library = library
        self.backdrop = None
        self.body = QWidget(self)
        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(22, 22, 22, 22)
        lay.setSpacing(6)
        self.cover = QLabel(alignment=Qt.AlignCenter)
        self.cover.setFixedHeight(290)
        self.title = QLabel(wordWrap=True)
        self.title.setStyleSheet("font-size: 21px; font-weight: 700;")
        self.meta = QLabel(objectName="muted")
        self.rating = QLabel(objectName="muted")
        self.genres = QHBoxLayout()
        self.genres.setSpacing(6)
        self.desc = QLabel(wordWrap=True)
        self.desc.setStyleSheet("color: #c3c8d6; line-height: 150%;")
        self.desc.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        video = QFrame(objectName="video")
        vl = QHBoxLayout(video)
        vl.setContentsMargins(12, 12, 12, 12)
        play = QLabel("▶", alignment=Qt.AlignCenter)
        play.setFixedSize(36, 36)
        play.setStyleSheet(f"background: {ACCENT}; color: #062033; border-radius: 18px;")
        vt = QLabel(f"<b>Gameplay video</b><br><span style='color:{MUTED}; font-size:12px'>ES-DE clip · plays here "
                    f"with sound</span>")
        vl.addWidget(play)
        vl.addWidget(vt, 1)
        self.file = QLabel(objectName="muted")
        self.file.setStyleSheet("font-size: 12px;")
        lay.addSpacing(4)
        lay.addWidget(self.cover)
        lay.addSpacing(14)
        lay.addWidget(self.title)
        lay.addWidget(self.meta)
        lay.addSpacing(4)
        lay.addWidget(self.rating)
        lay.addLayout(self.genres)
        lay.addSpacing(8)
        lay.addWidget(self.desc)
        lay.addSpacing(8)
        lay.addWidget(video)
        lay.addWidget(self.file)
        lay.addStretch(1)
        self.fade = QGraphicsOpacityEffect(self.body)
        self.body.setGraphicsEffect(self.fade)
        self.fade_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=260,
                                           easingCurve=QEasingCurve.OutCubic)
        self.fade_anim.valueChanged.connect(self._fade_step)
        self.shown_id = None

    def _fade_step(self, v):
        self.fade.setOpacity(v)
        self.body.move(0, int(8 * (1 - v)))

    def resizeEvent(self, e):
        self.body.setGeometry(0, self.body.y(), self.width(), self.height())

    def show_game(self, g):
        if not g or g.id == self.shown_id:
            return
        self.shown_id = g.id
        self.cover.setPixmap(with_shadow(cover(g.name, 170, 230, radius=8)))
        self.backdrop = blurred(cover(g.name, 120, 160, radius=0), 30)
        self.title.setText(g.name)
        self.meta.setText(f"{g.year} · {g.dev} · {g.pub}")
        n = round(g.rating)
        self.rating.setText(f"<span style='color:{STAR}; font-size:16px; letter-spacing:2px'>{'★' * n}{'☆' * (5 - n)}"
                            f"</span>&nbsp;&nbsp;{g.rating:.1f} · {300 + fnv(g.name) % 900} votes")
        while self.genres.count():
            w = self.genres.takeAt(0).widget()
            if w:
                w.deleteLater()
        for x in g.genre.split(", "):
            self.genres.addWidget(QLabel(x, objectName="genre"))
        self.genres.addStretch(1)
        self.desc.setText(self.library["descriptions"].get(g.name, self.library["defaultDescription"]))
        self.file.setText(f"{g.name} ({g.region}).zip · {mb(g.size)}")
        self.fade_anim.stop()
        self.fade_anim.start()
        self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.backdrop:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 12, 12)
        p.setClipPath(clip)
        p.setOpacity(.5)
        h = int(self.width() * 1.3)
        p.drawPixmap(QRect(-40, -60, self.width() + 80, h), self.backdrop)
        p.setOpacity(1)
        g = QLinearGradient(0, 0, 0, h - 60)
        c = QColor(SURFACE)
        c.setAlpha(0)
        g.setColorAt(0, c)
        g.setColorAt(.85, QColor(SURFACE))
        p.fillRect(QRect(0, 0, self.width(), h - 60), g)


class Toast(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet(f"background: rgba(38,43,56,235); border: 1px solid {BORDER}; border-radius: 12px;"
                           "padding: 10px 16px;")
        self.fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self.fx)
        self.fx.setOpacity(0)
        self.anim = QVariantAnimation(self, duration=300, easingCurve=QEasingCurve.OutCubic)
        self.anim.valueChanged.connect(self._step)
        self.hide_timer = QTimer(self, singleShot=True, interval=2200, timeout=lambda: self._go(0))
        self.v = 0.0

    def _step(self, v):
        self.v = v
        self.fx.setOpacity(v)
        self.adjustSize()
        par = self.parentWidget()
        self.move((par.width() - self.width()) // 2, par.height() - 76 - self.height() + int(30 * (1 - v)))

    def _go(self, to):
        self.anim.stop()
        self.anim.setStartValue(self.v)
        self.anim.setEndValue(float(to))
        self.anim.start()

    def show_text(self, text):
        self.setText(f"{text}&nbsp;&nbsp;<span style='background:{SURFACE3}; color:{ACCENT}'>&nbsp;Y&nbsp;</span> Undo")
        self.show()
        self.raise_()
        self._step(self.v)
        self._go(1)
        self.hide_timer.start()


class Glyph(QLabel):
    COLORS = {"A": "#5ad25a", "B": "#ff5f5f", "X": "#4aa3ff", "Y": "#ffd23f"}

    def __init__(self, text):
        super().__init__(text, alignment=Qt.AlignCenter)
        color = self.COLORS.get(text, "#c9cedb")
        radius = 12 if text in self.COLORS else 6
        self.setStyleSheet(f"background: {color}; color: #0b0d12; font-weight: 800; font-size: 11px;"
                           f"border-radius: {radius}px; padding: 0 6px; min-width: 12px;")
        self.setFixedHeight(24)


class Window(QWidget):
    def __init__(self, library):
        super().__init__()
        self.library = library
        self.setWindowTitle("RetroShelf (PySide6 mock-up)")
        self.setWindowIcon(QIcon(os.path.join(REPO, "assets", "icon-256.png")))
        self.resize(1280, 800)
        self.undo_stack = []

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(12)

        # top bar
        top = QHBoxLayout()
        top.setSpacing(14)
        icon = QLabel()
        icon.setPixmap(QPixmap(os.path.join(REPO, "assets", "icon-64.png")).scaled(
            28, 28, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        top.addWidget(icon)
        top.addWidget(QLabel("RetroShelf", objectName="brand"))
        system = QPushButton(objectName="system")
        sl = QHBoxLayout(system)
        sl.setContentsMargins(6, 0, 12, 0)
        sl.setSpacing(10)
        sl.addWidget(QLabel(library["system"], objectName="tag"))
        sl.addWidget(QLabel(library["systemName"]))
        sl.addWidget(QLabel("▾", objectName="muted"))
        system.setFixedHeight(38)
        system.setMinimumWidth(system.sizeHint().width() + 260)
        top.addWidget(system)
        self.search = QLineEdit(objectName="search", placeholderText="⌕  Search games")
        self.search.setFixedHeight(38)
        self.search.setMaximumWidth(420)
        self.search.textChanged.connect(self.on_search)
        top.addWidget(self.search, 1)
        top.addStretch(0)
        top.addWidget(SpaceRing(1 - library["freeGB"] / library["totalGB"]))
        space = QLabel(f"<b style='font-size:15px'>{library['freeGB']:.1f} GB free</b><br>"
                       f"<span style='color:{MUTED}; font-size:12px'>{library['romsPath']}</span>")
        top.addWidget(space)
        root.addLayout(top)

        # main: lists + details
        main = QHBoxLayout()
        main.setSpacing(16)
        left = QVBoxLayout()
        left.setSpacing(12)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for f in library["filters"]:
            label = f["label"].replace("&", "&&")
            b = QPushButton(("✓ " if f["on"] else "") + label, objectName="chip", checkable=True, checked=f["on"])
            b.toggled.connect(lambda on, b=b, label=label: b.setText(("✓ " if on else "") + label))
            b.setCursor(Qt.PointingHandCursor)
            chips.addWidget(b)
        chips.addStretch(1)
        left.addLayout(chips)
        cols = QHBoxLayout()
        cols.setSpacing(14)
        self.models, self.views, self.cards, self.counts, self.sizes = {}, {}, {}, {}, {}
        for kind, label, color in (("keep", "Keeping", KEEP), ("move", "Moving", MOVE)):
            card = Card()
            cl = QVBoxLayout(card)
            cl.setContentsMargins(0, 0, 0, 0)
            cl.setSpacing(0)
            head = QWidget(objectName="colhead")
            head.setAttribute(Qt.WA_StyledBackground)
            hl = QHBoxLayout(head)
            hl.setContentsMargins(12, 10, 16, 10)
            hl.setSpacing(6)
            hl.addWidget(Dot(color))
            t = QLabel(label)
            t.setStyleSheet("font-weight: 600;")
            hl.addWidget(t)
            count = RollingLabel(lambda v: str(round(v)))
            count.setStyleSheet("font-weight: 700;")
            hl.addWidget(count)
            hl.addStretch(1)
            size = RollingLabel(lambda v: f"{v:.1f} MB", objectName="muted")
            hl.addWidget(size)
            cl.addWidget(head)
            model = GameModel(kind)
            view = GameList(model)
            view.clicked.connect(lambda idx, k=kind: (self.set_active(k), self.select(k, idx.row())))
            view.doubleClicked.connect(lambda idx, k=kind: (self.select(k, idx.row()), self.flip_and_record()))
            cl.addWidget(view, 1)
            self.models[kind], self.views[kind], self.cards[kind] = model, view, card
            self.counts[kind], self.sizes[kind] = count, size
            cols.addWidget(card, 1)
        left.addLayout(cols, 1)
        main.addLayout(left, 1)
        self.details = Details(library)
        self.details.setFixedWidth(380)
        main.addWidget(self.details)
        root.addLayout(main, 1)

        # footer: gamepad hints + actions
        foot = QHBoxLayout()
        foot.setSpacing(16)
        self.hints = QWidget()
        self.hint_layout = QHBoxLayout(self.hints)
        self.hint_layout.setContentsMargins(0, 0, 0, 0)
        self.hint_layout.setSpacing(18)
        foot.addWidget(self.hints)
        foot.addStretch(1)
        foot.addWidget(QPushButton("Hide in ES-DE", objectName="ghost"))
        self.move_btn = QPushButton(objectName="primary")
        foot.addWidget(self.move_btn)
        root.addLayout(foot)
        self.toast = Toast(self)
        self.hint_fx = QGraphicsOpacityEffect(self.hints)
        self.hints.setGraphicsEffect(self.hint_fx)
        self.hint_anim = QVariantAnimation(self, startValue=0.0, endValue=1.0, duration=400,
                                           easingCurve=QEasingCurve.OutCubic)
        self.hint_anim.valueChanged.connect(self.hint_fx.setOpacity)

        self.models["keep"].all = [Game(r, None) for r in library["keeping"]]
        self.models["move"].all = [Game(r) for r in library["moving"]]
        for m in self.models.values():
            m.refresh()
        self.active = "keep"
        self.views["keep"].current = next(i for i, g in enumerate(self.models["keep"].items)
                                          if g.name == "Chrono Trigger")
        self.update_counts()
        QTimer.singleShot(0, lambda: (self.set_active("keep", animate=False), self.hint_anim.start()))
        self.start_gamepads()

    # ---------- painting ----------
    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG))
        g = QRadialGradient(self.width() * .2, -self.height() * .1, self.width() * .7)
        g.setColorAt(0, QColor("#1a2233"))
        g.setColorAt(1, QColor(26, 34, 51, 0))
        p.fillRect(self.rect(), g)

    # ---------- state ----------
    def other(self, kind):
        return "move" if kind == "keep" else "keep"

    def current_game(self, kind=None):
        kind = kind or self.active
        m, v = self.models[kind], self.views[kind]
        return m.items[v.current] if m.items else None

    def set_active(self, kind, animate=True):
        self.active = kind
        for k in ("keep", "move"):
            on = k == kind
            self.cards[k].set_active(on)
            self.views[k].ring.setVisible(on)
            self.views[k].ring.setEnabled(on)
        self.views[kind].place_ring(animate)
        self.details.show_game(self.current_game())
        self.update_hints()

    def select(self, kind, row):
        v = self.views[kind]
        v.current = max(0, min(row, self.models[kind].rowCount() - 1))
        v.place_ring()
        v.ensure_visible()
        self.details.show_game(self.current_game())

    def update_counts(self):
        for k in ("keep", "move"):
            games = self.models[k].all
            self.counts[k].roll(len(games))
            self.sizes[k].roll(sum(g.size for g in games))
        mv = self.models["move"].all
        self.move_btn.setText(f"Move {len(mv)} games · {sum(g.size for g in mv):.1f} MB")
        self.update_hints()

    def update_hints(self):
        marked = len(self.models["keep"].marked | self.models["move"].marked)
        x = f"Flip {marked} marked" if marked else ("Move" if self.active == "keep" else "Keep")
        while self.hint_layout.count():
            w = self.hint_layout.takeAt(0).widget()
            if w:
                w.deleteLater()
        for glyph, text in (("A", "Mark"), ("X", x), ("Y", "Undo"), ("LB/RB", "Switch list"), ("B", "Close")):
            box = QWidget()
            bl = QHBoxLayout(box)
            bl.setContentsMargins(0, 0, 0, 0)
            bl.setSpacing(7)
            bl.addWidget(Glyph(glyph))
            bl.addWidget(QLabel(text, objectName="muted"))
            self.hint_layout.addWidget(box)

    def on_search(self, text):
        for k in ("keep", "move"):
            self.models[k].query = text.lower()
            self.models[k].refresh()
            self.views[k].place_ring(False)
        self.details.show_game(self.current_game())

    # ---------- flipping, with the row flying across ----------
    def flip(self, ids=None, src_kind=None, dst_kind=None):
        src_kind = src_kind or self.active
        dst_kind = dst_kind or self.other(src_kind)
        sm, dm = self.models[src_kind], self.models[dst_kind]
        sv, dv = self.views[src_kind], self.views[dst_kind]
        if ids is None:
            ids = set(sm.marked) if sm.marked else ({self.current_game(src_kind).id} if sm.items else set())
        games = [g for g in sm.all if g.id in ids]
        if not games:
            return None
        before = {k: {g.id: i for i, g in enumerate(self.models[k].items)} for k in ("keep", "move")}
        ghosts = []
        for g in games:
            row = before[src_kind].get(g.id)
            if row is None:
                continue
            r = sv.row_rect(row)
            if r.bottom() < 0 or r.top() > sv.viewport().height():
                continue
            pix = sv.viewport().grab(r.adjusted(6, 0, -6, 0))
            ghosts.append((g, pix, sv.viewport().mapTo(self, r.topLeft() + QPoint(6, 0))))
        sm.all = [g for g in sm.all if g.id not in ids]
        for g in games:
            if dst_kind == "move" and not g.why:
                g.why = "flipped by hand"
            dm.all.append(g)
        sm.marked.clear()
        dm.marked.clear()
        sm.refresh()
        dm.refresh()
        now = time.monotonic()
        for k in ("keep", "move"):  # rows that shifted glide to their new places
            v = self.views[k]
            for i, g in enumerate(self.models[k].items):
                old = before[k].get(g.id)
                if old is not None and old != i:
                    v.fx.offset[g.id] = ((old - i) * ROW_H, now, .26)
            v.fx.kick()
        sv.place_ring(False)
        self.details.show_game(self.current_game())
        self.update_counts()
        for g, pix, start in ghosts:
            self.fly(g, pix, start, dst_kind)
        return {"ids": {g.id for g in games}, "src": src_kind, "dst": dst_kind, "names": [g.name for g in games]}

    def fly(self, g, pix, start, dst_kind):
        dv, dm = self.views[dst_kind], self.models[dst_kind]
        row = next(i for i, x in enumerate(dm.items) if x.id == g.id)
        r = dv.row_rect(row)
        if r.top() < 0 or r.bottom() > dv.viewport().height():  # bring it into view first
            sb = dv.verticalScrollBar()
            sb.setValue(max(0, r.top() + sb.value() - dv.viewport().height() // 2))
            r = dv.row_rect(row)
        end = dv.viewport().mapTo(self, r.topLeft() + QPoint(6, 0))
        dv.fx.hidden.add(g.id)
        ghost = QLabel(self)
        ghost.setPixmap(pix)
        ghost.setStyleSheet(f"background: {SURFACE3}; border-radius: 10px;")
        ghost.setAttribute(Qt.WA_TransparentForMouseEvents)
        ghost.setGraphicsEffect(QGraphicsDropShadowEffect(blurRadius=50, offset=QPointF(0, 18),
                                                          color=QColor(0, 0, 0, 140)))
        ghost.move(start)
        ghost.show()
        ghost.raise_()
        anim = QPropertyAnimation(ghost, b"pos", ghost)
        anim.setDuration(420)
        anim.setStartValue(start)
        anim.setKeyValueAt(.5, QPoint((start.x() + end.x()) // 2, (start.y() + end.y()) // 2 - 30))
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.OutCubic)

        def landed():
            ghost.deleteLater()
            dv.fx.hidden.discard(g.id)
            dv.fx.glow[g.id] = 1.0
            dv.fx.kick()

        anim.finished.connect(landed)
        anim.start()

    def flip_and_record(self):
        done = self.flip()
        if not done:
            return
        self.undo_stack.append(done)
        names = done["names"]
        self.toast.show_text(f"{'Moving' if done['dst'] == 'move' else 'Keeping'} {names[0]}" if len(names) == 1
                             else f"{len(names)} games flipped")

    def undo(self):
        if not self.undo_stack:
            return
        u = self.undo_stack.pop()
        self.flip(u["ids"], u["dst"], u["src"])
        self.toast.show_text("Undone")

    # ---------- input: keyboard, and gamepads mapped onto the same keys ----------
    def keyPressEvent(self, e):
        if self.handle(e.key(), e.modifiers()):
            e.accept()
        else:
            super().keyPressEvent(e)

    def focusNextPrevChild(self, nxt):  # Tab switches lists instead of moving the keyboard focus
        if self.search.hasFocus():
            return super().focusNextPrevChild(nxt)
        self.handle(Qt.Key_Tab, Qt.NoModifier)
        return True

    def handle(self, key, mods=Qt.NoModifier):
        k, v = self.active, self.views[self.active]
        n = self.models[k].rowCount()
        page = max(1, v.viewport().height() // ROW_H)
        if self.search.hasFocus():
            if key in (Qt.Key_Escape, Qt.Key_Down, Qt.Key_Return):
                self.setFocus()
                return True
            return False
        if key == Qt.Key_Down:
            self.select(k, v.current + 1)
        elif key == Qt.Key_Up:
            self.select(k, v.current - 1)
        elif key == Qt.Key_PageDown:
            self.select(k, v.current + page)
        elif key == Qt.Key_PageUp:
            self.select(k, v.current - page)
        elif key == Qt.Key_Home:
            self.select(k, 0)
        elif key == Qt.Key_End:
            self.select(k, n - 1)
        elif key in (Qt.Key_Right, Qt.Key_Delete) and k == "keep" or key == Qt.Key_Left and k == "move" \
                or key in (Qt.Key_Return, Qt.Key_Enter):
            v.ring.pulse()
            self.flip_and_record()
        elif key == Qt.Key_Space:
            g = self.current_game()
            if g:
                marked = self.models[k].marked
                marked.symmetric_difference_update({g.id})
                v.ring.pulse()
                self.select(k, v.current + 1)
                self.update_hints()
        elif key in (Qt.Key_Tab, Qt.Key_Backtab):
            self.set_active(self.other(k))
        elif key == Qt.Key_Z and mods & Qt.ControlModifier or key == Qt.Key_Backspace:
            self.undo()
        elif key == Qt.Key_Slash or key == Qt.Key_F and mods & Qt.ControlModifier:
            self.search.setFocus()
        else:
            return False
        return True

    def start_gamepads(self):
        try:
            import gamepad  # RetroShelf's own reader: /dev/input on Linux, XInput on Windows
        except Exception:
            return
        self.pad_source, self.pad_repeat = gamepad.default_source(), gamepad.Repeater()
        if not self.pad_source:
            return
        keys = {"up": Qt.Key_Up, "down": Qt.Key_Down, "left": Qt.Key_Left, "right": Qt.Key_Right, "a": Qt.Key_Space,
                "x": Qt.Key_Return, "y": Qt.Key_Backspace, "lb": Qt.Key_Tab, "rb": Qt.Key_Tab, "lt": Qt.Key_PageUp,
                "rt": Qt.Key_PageDown}

        def poll():
            if not self.isActiveWindow():
                return
            now = time.monotonic()
            pressed, _new = self.pad_source.poll(now)
            for b in self.pad_repeat.update(pressed, now):
                if b in keys:
                    self.handle(keys[b])

        self.pad_timer = QTimer(self, interval=gamepad.POLL_MS, timeout=poll)
        self.pad_timer.start()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    font = QFont(FONT)
    font.setPixelSize(14)
    app.setFont(font)
    pal = app.palette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(MUTED))
    app.setPalette(pal)
    app.setStyleSheet(QSS)
    with open(os.path.join(REPO, "mockups", "shared", "games.json"), encoding="utf-8") as f:
        library = json.load(f)
    win = Window(library)
    if os.environ.get("MOCKUP_CAPTURE"):
        win.setWindowFlag(Qt.FramelessWindowHint)
        win.move(0, 0)
    win.show()
    win.setFocus()
    if os.environ.get("MOCKUP_CAPTURE"):
        capture(win, os.environ["MOCKUP_CAPTURE"])
    sys.exit(app.exec())


# The same scripted demo as the Electron mock-up: keys at set times, screenshots at three points.
DEMO = [(1500, "shot", "main.png")] + [(250, Qt.Key_Down, None)] * 5 + [
    (250, Qt.Key_Right, None), (1200, "shot", "after-flip.png"), (0, Qt.Key_Space, None), (350, Qt.Key_Space, None),
    (350, Qt.Key_Return, None), (1200, Qt.Key_Tab, None), (600, Qt.Key_Down, None), (300, Qt.Key_Down, None),
    (300, Qt.Key_Left, None), (1200, Qt.Key_Z, Qt.ControlModifier), (1200, "shot", "end.png"), (100, "quit", None)]


def capture(win, out):
    os.makedirs(out, exist_ok=True)
    t = 0
    for delay, what, arg in DEMO:
        t += delay
        if what == "shot":
            QTimer.singleShot(t, lambda arg=arg: win.grab().save(os.path.join(out, arg)))
        elif what == "quit":
            QTimer.singleShot(t, QApplication.quit)
        else:
            QTimer.singleShot(t, lambda what=what, arg=arg: win.handle(what, arg or Qt.NoModifier))


if __name__ == "__main__":
    main()
