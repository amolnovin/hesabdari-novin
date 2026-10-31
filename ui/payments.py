# -*- coding: utf-8 -*-
"""برگهٔ دریافت و پرداخت"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout, QWidget,
)

from html import escape

import jalali
import repo
import utils
from ui.widgets import (
    DateEdit, FormDialog, MoneyEdit, add_row, export_csv, make_table,
    msg_error, msg_info, msg_warn, msg_ask, selected_id,
)

METHOD_LABEL = {"cash": "نقد (صندوق)", "bank": "بانک", "pos": "کارتخوان", "transfer": "انتقال"}


class PaymentsTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        btns = QHBoxLayout()
        for text, slot, primary in [
            ("➕ دریافت از مشتری", self.new_receipt, True),
            ("➖ پرداخت به تامین‌کننده", self.new_payment, False),
            ("👁 مشاهده / چاپ", self.view_payment, False),
            ("🚫 ابطال رسید", self.cancel_payment, False),
            ("📄 خروجی", self.export, False),
            ("🔄 بروزرسانی", self.refresh, False),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            if primary:
                b.setStyleSheet("QPushButton{background:#17795e;color:#fff;padding:7px 14px;border-radius:6px;font-weight:bold}")
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.table = make_table(
            ["شناسه", "شماره", "تاریخ", "نوع", "طرف حساب", "روش", "مبلغ (ریال)",
             "فاکتور مرتبط", "شرح", "وضعیت"])
        lay.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:6px")
        lay.addWidget(self.summary)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        rows = repo.list_payments(self.con)
        self.table.setRowCount(0)
        rec = pay = 0
        for r in rows:
            is_receipt = r["direction"] == "receipt"
            if r["is_cancelled"]:
                status = "ابطال‌شده"
            else:
                status = "ثبت‌شده"
                rec += r["amount"] if is_receipt else 0
                pay += 0 if is_receipt else r["amount"]
            add_row(self.table, [
                r["id"], r["no"], r["jalali_date"],
                "دریافت" if is_receipt else "پرداخت",
                r["party_name"], METHOD_LABEL.get(r["method"], r["method"]),
                utils.fmt(r["amount"]),
                f"#{r['invoice_id']}" if r["invoice_id"] else "",
                r["description"] or "", status,
            ], data=r["id"])
        self.summary.setText(
            f"تعداد: {len(rows)}  |  مجموع دریافت‌ها: {utils.fmt(rec)} ریال  |  "
            f"مجموع پرداخت‌ها: {utils.fmt(pay)} ریال  |  خالص نقد: {utils.fmt(rec - pay)} ریال")

    # ------------------------------------------------------------------
    def _dialog(self, direction: str, title: str) -> FormDialog:
        d = FormDialog(self, title, [
            ("amount", "مبلغ (ریال) *", "money"),
            ("date", "تاریخ", "date"),
            ("description", "شرح", "text"),
        ])
        party = QComboBox()
        kind = "customer" if direction == "receipt" else "supplier"
        for p in repo.list_parties(self.con, kind):
            party.addItem(p["name"], p["id"])
        method = QComboBox()
        for k, v in METHOD_LABEL.items():
            method.addItem(v, k)
        form = d.layout().itemAt(0).layout()
        form.insertRow(1, "طرف حساب *", party)
        form.insertRow(2, "روش پرداخت", method)

        invoice = QComboBox()
        form.insertRow(3, "تسویه فاکتور", invoice)
        d.resize(460, 340)
        d.party_combo = party
        d.method_combo = method
        d.invoice_combo = invoice
        inv_kind = "sale" if direction == "receipt" else "purchase"
        def reload_invoices():
            invoice.clear()
            invoice.addItem("— بدون ارجاع به فاکتور —", None)
            pid = party.currentData()
            if not pid:
                return
            for inv in repo.list_invoices(self.con, inv_kind, party_id=pid, status="confirmed"):
                rem = inv["total"] - inv["paid_amount"]
                if rem > 0:
                    invoice.addItem(f"فاکتور #{inv['no']} — مانده {utils.fmt(rem)} ریال", inv["id"])
        party.currentIndexChanged.connect(reload_invoices)
        reload_invoices()
        return d

    def new_receipt(self):
        d = self._dialog("receipt", "دریافت وجه از مشتری")
        if d.exec():
            try:
                if not d.party_combo.currentData():
                    msg_warn(self, "انتخاب مشتری الزامی است")
                    return
                if d.get("amount") <= 0:
                    msg_warn(self, "مبلغ باید بزرگ‌تر از صفر باشد")
                    return
                repo.add_payment(self.con, "receipt", d.party_combo.currentData(),
                                 d.get("amount"), jalali.from_jalali_str(d.get("date")),
                                 d.method_combo.currentData(), d.invoice_combo.currentData(),
                                 d.get("description"))
                self.refresh()
                msg_info(self, "رسید دریافت ثبت شد و سند آن صادر گردید")
            except Exception as e:
                msg_error(self, str(e))

    def new_payment(self):
        d = self._dialog("payment", "پرداخت وجه به تامین‌کننده")
        if d.exec():
            try:
                if not d.party_combo.currentData():
                    msg_warn(self, "انتخاب تامین‌کننده الزامی است")
                    return
                if d.get("amount") <= 0:
                    msg_warn(self, "مبلغ باید بزرگ‌تر از صفر باشد")
                    return
                repo.add_payment(self.con, "payment", d.party_combo.currentData(),
                                 d.get("amount"), jalali.from_jalali_str(d.get("date")),
                                 d.method_combo.currentData(), d.invoice_combo.currentData(),
                                 d.get("description"))
                self.refresh()
                msg_info(self, "رسید پرداخت ثبت شد و سند آن صادر گردید")
            except Exception as e:
                msg_error(self, str(e))

    def view_payment(self):
        pid = selected_id(self.table)
        if not pid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        p = self.con.execute(
            """SELECT p.*, pt.name AS party_name FROM payments p
               JOIN parties pt ON pt.id = p.party_id WHERE p.id = ?""", (pid,)).fetchone()
        company = {r["key"]: r["value"] for r in self.con.execute("SELECT key, value FROM settings")}
        html = f"""
        <html><body dir="rtl" style="font-family:Tahoma;font-size:13px">
        <h2 style="text-align:center;margin:2px">{escape(company.get('company_name',''))}</h2>
        <h3 style="text-align:center;margin:4px">{'رسید دریافت' if p['direction']=='receipt' else 'رسید پرداخت'} شماره {p['no']}</h3>
        <hr>
        <p>تاریخ: {p['jalali_date']}</p>
        <p>{'دریافت از:' if p['direction']=='receipt' else 'پرداخت به:'} <b>{escape(p['party_name'])}</b></p>
        <p>مبلغ: <b>{utils.fmt(p['amount'])} ریال</b></p>
        <p>روش: {METHOD_LABEL.get(p['method'], p['method'])}</p>
        <p>شرح: {escape(p['description'] or '-')}</p>
        {'<p style="color:#b3261e"><b>این رسید ابطال شده است</b></p>' if p['is_cancelled'] else ''}
        <br><br>
        <table width="100%"><tr>
        <td style="text-align:center">امضا و مهر</td>
        <td style="text-align:center">امضای تحویل‌گیرنده</td>
        </tr></table>
        </body></html>"""
        from ui.widgets import print_html
        print_html(self, html, f"رسید-{p['no']}")

    def cancel_payment(self):
        pid = selected_id(self.table)
        if not pid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        if not msg_ask(self, "آیا این مورد ابطال شود؟ (سند معکوس صادر می‌گردد)"):
            return
        try:
            repo.cancel_payment(self.con, pid, "ابطال توسط کاربر")
            self.refresh()
            msg_info(self, "با ثبت سند معکوس ابطال شد")
        except Exception as e:
            msg_error(self, str(e))

    def export(self):
        export_csv(self, self.table, "payments")
