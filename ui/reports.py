# -*- coding: utf-8 -*-
"""برگهٔ گزارشات"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget,
)

import jalali
import repo
import utils
from ui.widgets import (
    DateEdit, add_row, export_csv, make_table, msg_warn, print_html,
)


class ReportsTab(QWidget):
    REPORTS = [
        ("sales", "گزارش فروش و سود ناخالص"),
        ("stock", "موجودی و ارزش انبار"),
        ("customers", "بدهی مشتریان"),
        ("suppliers", "بدهی به تامین‌کنندگان"),
        ("aging_c", "سنوات بدهی مشتریان"),
        ("aging_s", "سنوات بدهی تامین‌کنندگان"),
        ("profit", "صورت سود و زیان"),
        ("trial", "تراز آزمایشی"),
        ("ledger", "دفتر حساب (گردش یک حساب)"),
    ]

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.combo = QComboBox()
        for key, label in self.REPORTS:
            self.combo.addItem(label, key)
        self.combo.currentIndexChanged.connect(self.run)
        self.from_date = DateEdit(with_today_button=False)
        self.to_date = DateEdit(with_today_button=False)
        jy = jalali.gregorian_to_jalali(*map(int, utils.today_g().split("-")))[0]
        self.from_date.set_jalali(f"{jy}/01/01")
        self.to_date.set_jalali(f"{jy}/12/29")
        self.account = QComboBox()
        for a in self.con.execute(
                "SELECT code, name FROM accounts WHERE is_postable=1 ORDER BY code"):
            self.account.addItem(f"{a['code']} — {a['name']}", a["code"])
        self.account.setVisible(False)
        bar.addWidget(QLabel("گزارش:"))
        bar.addWidget(self.combo)
        bar.addWidget(QLabel("از:"))
        bar.addWidget(self.from_date)
        bar.addWidget(QLabel("تا:"))
        bar.addWidget(self.to_date)
        bar.addWidget(self.account)
        bar.addStretch(1)
        b = QPushButton("🔄 اجرا")
        b.clicked.connect(self.run)
        bar.addWidget(b)
        lay.addLayout(bar)

        btns = QHBoxLayout()
        for text, slot in [("📄 خروجی Excel/CSV", self.export), ("🖨 چاپ PDF", self.print_report)]:
            b2 = QPushButton(text)
            b2.clicked.connect(slot)
            btns.addWidget(b2)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.table = make_table(["ستون ۱"])
        lay.addWidget(self.table, 1)
        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:8px;font-size:13px")
        lay.addWidget(self.summary)
        self.run()

    # ------------------------------------------------------------------
    def _range(self):
        try:
            d1 = jalali.from_jalali_str(self.from_date.jalali) if self.from_date.jalali else "0000-01-01"
        except ValueError:
            d1 = "0000-01-01"
        try:
            d2 = jalali.from_jalali_str(self.to_date.jalali) if self.to_date.jalali else "9999-12-31"
        except ValueError:
            d2 = "9999-12-31"
        return d1, d2

    def _reset(self, headers):
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(0)

    # ------------------------------------------------------------------
    def run(self):
        kind = self.combo.currentData()
        self.account.setVisible(kind == "ledger")
        self.from_date.setEnabled(kind in ("sales", "profit", "ledger"))
        self.to_date.setEnabled(kind in ("sales", "profit", "ledger"))
        if kind in ("aging_c", "aging_s"):
            self.from_date.setEnabled(False)
            self.to_date.setEnabled(False)
        getattr(self, "_" + kind)()

    # ------------------------------------------------------------------
    def _sales(self):
        d1, d2 = self._range()
        r = repo.report_sales(self.con, d1, d2)
        self._reset(["شماره", "تاریخ", "نوع", "مشتری", "خالص (ریال)",
                     "بهای تمام‌شده", "سود ناخالص", "درصد سود", "مالیات", "جمع کل"])
        for x in r["detail"]:
            inv = x["inv"]
            margin = (100.0 * x["gross_profit"] / x["net"]) if x["net"] else 0
            add_row(self.table, [
                inv["no"], inv["jalali_date"],
                "فروش" if inv["kind"] == "sale" else "برگشت از فروش",
                inv["party_name"], utils.fmt(abs(x["net"])), utils.fmt(abs(x["cogs"])),
                utils.fmt(x["gross_profit"]), f"{margin:,.1f}٪",
                utils.fmt(inv["vat_amount"]), utils.fmt(inv["total"]),
            ], data=inv["id"])
        self.summary.setText(
            f"فروش ناخالص: {utils.fmt(r['gross_sales'])}  |  برگشت‌ها: {utils.fmt(r['returns'])}  |  "
            f"فروش خالص: {utils.fmt(r['net_sales'])}  |  بهای تمام‌شده: {utils.fmt(r['cogs'])}  |  "
            f"سود ناخالص: {utils.fmt(r['gross_profit'])} ریال ({r['margin']:.1f}٪)")

    def _stock(self):
        r = repo.report_stock(self.con)
        self._reset(["کد", "نام کالا", "واحد", "موجودی", "میانگین بهای تمام‌شده",
                     "ارزش موجودی (ریال)", "حداقل", "وضعیت"])
        for x in r["rows"]:
            add_row(self.table, [
                x["item"]["code"] or "", x["item"]["name"], x["item"]["unit"],
                utils.fmt_qty(x["qty"]), utils.fmt(x["avg_cost"]), utils.fmt(x["value"]),
                utils.fmt_qty(x["item"]["stock_min"]),
                "⚠️ زیر حد نصاب" if x["low"] else "عادی",
            ], data=x["item"]["id"])
        self.summary.setText(f"ارزش کل موجودی انبار: {utils.fmt(r['total_value'])} ریال")

    def _customers(self):
        self._party_report("customer", "مشتریان")

    def _suppliers(self):
        self._party_report("supplier", "تامین‌کنندگان")

    def _party_report(self, kind: str, title: str):
        r = repo.report_customers(self.con, kind)
        self._reset(["کد", "نام", "تلفن", "مانده (ریال)",
                     "تعداد فاکتور باز", "مبلغ فاکتورهای باز"])
        for x in r["rows"]:
            add_row(self.table, [
                x["party"]["code"] or "", x["party"]["name"], x["party"]["phone"] or "",
                utils.fmt(x["balance"]), x["open_invoices"], utils.fmt(x["open_amount"]),
            ], data=x["party"]["id"])
        self.summary.setText(f"مجموع ماندهٔ {title}: {utils.fmt(r['total'])} ریال")

    def _aging(self, kind: str, title: str):
        r = repo.report_aging(self.con, kind)
        self._reset(["نام", "جاری (سررسید نرسیده)", "۱ تا ۳۰ روز", "۳۱ تا ۶۰ روز",
                     "۶۱ تا ۹۰ روز", "بیش از ۹۰ روز", "جمع (ریال)", "تعداد فاکتور"])
        for x in r["rows"]:
            add_row(self.table, [
                x["party_name"], utils.fmt(x["current"]), utils.fmt(x["d1_30"]),
                utils.fmt(x["d31_60"]), utils.fmt(x["d61_90"]), utils.fmt(x["d90_plus"]),
                utils.fmt(x["total"]), x["invoices"],
            ], data=x["party_id"])
        b = r["buckets"]
        self.summary.setText(
            f"{title} — جاری: {utils.fmt(b['current'])}  |  ۱-۳۰ روز: {utils.fmt(b['d1_30'])}  |  "
            f"۳۱-۶۰: {utils.fmt(b['d31_60'])}  |  ۶۱-۹۰: {utils.fmt(b['d61_90'])}  |  "
            f"بیش از ۹۰: {utils.fmt(b['d90_plus'])}  |  جمع کل: {utils.fmt(r['total'])} ریال")

    def _aging_c(self):
        self._aging("customer", "سنوات بدهی مشتریان")

    def _aging_s(self):
        self._aging("supplier", "سنوات بدهی تامین‌کنندگان")

    def _profit(self):
        d1, d2 = self._range()
        r = repo.report_profit_loss(self.con, d1, d2)
        self._reset(["عنوان", "مبلغ (ریال)"])
        for label, val in [("درآمد خالص فروش", r["revenue"]),
                           ("بهای تمام‌شده کالای فروخته‌شده", -r["cogs"]),
                           ("سود ناخالص", r["gross_profit"]),
                           ("هزینه‌های عملیاتی", -r["expenses"]),
                           ("سود (زیان) خالص", r["net_profit"])]:
            add_row(self.table, [label, utils.fmt(val)])
        self.summary.setText(
            f"بازه: {self.from_date.jalali} تا {self.to_date.jalali}  |  "
            f"سود خالص: {utils.fmt(r['net_profit'])} ریال")

    def _trial(self):
        r = repo.report_trial_balance(self.con)
        self._reset(["کد حساب", "نام حساب", "نوع", "بدهکار (ریال)", "بستانکار (ریال)", "مانده (ریال)"])
        types = {"asset": "دارایی", "liability": "بدهی", "equity": "حقوق صاحبان سهام",
                 "revenue": "درآمد", "expense": "هزینه"}
        for row in r["rows"]:
            add_row(self.table, [row["code"], row["name"],
                                 types.get(row["type"], row["type"]),
                                 utils.fmt(row["debit"]), utils.fmt(row["credit"]),
                                 utils.fmt(row["balance"])])
        ok = "✅ تراز است" if r["balanced"] else "❌ نامتوازن!"
        self.summary.setText(
            f"جمع بدهکار: {utils.fmt(r['total_debit'])}  |  "
            f"جمع بستانکار: {utils.fmt(r['total_credit'])}  |  {ok}")

    def _ledger(self):
        code = self.account.currentData() or "10101"
        d1, d2 = self._range()
        rows = repo.report_ledger(self.con, code, d1, d2)
        self._reset(["تاریخ", "شماره سند", "نوع سند", "مرجع", "طرف حساب",
                     "بدهکار", "بستانکار", "مانده", "شرح"])
        bal = 0
        for r in rows:
            bal += r["debit"] - r["credit"]
            add_row(self.table, [
                r["jalali_date"], r["no"], r["entry_type"], r["reference_no"] or "",
                r["party_name"] or "", utils.fmt(r["debit"]), utils.fmt(r["credit"]),
                utils.fmt(bal), r["entry_desc"] or "",
            ], data=r["no"])
        name = self.con.execute("SELECT name FROM accounts WHERE code=?", (code,)).fetchone()
        self.summary.setText(f"گردش حساب «{name['name'] if name else code}»  |  "
                             f"ماندهٔ پایانی: {utils.fmt(bal)} ریال")

    # ------------------------------------------------------------------
    def export(self):
        export_csv(self, self.table, self.combo.currentData())

    def print_report(self):
        if self.table.rowCount() == 0:
            msg_warn(self, "گزارشی برای چاپ وجود ندارد")
            return
        cols = [self.table.horizontalHeaderItem(i).text()
                for i in range(self.table.columnCount())]
        head = "".join(f"<th style='padding:6px;border:1px solid #ccc'>{c}</th>" for c in cols)
        body = ""
        for r in range(self.table.rowCount()):
            tds = "".join(
                f"<td style='padding:5px;border:1px solid #ccc'>"
                f"{self.table.item(r, c).text() if self.table.item(r, c) else ''}</td>"
                for c in range(self.table.columnCount()))
            body += f"<tr>{tds}</tr>"
        html = f"""<html><body dir="rtl" style="font-family:Tahoma;font-size:11px">
        <h3 style="text-align:center">{self.combo.currentText()}</h3>
        <table width="100%" style="border-collapse:collapse" dir="rtl">
        <tr style="background:#eef3f7">{head}</tr>{body}</table>
        <p>{self.summary.text()}</p></body></html>"""
        print_html(self, html, self.combo.currentData())
