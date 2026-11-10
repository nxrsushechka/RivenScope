import json
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget, QTreeWidgetItem,
    QDialog, QFormLayout, QComboBox, QLineEdit, QDialogButtonBox, QMessageBox, QInputDialog)
from ..filters import FIELDS, OPS, field_type, validate
from .widgets import button, label

OP_LABELS = {"eq": "equals", "ne": "does not equal", "gt": "greater than", "ge": "at least",
             "lt": "less than", "le": "at most", "exists": "exists", "absent": "is absent",
             "contains": "contains text", "in": "is one of"}


class ConditionDialog(QDialog):
    def __init__(self, attributes, condition=None, parent=None):
        super().__init__(parent); self.setWindowTitle("Filter condition"); self.setMinimumWidth(480)
        self.result_condition = None
        layout = QVBoxLayout(self); form = QFormLayout(); layout.addLayout(form)
        self.field = QComboBox()
        for field in FIELDS: self.field.addItem(field.replace("_", " ").title(), field)
        for attribute in attributes:
            name = attribute.get("i18n", {}).get("en", {}).get("name", attribute["slug"])
            for prefix in ("positive", "negative", "attribute"):
                if prefix == "negative" and attribute.get("positiveOnly"): continue
                if prefix == "positive" and attribute.get("negativeOnly"): continue
                self.field.addItem(f"{prefix.title()} · {name}", prefix + "." + attribute["slug"])
        self.op = QComboBox()
        for op in OPS: self.op.addItem(OP_LABELS[op], op)
        self.value = QLineEdit(); self.value.setPlaceholderText("Use slugs for weapon/category; comma-separated for 'one of'")
        form.addRow("Field", self.field); form.addRow("Operator", self.op); form.addRow("Value", self.value)
        layout.addWidget(label("Missing values do not match comparisons, including NOT. Use 'is absent' explicitly.", "subtitle", True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.save); buttons.rejected.connect(self.reject); layout.addWidget(buttons)
        self.op.currentIndexChanged.connect(lambda: self.value.setEnabled(self.op.currentData() not in ("exists", "absent")))
        if condition:
            index = self.field.findData(condition["field"])
            if index < 0:
                self.field.addItem(condition["field"], condition["field"]); index = self.field.count()-1
            self.field.setCurrentIndex(index); self.op.setCurrentIndex(self.op.findData(condition["op"]))
            value = condition.get("value", "")
            self.value.setText(", ".join(map(str, value)) if isinstance(value, list) else str(value))

    def save(self):
        try:
            field, op = self.field.currentData(), self.op.currentData()
            result = {"field": field, "op": op}
            if op not in ("exists", "absent"):
                kind = field_type(field)
                def convert(value):
                    if kind == "number": return float(value)
                    if kind == "bool":
                        if value.lower() not in ("true", "false"): raise ValueError("Use true or false")
                        return value.lower() == "true"
                    return value
                text = self.value.text().strip()
                result["value"] = [convert(v.strip()) for v in text.split(",")] if op == "in" else convert(text)
            validate(result)
            self.result_condition = result; self.accept()
        except ValueError as error: QMessageBox.warning(self, "Invalid condition", str(error))


class FilterBuilder(QWidget):
    def __init__(self, attributes=None, parent=None):
        super().__init__(parent); self.attributes = attributes or []
        layout = QVBoxLayout(self); layout.setContentsMargins(0,0,0,0)
        layout.addWidget(label("Build nested conditions. Select a group to add children; double-click to edit.", "subtitle", True))
        self.tree = QTreeWidget(); self.tree.setHeaderLabels(["Logic / field", "Operator", "Value"])
        self.tree.setColumnWidth(0, 260); self.tree.setColumnWidth(1, 150)
        self.tree.itemDoubleClicked.connect(lambda *_: self.edit())
        layout.addWidget(self.tree)
        actions = QHBoxLayout()
        for text, callback in (("+ Condition", self.add_condition), ("+ Group", self.add_group), ("Edit", self.edit), ("Remove", self.remove)):
            actions.addWidget(button(text, callback))
        layout.addLayout(actions)
        self.set_expression({"op": "AND", "children": []})

    def set_expression(self, expression):
        self.tree.clear()
        self._add(expression, self.tree)
        self.tree.expandAll(); self.tree.setCurrentItem(self.tree.topLevelItem(0))

    def _add(self, expression, parent):
        item = QTreeWidgetItem(parent)
        if expression["op"] in ("AND", "OR", "NOT"):
            item.setText(0, expression["op"]); item.setData(0, Qt.ItemDataRole.UserRole, {"op": expression["op"]})
            for child in expression["children"]: self._add(child, item)
        else:
            item.setText(0, expression["field"]); item.setText(1, OP_LABELS[expression["op"]])
            item.setText(2, str(expression.get("value", "")))
            item.setData(0, Qt.ItemDataRole.UserRole, expression)
        return item

    def expression(self):
        def walk(item):
            data = dict(item.data(0, Qt.ItemDataRole.UserRole))
            if data["op"] in ("AND", "OR", "NOT"):
                data["children"] = [walk(item.child(i)) for i in range(item.childCount())]
            return data
        result = walk(self.tree.topLevelItem(0)); validate(result); return result

    def target(self):
        item = self.tree.currentItem() or self.tree.topLevelItem(0)
        if item.data(0, Qt.ItemDataRole.UserRole)["op"] not in ("AND", "OR", "NOT"):
            item = item.parent()
        return item

    def add_condition(self):
        dialog = ConditionDialog(self.attributes, parent=self)
        if dialog.exec(): self._add(dialog.result_condition, self.target()); self.tree.expandAll()

    def add_group(self):
        op, ok = QInputDialog.getItem(self, "Logical group", "Combine conditions using", ["AND", "OR", "NOT"], editable=False)
        if ok: self._add({"op": op, "children": []}, self.target()); self.tree.expandAll()

    def edit(self):
        item = self.tree.currentItem()
        if item is None: return
        value = item.data(0, Qt.ItemDataRole.UserRole)
        if value["op"] in ("AND", "OR", "NOT"):
            op, ok = QInputDialog.getItem(self, "Logical group", "Operator", ["AND", "OR", "NOT"], editable=False)
            if ok: item.setData(0, Qt.ItemDataRole.UserRole, {"op": op}); item.setText(0, op)
        else:
            dialog = ConditionDialog(self.attributes, value, self)
            if dialog.exec():
                parent = item.parent(); position = parent.indexOfChild(item)
                parent.takeChild(position); replacement = self._add(dialog.result_condition, parent)
                self.tree.setCurrentItem(replacement)

    def remove(self):
        item = self.tree.currentItem()
        if item and item.parent(): item.parent().removeChild(item)
