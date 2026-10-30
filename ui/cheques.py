# -*- coding: utf-8 -*-
"""برگهٔ مدیریت چک‌های دریافتنی و پرداختنی"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QVBoxLayout, QWidget,
)

import jalali
import repo
import utils
from ui.widgets import (
    DateEdit, FormDialog, MoneyEdit, add_row, export_csv, make_table,
    msg_error, msg_info, msg_warn, msg_ask, selected_id,
)

STATUS_LABEL = repo.CHEQUE_STATUS


class ChequesTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItem("همه", "")
        self.type_combo.addItem("چک‌های دریافتنی", "received")
        self.type_combo.addItem("چک‌های پرداختنی", "paid")
        self.type_combo.currentIndexChanged.connect(self.refresh)
        self.status_combo = QComboBox()
        self.status_combo.addItem("همه", "")
        for k, v in STATUS_LABEL.items():
            self.status_combo.addItem(v, k)
        self.status_combo.currentIndexChanged.connect(self.refresh)
        bar.addWidget(QLabel("نوع:"))
        bar.addWidget(self.type_combo)
        bar.addWidget(QLabel("وضعیت:"))
        bar.addWidget(self.status_combo)
        bar.addStretch(1)
        lay.addLayout(bar)

        btns = QHBoxLayout()
        for text, slot, perm, primary in [
            ("➕ چک جدید", self.new_cheque, "cheque.create", True),
            ("✅ وصول / پرداخت", self.clear_cheque, "cheque.update", False),
            ("⚠️ برگشت خوردن", self.bounce_cheque, "cheque.update", False),
            ("🚫 ابطال چک", self.cancel_cheque, "cheque.update", False),
            ("📄 خروجی", self.export, "report.export", False),
            ("🔄 بروزرسانی", self.refresh, "", False),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            if perm:
                b.setProperty("perm", perm)
            if primary:
                b.setStyleSheet("QPushButton{background:#1f5f8b;color:#fff;padding:7px 14px;border-radius:6px;font-weight:bold}")
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.table = make_table(
            ["شناسه", "نوع", "سریال", "بانک", "طرف حساب", "مبلغ (ریال)",
             "تاریخ صدور", "تاریخ سررسید", "روز باقی‌مانده", "وضعیت", "شرح"])
        lay.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:6px")
        lay.addWidget(self.summary)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        rows = repo.list_cheques(self.con, self.type_combo.currentData(),
                                 self.status_combo.currentData())
        self.table.setRowCount(0)
        from datetime import date
        today = date.today()
        overdue = due_soon = 0
        rec_pending = paid_pending = 0
        for r in rows:
            days = (date.fromisoformat(r["due_date"]) - today).days
            if r["status"] == "pending":
                if r["cheque_type"] == "received":
                    rec_pending += r["amount"]
                else:
                    paid_pending += r["amount"]
                if days < 0:
                    overdue += 1
                elif days <= 7:
                    due_soon += 1
            days_text = f"{days} روز گذشته" if days < 0 else (f"{days} روز" if days else "امروز")
            add_row(self.table, [
                r["id"], "دریافتنی" if r["cheque_type"] == "received" else "پرداختنی",
                r["serial_no"], r["bank_name"] or "", r["party_name"],
                utils.fmt(r["amount"]), r["jalali_issue"], r["jalali_due"],
                days_text, STATUS_LABEL.get(r["status"], r["status"]),
                r["description"] or "",
            ], data=r["id"])
            if r["status"] == "pending" and days < 0:
                for c in range(self.table.columnCount()):
                    it = self.table.item(self.table.rowCount() - 1, c)
                    if it:
                        it.setBackground(Qt.lightGray)
        self.summary.setText(
            f"تعداد: {len(rows)}  |  در جریان وصول (دریافتنی): {utils.fmt(rec_pending)} ریال  |  "
            f"در جریان (پرداختنی): {utils.fmt(paid_pending)} ریال  |  "
            f"سررسید گذشته: {overdue}  |  هفتهٔ جاری: {due_soon}")

    # ------------------------------------------------------------------
    def _dialog(self, cheque=None):
        d = FormDialog(
            self, "چک جدید" if not cheque else "مشاهده چک",
            [("serial_no", "شماره سریال چک *", "text"),
             ("bank_name", "بانک", "text"),
             ("branch", "شعبه", "text"),
             ("amount", "مبلغ (ریال) *", "money"),
             ("issue_date", "تاریخ صدور", "date"),
             ("due_date", "تاریخ سررسید", "date"),
             ("sayad_id", "شناسه صیاد", "text"),
             ("description", "شرح", "text")])
        ctype = QComboBox()
        ctype.addItem("چک دریافتنی (از مشتری)", "received")
        ctype.addItem("چک پرداختنی (به تامین‌کننده)", "paid")
        party = QComboBox()
        form = d.layout().itemAt(0).layout()
        form.insertRow(0, "نوع چک *", ctype)
        form.insertRow(1, "طرف حساب *", party)

        def fill_parties():
            party.clear()
            kind = "customer" if ctype.currentData() == "received" else "supplier"
            for p in repo.list_parties(self.con, kind):
                party.addItem(p["name"], p["id"])

        ctype.currentIndexChanged.connect(fill_parties)
        fill_parties()
        d.resize(470, 400)
        d.ctype = ctype
        d.party_combo = party
        return d

    def new_cheque(self):
        d = self._dialog()
        if d.exec():
            try:
                if not d.party_combo.currentData():
                    msg_warn(self, "ابتدا طرف حساب (مشتری یا تامین‌کننده) را تعریف کنید")
                    return
                if d.get("amount") <= 0:
                    msg_warn(self, "مبلغ چک باید بزرگ‌تر از صفر باشد")
                    return
                repo.add_cheque(self.con, d.ctype.currentData(), d.party_combo.currentData(),
                                d.get("serial_no"), d.get("amount"),
                                jalali.from_jalali_str(d.get("issue_date")),
                                jalali.from_jalali_str(d.get("due_date")),
                                d.get("bank_name"), d.get("branch"),
                                d.get("sayad_id"), d.get("description"))
                self.refresh()
                msg_info(self, "چک ثبت شد و سند حسابداری آن صادر گردید")
            except Exception as e:
                msg_error(self, str(e))

    def _selected(self):
        cid = selected_id(self.table)
        if not cid:
            msg_warn(self, "ابتدا یک چک را انتخاب کنید")
            return None
        return cid

    def clear_cheque(self):
        cid = self._selected()
        if not cid:
            return
        method, ok = QInputDialog.getItem(self, "نحوهٔ وصول/پرداخت", "روش:",
                                          ["بانک", "صندوق"], 0, False)
        if not ok:
            return
        try:
            repo.clear_cheque(self.con, cid, "bank" if method == "بانک" else "cash")
            self.refresh()
            msg_info(self, "وضعیت چک به «وصول/پرداخت شده» تغییر یافت")
        except Exception as e:
            msg_error(self, str(e))

    def bounce_cheque(self):
        cid = self._selected()
        if not cid:
            return
        if not msg_ask(self, "آیا این چک برگشت خورده است؟ (سند اصلاحی ثبت می‌شود)"):
            return
        try:
            repo.bounce_cheque(self.con, cid)
            self.refresh()
            msg_info(self, "برگشت چک ثبت شد")
        except Exception as e:
            msg_error(self, str(e))

    def cancel_cheque(self):
        cid = self._selected()
        if not cid:
            return
        reason, ok = QInputDialog.getText(self, "ابطال چک", "دلیل ابطال:")
        if not ok:
            return
        try:
            repo.cancel_cheque(self.con, cid, reason)
            self.refresh()
            msg_info(self, "چک با ثبت سند معکوس ابطال شد")
        except Exception as e:
            msg_error(self, str(e))

    def export(self):
        export_csv(self, self.table, "cheques")
