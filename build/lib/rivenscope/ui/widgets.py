import json
import math
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, QSortFilterProxyModel, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableView, QHeaderView, QAbstractItemView, QFrame, QSizePolicy)

STYLE = """
QWidget { background: #10121c; color: #dce2f0; font-family: 'Inter', 'Noto Sans', sans-serif; font-size: 13px; }
QMainWindow, QStackedWidget { background: #10121c; }
QFrame#sidebar { background: #0c0e17; border-right: 1px solid #252a3d; }
QLabel#brand { font-size: 24px; font-weight: 800; color: #c3a5ff; }
QLabel#pageTitle { font-size: 28px; font-weight: 700; }
QLabel#subtitle { color: #919bb5; }
QLabel#banner { color: #f0cb8b; background: #2a241e; border: 1px solid #59452f; border-radius: 8px; padding: 12px; }
QLabel#notice { color: #83ddc6; padding: 8px; }
QFrame#card { background: #191d2c; border: 1px solid #2c3249; border-radius: 10px; }
QFrame#card QLabel { background: transparent; border: none; }
QLabel#metric { font-size: 29px; font-weight: 700; color: #bfa2ff; }
QPushButton { background: #22283b; border: 1px solid #353e58; border-radius: 6px; padding: 8px 13px; }
QPushButton:hover { background: #333c57; border-color: #8e72d0; }
QPushButton:pressed { background: #685299; }
QPushButton:disabled { color: #677088; background: #191d2a; border-color: #262b3e; }
QPushButton#primary { background: #7453b8; border-color: #9670df; color: white; font-weight: 600; }
QPushButton#primary:disabled { background: #262038; color: #8d7ca9; border-color: #3c3052; }
QListWidget#navigation { background: transparent; border: none; font-size: 14px; outline: none; }
QListWidget#navigation::item { padding: 13px; margin: 3px 7px; border-radius: 7px; }
QListWidget#navigation::item:selected { background: #2f2448; color: #d4baff; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox { background: #191e2e; border: 1px solid #333c53; border-radius: 5px; padding: 7px; selection-background-color: #694b9e; }
QLineEdit:focus, QComboBox:focus { border-color: #ad89ed; }
QComboBox QAbstractItemView { background: #191e2e; selection-background-color: #47345f; }
QTableView, QTreeWidget, QListWidget, QTextEdit, QTextBrowser { background: #141824; alternate-background-color: #191e2b; border: 1px solid #2a3146; border-radius: 6px; selection-background-color: #342b4d; gridline-color: #242b3c; }
QHeaderView::section { background: #202638; color: #9eabc5; border: none; border-bottom: 1px solid #37415a; padding: 9px; font-size: 11px; font-weight: 600; }
QTableView::item { padding: 6px; border-bottom: 1px solid #222839; }
QTabWidget::pane { border: none; padding-top: 8px; }
QTabBar::tab { background: #171c2a; padding: 11px 20px; border-bottom: 2px solid #242c40; }
QTabBar::tab:selected { color: #c8aaff; border-bottom: 2px solid #b28ce8; }
QScrollBar:vertical { background: #111521; width: 9px; }
QScrollBar::handle:vertical { background: #3c4763; border-radius: 4px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0px; }
QGroupBox { border: 1px solid #2e374d; border-radius: 7px; margin-top: 12px; padding: 14px; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; color: #b4c0dc; }
QCheckBox { spacing: 8px; padding: 4px; }
QToolTip { background: #273047; color: white; border: 1px solid #705898; padding: 6px; }
QStatusBar { background: #0c101a; color: #919db6; }
QSplitter::handle { background: #282f43; width: 3px; }
"""


def label(text, name="", wrap=False):
    result = QLabel(text)
    result.setTextFormat(Qt.TextFormat.PlainText)
    result.setWordWrap(wrap)
    result.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
    if name: result.setObjectName(name)
    return result


def button(text, callback, primary=False):
    result = QPushButton(text)
    if primary: result.setObjectName("primary")
    result.clicked.connect(callback)
    return result


def page(title, subtitle):
    widget = QWidget(); layout = QVBoxLayout(widget)
    layout.setContentsMargins(28, 24, 28, 20); layout.setSpacing(15)
    layout.addWidget(label(title, "pageTitle")); layout.addWidget(label(subtitle, "subtitle", True))
    return widget, layout


class Metric(QFrame):
    def __init__(self, title, value="—", detail=""):
        super().__init__(); self.setObjectName("card")
        layout = QVBoxLayout(self); layout.setContentsMargins(18, 16, 18, 16)
        layout.addWidget(label(title.upper(), "subtitle"))
        self.value = label(value, "metric"); layout.addWidget(self.value)
        self.detail = label(detail, "subtitle", True); layout.addWidget(self.detail)


class TableModel(QAbstractTableModel):
    def __init__(self, columns, parent=None):
        super().__init__(parent); self.columns = columns; self.rows = []; self.highlighted = set()
        self.sort_column = -1; self.sort_order = Qt.SortOrder.AscendingOrder

    def set_rows(self, rows):
        self.beginResetModel(); self.rows = rows
        self._sort_rows()
        self.endResetModel()

    def _sort_rows(self):
        if self.sort_column >= 0:
            getter = self.columns[self.sort_column][1]
            # One Python key evaluation per row, rather than O(n log n) Qt/Python callbacks.
            def key(row):
                value = getter(row)
                return (value is None, value)
            self.rows = sorted(self.rows, key=key, reverse=self.sort_order == Qt.SortOrder.DescendingOrder)

    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        self.beginResetModel(); self.sort_column = column; self.sort_order = order
        self._sort_rows(); self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.columns)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole and orientation == Qt.Orientation.Horizontal:
            return self.columns[section][0]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid(): return None
        row = self.rows[index.row()]; value = self.columns[index.column()][1](row)
        if role == Qt.ItemDataRole.UserRole: return value
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            if value is None: return "—"
            if isinstance(value, float): return f"{value:,.1f}"
            if isinstance(value, bool): return "Yes" if value else "No"
            return str(value)
        if role == Qt.ItemDataRole.ForegroundRole:
            if index.column() == 0: return QColor("#c8aff7")
        if role == Qt.ItemDataRole.BackgroundRole and row.get("id", getattr(row.get("listing"), "id", None)) in self.highlighted:
            return QColor("#28403d")


class TableProxy(QSortFilterProxyModel):
    def sort(self, column, order=Qt.SortOrder.AscendingOrder):
        super().sort(-1)
        self.sourceModel().sort(column, order)


class Table(QWidget):
    selected = Signal(object)

    def __init__(self, columns, searchable=True, parent=None):
        super().__init__(parent)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        from PySide6.QtWidgets import QLineEdit
        layout = QVBoxLayout(self); layout.setContentsMargins(0, 0, 0, 0)
        self.model = TableModel(columns, self)
        self.proxy = TableProxy(self); self.proxy.setSourceModel(self.model)
        self.proxy.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.proxy.setFilterKeyColumn(-1); self.proxy.setSortRole(Qt.ItemDataRole.UserRole)
        self.search = QLineEdit(); self.search.setPlaceholderText("Search this table…")
        self.search.textChanged.connect(self.proxy.setFilterFixedString)
        if searchable: layout.addWidget(self.search)
        self.view = QTableView(); self.view.setModel(self.proxy)
        self.view.setAlternatingRowColors(True); self.view.setShowGrid(False)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self.view.setSortingEnabled(True); self.view.verticalHeader().hide()
        self.view.verticalHeader().setDefaultSectionSize(34)
        self.view.horizontalHeader().setSectionsMovable(True)
        self.view.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.view.horizontalHeader().setStretchLastSection(True)
        self.view.selectionModel().currentRowChanged.connect(self._selected)
        layout.addWidget(self.view)

    def _selected(self, current, previous):
        index = self.proxy.mapToSource(current)
        if index.isValid(): self.selected.emit(self.model.rows[index.row()])


class Chart(QWidget):
    """CPU-rendered bounded chart, no plotting runtime or GPU dependency."""
    def __init__(self, title, parent=None, bars=False):
        super().__init__(parent); self.title = title; self.points = []; self.unit = ""; self.bars = bars
        self.setMinimumHeight(210); self.setMinimumWidth(280)

    def set_points(self, points, unit=""):
        self.points = sorted(points)[-2000:]; self.unit = unit; self.update()

    def paintEvent(self, event):
        from PySide6.QtCore import QPointF, QRectF
        painter = QPainter(self); painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor("#171c2b")); painter.setPen(QColor("#bdc7de"))
        painter.drawText(18, 27, self.title)
        if not self.points:
            painter.setPen(QColor("#7f8ba5"))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "No observations yet\nHistory starts with verified observations")
            return
        x0, y0, width, height = 65, 48, self.width()-90, self.height()-110
        xs, ys = zip(*self.points); low, high = min(ys), max(ys)
        if self.bars: low = 0
        spread = high-low or max(abs(high)*.1, 1)
        for i in range(5):
            y = y0 + height * i / 4
            painter.setPen(QColor("#2b3348")); painter.drawLine(int(x0), int(y), int(x0+width), int(y))
            painter.setPen(QColor("#8593ae")); painter.drawText(7, int(y)+4, f"{high-spread*i/4:.0f}")
        points = [QPointF(x0+(x-min(xs))/max(max(xs)-min(xs), 1)*width, y0+(high-y)/spread*height) for x,y in self.points]
        painter.setPen(QPen(QColor("#b293f2"), 2))
        if self.bars:
            painter.setBrush(QColor("#8b70ba"))
            for point in points: painter.drawRect(QRectF(point.x()-width/len(points)*.35, point.y(), width/len(points)*.7, y0+height-point.y()))
        else:
            for a,b in zip(points, points[1:]): painter.drawLine(a,b)
            if len(points) == 1: painter.drawEllipse(points[0], 3, 3)
        from datetime import datetime, timezone
        def tick(value):
            return datetime.fromtimestamp(value,timezone.utc).strftime("%m-%d %H:%M") if value > 1_000_000_000 else f"{value:g}"
        painter.setPen(QColor("#8593ae"))
        painter.drawText(65, self.height()-40, tick(min(xs)))
        painter.drawText(self.width()-135, self.height()-40, tick(max(xs)))
        painter.setPen(QColor("#8593ae")); painter.drawText(65, self.height()-16, self.unit)
