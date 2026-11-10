from copy import deepcopy
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QFormLayout, QComboBox, QCheckBox, QSpinBox,
    QDoubleSpinBox, QLineEdit, QVBoxLayout, QHBoxLayout, QTabWidget, QGroupBox,
    QDialog, QDialogButtonBox, QListWidget, QListWidgetItem, QAbstractItemView,
    QScrollArea, QMessageBox, QFileDialog)
from ..config import DEFAULTS, validate_settings
from ..domain import RISK_PROFILES
from ..storage import new_watchlist, validate_watchlist
from .filters import FilterBuilder
from .widgets import label, button


class Preferences(QWidget):
    def __init__(self, data=None, parent=None):
        super().__init__(parent)
        self.original = validate_settings(data or {})
        self.controls = {}
        layout = QVBoxLayout(self); tabs = QTabWidget(); layout.addWidget(tabs)
        for title, keys in (("Monitoring", ["catalog_interval_minutes", "global_priority", "retention_days", "dense_table"]),
                            ("Risk", ["risk_profile"]),
                            ("Notifications", ["in_app", "desktop", "sound", "sound_path", "highlight", "notify_existing", "notify_new", "notify_price", "notification_limit"])):
            widget = QWidget(); form = QFormLayout(widget); form.setSpacing(12); tabs.addTab(widget, title)
            for key in keys:
                value = self.original[key]
                if type(value) is bool:
                    control = QCheckBox(); control.setChecked(value)
                elif type(value) is int:
                    control = QSpinBox()
                    ranges = {"catalog_interval_minutes": (60, 1440), "global_priority": (1,10), "retention_days": (7,3650), "notification_limit": (1,60)}
                    control.setRange(*ranges[key]); control.setValue(value)
                elif key == "risk_profile":
                    control = QComboBox(); control.addItems(list(RISK_PROFILES)); control.setCurrentText(value)
                else: control = QLineEdit(value)
                self.controls[key] = control
                names = {"catalog_interval_minutes": "Catalog check interval (minutes)", "global_priority": "Global request priority",
                         "notification_limit": "Maximum alerts per minute", "retention_days": "History retention (days; manual prune)",
                         "sound_path": "Local WAV file", "notify_existing": "Notify on existing listings", "notify_new": "Notify on new discoveries", "notify_price": "Notify on price changes"}
                form.addRow(names.get(key, key.replace("_", " ").title()), control)
            if title == "Risk":
                for key, value in self.original["risk_thresholds"].items():
                    control = QDoubleSpinBox(); control.setDecimals(0 if key == "samples" else 1)
                    limits = {"discount": (0,100), "profit": (0,1000000), "confidence": (0,100), "samples": (5,10000), "max_age_hours": (1,8760)}
                    control.setRange(*limits[key]); control.setValue(value)
                    self.controls["threshold_"+key] = control
                    form.addRow({"discount":"Minimum estimated discount (%)", "profit":"Minimum potential gross profit (p)", "confidence":"Minimum confidence (%)", "samples":"Minimum comparable count", "max_age_hours":"Maximum observation age (hours)"}[key], control)
                form.addRow(label("Estimates use asking prices. They do not predict a completed sale or guarantee profit.", "subtitle", True))
            if title == "Notifications":
                form.addRow(button("Choose sound…", self.choose_sound))
                self.statuses = {}
                for status in ("ingame", "online", "offline", "unknown"):
                    check = QCheckBox({"ingame": "In Game", "online": "Online", "offline": "Offline", "unknown": "Unknown"}[status])
                    check.setChecked(status in self.original["notification_statuses"])
                    self.statuses[status] = check; form.addRow("Notify for seller status", check)
                self.priority = QComboBox()
                self.priority.addItem("In Game → Online → Offline", ["ingame", "online", "offline", "unknown"])
                self.priority.addItem("Online → In Game → Offline", ["online", "ingame", "offline", "unknown"])
                self.priority.setCurrentIndex(max(0, self.priority.findData(self.original["seller_priority"])))
                form.addRow("Seller ranking priority", self.priority)
        self.controls["risk_profile"].currentTextChanged.connect(self.profile_changed)

    def choose_sound(self):
        path, _ = QFileDialog.getOpenFileName(self, "Choose notification sound", "", "Wave audio (*.wav)")
        if path: self.controls["sound_path"].setText(path)

    def profile_changed(self, profile):
        for key, value in RISK_PROFILES[profile].items(): self.controls["threshold_"+key].setValue(value)

    def values(self):
        result = deepcopy(self.original)
        for key, control in self.controls.items():
            if key.startswith("threshold_"): result["risk_thresholds"][key[10:]] = control.value()
            elif isinstance(control, QCheckBox): result[key] = control.isChecked()
            elif isinstance(control, QSpinBox): result[key] = control.value()
            elif isinstance(control, QComboBox): result[key] = control.currentText()
            else: result[key] = control.text()
        result["notification_statuses"] = [k for k,v in self.statuses.items() if v.isChecked()]
        result["seller_priority"] = self.priority.currentData()
        return validate_settings(result)


class WatchlistDialog(QDialog):
    def __init__(self, weapons, attributes, settings, value=None, parent=None):
        super().__init__(parent); self.setWindowTitle("Watchlist editor"); self.resize(800, 690)
        self.value = deepcopy(value or new_watchlist()); self.result_value = None
        self.weapons_data, self.attributes_data = weapons, attributes
        layout = QVBoxLayout(self); tabs = QTabWidget(); layout.addWidget(tabs)
        general = QWidget(); form = QFormLayout(general); tabs.addTab(general, "Search & priority")
        self.name = QLineEdit(self.value["name"]); form.addRow("Name", self.name)
        self.enabled = QCheckBox("Enabled when a supported contract source becomes available")
        self.enabled.setChecked(self.value["enabled"]); form.addRow(self.enabled)
        self.priority = QSpinBox(); self.priority.setRange(1,10); self.priority.setValue(self.value["priority"]); form.addRow("Priority (1–10)", self.priority)
        self.category = QComboBox(); self.category.addItem("All weapon types", "")
        categories = sorted({w.get("rivenType", "unknown") for w in weapons})
        for category in categories: self.category.addItem(category.title(), category)
        self.category.setCurrentIndex(max(0, self.category.findData(self.value["category"])))
        form.addRow("Weapon type", self.category)
        self.weapon_search = QLineEdit(); self.weapon_search.setPlaceholderText("Find weapons… (Ctrl-click to select a group)"); form.addRow(self.weapon_search)
        self.weapons = QListWidget(); self.weapons.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        for weapon in sorted(weapons, key=lambda w:w["slug"]):
            item = QListWidgetItem(weapon.get("i18n",{}).get("en",{}).get("name", weapon["slug"]))
            item.setData(Qt.ItemDataRole.UserRole, weapon["slug"]); self.weapons.addItem(item)
            item.setSelected(weapon["slug"] in self.value["weapons"])
        form.addRow("Weapons (none = all)", self.weapons)
        self.weapon_search.textChanged.connect(lambda text: [self.weapons.item(i).setHidden(text.casefold() not in self.weapons.item(i).text().casefold()) for i in range(self.weapons.count())])
        form.addRow(label("Set maximum/minimum price, attribute ranges and seller-status logic in Conditions. All local presets are retained; live search is currently unavailable.", "subtitle", True))
        self.builder = FilterBuilder(attributes); self.builder.set_expression(self.value["filter"]); tabs.addTab(self.builder, "Conditions")
        self.preferences = Preferences(settings | self.value["settings"]); tabs.addTab(self.preferences, "Alerts & risk")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)

    def save(self):
        try:
            value = self.value | {"name": self.name.text().strip(), "enabled": self.enabled.isChecked(),
                "priority": self.priority.value(), "category": self.category.currentData(),
                "weapons": [item.data(Qt.ItemDataRole.UserRole) for item in self.weapons.selectedItems()],
                "filter": self.builder.expression(), "settings": self.preferences.values()}
            validate_watchlist(value, {a["slug"]:a for a in self.attributes_data} or None, {w["slug"]:w for w in self.weapons_data} or None)
            self.result_value = value; self.accept()
        except ValueError as error: QMessageBox.warning(self, "Invalid watchlist", str(error))
