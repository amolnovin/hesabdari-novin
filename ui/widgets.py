# -*- coding: utf-8 -*-
"""ابزارک‌ها و توابع کمکیِ رابط کاربری"""

import csv
import os
from datetime import date, datetime

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextDocument
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QAbstractButton, QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFileDialog,
    QFormLayout, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QMessageBox, QPushButton, QSizePolicy, QTableWidget, QTableWidgetItem,
    QTextEdit, QVBoxLayout, QWidget,
)

import auth
import jalali
import utils


# ---------------------------------------------------------------------------
# پیام‌ها
# ---------------------------------------------------------------------------
def msg_info(parent, text, title="توجه"):
    QMessageBox.information(parent, title, text)


def msg_warn(parent, text, title="هشدار"):
    QMessageBox.warning(parent, title, text)


def msg_error(parent, text, title="خطا"):
    QMessageBox.critical(parent, title, text)


def msg_ask(parent, text, title="تأیید") -> bool:
    return QMessageBox.question(
        parent, title, text, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    ) == QMessageBox.Yes


# ---------------------------------------------------------------------------
# فیلد تاریخ شمسی
# ---------------------------------------------------------------------------
class DateEdit(QWidget):
    """فیلد ورود تاریخ شمسی (مثل ۱۴۰۵/۰۶/۲۳) با دکمهٔ «امروز»"""

    def __init__(self, parent=None, with_today_button=True):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("1405/06/23")
        self.edit.setMaxLength(10)
        self.edit.setAlignment(Qt.AlignCenter)
        self.edit.setMinimumWidth(110)
        lay.addWidget(self.edit)
        if with_today_button:
            btn = QPushButton("امروز")
            btn.setMaximumWidth(60)
            btn.clicked.connect(self.set_today)
            lay.addWidget(btn)
        self.set_today()

    def set_today(self):
        self.edit.setText(utils.today_j())

    def set_jalali(self, j: str):
        self.edit.setText(j or "")

    @property
    def jalali(self) -> str:
        return utils.normalize(self.edit.text())

    @property
    def gregorian(self) -> str:
        """تاریخ میلادیِ معادل (برای ذخیره در پایگاه داده)"""
        try:
            return jalali.from_jalali_str(self.jalali)
        except ValueError as e:
            raise ValueError(str(e))

    def is_valid(self) -> bool:
        try:
            jalali.from_jalali_str(self.jalali)
            return True
        except ValueError:
            return False


# ---------------------------------------------------------------------------
# فیلد مبلغ
# ---------------------------------------------------------------------------
class MoneyEdit(QLineEdit):
    """فیلد مبلغ با جداکنندهٔ هزارگان خودکار"""

    def __init__(self, parent=None, value: int = 0):
        super().__init__(parent)
        self.setAlignment(Qt.AlignLeft)
        self.setPlaceholderText("0")
        self.textChanged.connect(self._reformat)
        self.set_value(value)

    def _reformat(self):
        raw = utils.normalize(self.text()).replace(",", "")
        if not raw or raw in ("-",):
            return
        pos = self.cursorPosition()
        try:
            val = int(float(raw))
        except ValueError:
            return
        self.blockSignals(True)
        self.setText(utils.fmt(val))
        self.setCursorPosition(min(len(self.text()), pos + max(0, len(self.text()) - len(raw))))
        self.blockSignals(False)

    def set_value(self, value: int):
        self.blockSignals(True)
        self.setText(utils.fmt(int(value or 0)))
        self.blockSignals(False)

    @property
    def value(self) -> int:
        return utils.parse_money(self.text())


class NumberEdit(QLineEdit):
    """فیلد عدد اعشاری (مثل تعداد)"""

    def __init__(self, parent=None, value: float = 1):
        super().__init__(parent)
        self.setAlignment(Qt.AlignLeft)
        self.set_value(value)

    def set_value(self, value):
        v = float(value or 0)
        self.setText(f"{v:g}")

    @property
    def value(self) -> float:
        return utils.parse_float(self.text())


# ---------------------------------------------------------------------------
# جدول
# ---------------------------------------------------------------------------
def make_table(headers: list[str], stretch_last: bool = True) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectRows)
    t.setSelectionMode(QAbstractItemView.SingleSelection)
    t.setEditTriggers(QAbstractItemView.NoEditTriggers)
    t.setAlternatingRowColors(True)
    t.verticalHeader().setVisible(False)
    t.setSortingEnabled(False)
    hh = t.horizontalHeader()
    hh.setSectionResizeMode(QHeaderView.ResizeToContents)
    if stretch_last:
        hh.setSectionResizeMode(len(headers) - 1, QHeaderView.Stretch)
    return t


def add_row(table: QTableWidget, values: list, data=None, align_left_cols=()):
    r = table.rowCount()
    table.insertRow(r)
    for c, v in enumerate(values):
        text = "" if v is None else str(v)
        item = QTableWidgetItem(text)
        if c in align_left_cols:
            item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        else:
            item.setTextAlignment(Qt.AlignCenter)
        if data is not None and c == 0:
            item.setData(Qt.UserRole, data)
        table.setItem(r, c, item)
    return r


def selected_id(table: QTableWidget) -> int | None:
    row = table.currentRow()
    if row < 0:
        return None
    return table.item(row, 0).data(Qt.UserRole)


# ---------------------------------------------------------------------------
# خروجی
# ---------------------------------------------------------------------------
def export_csv(parent, table: QTableWidget, default_name: str = "report") -> None:
    if table.rowCount() == 0:
        msg_warn(parent, "چیزی برای خروجی گرفتن وجود ندارد")
        return
    path, _ = QFileDialog.getSaveFileName(
        parent, "ذخیره خروجی Excel/CSV",
        os.path.join(os.path.expanduser("~"), f"{default_name}.csv"),
        "CSV (*.csv)",
    )
    if not path:
        return
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    # BOM برای باز شدن صحیح در اکسل ویندوز
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(headers)
        for r in range(table.rowCount()):
            w.writerow([table.item(r, c).text() if table.item(r, c) else ""
                        for c in range(table.columnCount())])
    msg_info(parent, f"فایل ذخیره شد:\n{path}")


def print_html(parent, html: str, title: str = "گزارش", ask_pdf: bool = True) -> None:
    """چاپ یا خروجی PDF از یک سند HTML (با پشتیبانی از RTL)"""
    doc = QTextDocument()
    doc.setDefaultFont(QFont("Tahoma", 9))
    doc.setHtml(html)
    printer = QPrinter(QPrinter.HighResolution)
    if ask_pdf:
        path, _ = QFileDialog.getSaveFileName(
            parent, "ذخیره PDF",
            os.path.join(os.path.expanduser("~"), f"{title}.pdf"), "PDF (*.pdf)")
        if not path:
            return
        printer.setOutputFormat(QPrinter.PdfFormat)
        printer.setOutputFileName(path)
    else:
        from PySide6.QtPrintSupport import QPrintDialog
        QPrintDialog(printer, parent).exec()
    doc.print_(printer)
    if ask_pdf:
        msg_info(parent, f"PDF ذخیره شد:\n{path}")


# ---------------------------------------------------------------------------
# فرم سریع (برای دیالوگ‌های ساده)
# ---------------------------------------------------------------------------
class FormDialog(QDialog):
    def __init__(self, parent, title: str, fields: list[tuple], values: dict | None = None):
        """
        fields: لیستی از (name, label, type) که type یکی از 'text' | 'money' | 'number' | 'date' است
        """
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setLayoutDirection(Qt.RightToLeft)
        self.fields = {}
        values = values or {}
        form = QFormLayout()
        for name, label, kind in fields:
            if kind == "money":
                w = MoneyEdit(value=values.get(name, 0))
            elif kind == "number":
                w = NumberEdit(value=values.get(name, 0))
            elif kind == "date":
                w = DateEdit()
                w.set_jalali(values.get(name) or utils.today_j())
            else:
                w = QLineEdit(str(values.get(name, "") or ""))
            self.fields[name] = (w, kind)
            form.addRow(label, w)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)
        self.resize(420, 120 + 40 * len(fields))

    def get(self, name: str):
        w, kind = self.fields[name]
        if kind == "money":
            return w.value
        if kind == "number":
            return w.value
        return utils.normalize(w.text() if isinstance(w, QLineEdit) else w.jalali)


# ---------------------------------------------------------------------------
# کارت آماری (داشبورد)
# ---------------------------------------------------------------------------
class StatCard(QFrame):
    def __init__(self, title: str, value: str = "—", color: str = "#1f5f8b", hint: str = ""):
        super().__init__()
        self.setStyleSheet(
            f"QFrame{{background:#ffffff;border:1px solid #e2e6ec;border-radius:10px;}}"
            f"QLabel{{border:none;background:transparent;}}"
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumHeight(96)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        t = QLabel(title)
        t.setStyleSheet(f"color:{color};font-weight:bold;font-size:12px;")
        v = QLabel(value)
        v.setStyleSheet("color:#1b2430;font-size:19px;font-weight:bold;")
        self.value_label = v
        lay.addWidget(t)
        lay.addWidget(v)
        if hint:
            h = QLabel(hint)
            h.setStyleSheet("color:#5c6b7a;font-size:11px;")
            self.hint_label = h
            lay.addWidget(h)

    def set_value(self, value: str, hint: str = ""):
        self.value_label.setText(value)
        if hint and hasattr(self, "hint_label"):
            self.hint_label.setText(hint)


def persian_now() -> str:
    return f"{utils.to_persian_digits(jalali.today_jalali_str())} — {datetime.now():%H:%M}"


# ---------------------------------------------------------------------------
# اعمال سطح دسترسی روی دکمه‌ها
# ---------------------------------------------------------------------------
# نگاشتِ «متن دکمه» به «مجوز لازم». دکمه‌هایی که در این فهرست نیستند برای همه فعال‌اند
# (مثل جستجو، بروزرسانی و مشاهدهٔ گزارشات).
PERM_BUTTONS = {
    "➕ فاکتور جدید":      "invoice.create",
    "✅ قطعی کردن":         "invoice.confirm",
    "🚫 ابطال":             "invoice.cancel",
    "🖨 چاپ PDF":           "invoice.print",
    "➕ دریافت از مشتری":   "payment.create",
    "➖ پرداخت به تامین‌کننده": "payment.create",
    "🚫 ابطال رسید":        "payment.cancel",
    "➕ جدید":              "party.edit",
    "✏️ ویرایش":            "party.edit",
    "🚫 غیرفعال کردن":      "party.edit",
    "➕ کالای جدید":        "item.edit",
    "✏️ ویرایش کالا":       "item.edit",
    "🗑️ حذف":               "item.edit",
    "📦 اصلاح موجودی":      "item.edit",
    "👤 مدیریت کاربران":    "user.manage",
    "🔒 قفل/باز کردن دوره":  "period.lock",
    "♻️ بازیابی از فایل":   "backup.restore",
    "📄 خروجی Excel/CSV":   "report.export",
}


def apply_permissions(root) -> int:
    """
    غیرفعال کردن دکمه‌هایی که کاربرِ فعلی مجوزشان را ندارد.
    (کنترلِ اصلی در لایهٔ منطق هم انجام می‌شود؛ این فقط برای وضوحِ رابط کاربری است)
    """
    disabled = 0
    for btn in root.findChildren(QAbstractButton):
        perm = btn.property("perm") or PERM_BUTTONS.get(btn.text().strip())
        if perm and not auth.has(perm):
            btn.setEnabled(False)
            btn.setToolTip(f"شما مجوز این کار را ندارید ({perm})")
            disabled += 1
    return disabled
