# -*- coding: utf-8 -*-
"""برگهٔ مشتریان و تامین‌کنندگان"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

import repo
import utils
from ui.widgets import (
    DateEdit, FormDialog, MoneyEdit, add_row, export_csv, make_table,
    msg_error, msg_info, msg_warn, msg_ask, selected_id,
)


class CustomersTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self.kind = "customer"
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItem("همه", "all")
        self.kind_combo.addItem("مشتریان", "customer")
        self.kind_combo.addItem("تامین‌کنندگان", "supplier")
        self.kind_combo.currentIndexChanged.connect(self.refresh)
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجو بر اساس نام، کد یا تلفن…")
        self.search.textChanged.connect(self.refresh)
        bar.addWidget(QLabel("نمایش:"))
        bar.addWidget(self.kind_combo)
        bar.addWidget(self.search, 1)
        lay.addLayout(bar)

        btns = QHBoxLayout()
        for text, slot, style in [
            ("➕ جدید", self.new_party, "primary"),
            ("✏️ ویرایش", self.edit_party, ""),
            ("📒 دفتر حساب", self.show_ledger, ""),
            ("🚫 غیرفعال کردن", self.deactivate, ""),
            ("📄 خروجی", self.export, ""),
            ("🔄 بروزرسانی", self.refresh, ""),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            if style == "primary":
                b.setStyleSheet("QPushButton{background:#1f5f8b;color:#fff;padding:7px 14px;border-radius:6px;font-weight:bold}")
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.table = make_table(["شناسه", "کد", "نام", "نوع", "تلفن", "سقف اعتبار", "مانده (ریال)"])
        lay.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:6px")
        lay.addWidget(self.summary)

        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        kind = self.kind_combo.currentData() or "all"
        rows = repo.list_parties(self.con, None if kind == "all" else kind,
                                 utils.normalize(self.search.text()))
        self.table.setRowCount(0)
        total = 0
        for r in rows:
            kind_label = {"customer": "مشتری", "supplier": "تامین‌کننده", "both": "هر دو"}.get(r["kind"], r["kind"])
            add_row(self.table, [
                r["id"], r["code"] or "", r["name"], kind_label, r["phone"] or "",
                utils.fmt(r["credit_limit"]), utils.fmt(r["balance"]),
            ], data=r["id"])
            total += r["balance"]
        kind_label = self.kind_combo.currentText()
        self.summary.setText(f"تعداد: {len(rows)}  |  مجموع مانده ({kind_label}): {utils.fmt(total)} ریال")

    # ------------------------------------------------------------------
    def _dialog(self, party=None):
        d = FormDialog(
            self, "مشتری / تامین‌کننده",
            [("name", "نام *", "text"),
             ("code", "کد", "text"),
             ("phone", "تلفن", "text"),
             ("address", "آدرس", "text"),
             ("national_id", "شناسه ملی / کد ملی", "text"),
             ("economic_code", "کد اقتصادی", "text"),
             ("postal_code", "کد پستی", "text"),
             ("credit_limit", "سقف اعتبار (ریال)", "money")] +
            ([("opening_balance", "ماندهٔ اولیه (ریال)", "money")] if not party else []) +
            [("note", "توضیحات", "text")],
            party,
        )
        kind_combo = QComboBox()
        kind_combo.addItem("مشتری", "customer")
        kind_combo.addItem("تامین‌کننده", "supplier")
        kind_combo.addItem("هر دو", "both")
        if party:
            idx = kind_combo.findData(party["kind"])
            kind_combo.setCurrentIndex(max(0, idx))
        d.layout().itemAt(0).layout().insertRow(2, "نوع", kind_combo)
        d.resize(460, 480)
        return d, kind_combo

    def new_party(self):
        d, kind_combo = self._dialog()
        if d.exec():
            try:
                data = {k: d.get(k) for k in
                        ("name", "code", "phone", "address", "national_id",
                         "economic_code", "postal_code", "credit_limit", "note")}
                data["kind"] = kind_combo.currentData()
                if not data["name"]:
                    msg_warn(self, "وارد کردن نام الزامی است")
                    return
                data["opening_balance"] = d.get("opening_balance")
                repo.save_party(self.con, None, data)
                self.refresh()
                msg_info(self, "شخص جدید با موفقیت ثبت شد")
            except Exception as e:
                msg_error(self, str(e))

    def edit_party(self):
        pid = selected_id(self.table)
        if not pid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        party = repo.get_party(self.con, pid)
        d, kind_combo = self._dialog(dict(party))
        if d.exec():
            try:
                data = {k: d.get(k) for k in
                        ("name", "code", "phone", "address", "national_id",
                         "economic_code", "postal_code", "credit_limit", "note")}
                data["kind"] = kind_combo.currentData()
                repo.save_party(self.con, pid, data)
                self.refresh()
                msg_info(self, "تغییرات ذخیره شد")
            except Exception as e:
                msg_error(self, str(e))

    def deactivate(self):
        pid = selected_id(self.table)
        if not pid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        party = repo.get_party(self.con, pid)
        if not msg_ask(self, f"آیا «{party['name']}» غیرفعال شود؟"):
            return
        try:
            repo.delete_party(self.con, pid)
            self.refresh()
        except Exception as e:
            msg_error(self, str(e))

    def show_ledger(self):
        pid = selected_id(self.table)
        if not pid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        party = repo.get_party(self.con, pid)
        rows = repo.party_ledger(self.con, pid)
        d = QDialog(self)
        d.setWindowTitle(f"دفتر حساب — {party['name']}")
        d.setLayoutDirection(Qt.RightToLeft)
        d.resize(780, 460)
        lay = QVBoxLayout(d)
        t = make_table(["تاریخ", "شماره سند", "نوع", "مرجع", "حساب", "بدهکار", "بستانکار", "شرح"])
        bal = 0
        for r in rows:
            bal += r["debit"] - r["credit"]
            add_row(t, [r["jalali_date"], r["no"], r["entry_type"], r["reference_no"] or "",
                        r["account_name"], utils.fmt(r["debit"]), utils.fmt(r["credit"]),
                        (r["entry_desc"] or "")], data=r["entry_id"])
        lay.addWidget(t)
        lay.addWidget(QLabel(f"ماندهٔ نهایی: {utils.fmt(bal)} ریال"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.exec()

    def export(self):
        export_csv(self, self.table, "customers")
