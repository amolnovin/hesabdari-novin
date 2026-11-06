# -*- coding: utf-8 -*-
"""برگهٔ گزارشات"""

from html import escape

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

import jalali
import repo
import utils
from ui.widgets import (
    DateEdit,
    add_row,
    export_csv,
    make_table,
    msg_warn,
    print_html,
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
        ("journal", "دفتر روزنامه"),
        ("balance_sheet", "ترازنامه"),
        ("reconciliation", "کنترل سازگاری انبار و دفاتر"),
    ]

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._unit = repo.unit_label(con)
        self._build()

    def refresh(self):
        """برای سازگاری با MainWindow.open_tab (این برگه متد run دارد)."""
        self.run()

    def refresh_unit(self):
        """واحد پول نمایشی را از تنظیمات دوباره می‌خواند (پس از تغییر در تنظیمات)."""
        self._unit = repo.unit_label(self.con)
        self.run()

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
        self.to_date.set_jalali(jalali.to_jalali_str(jalali.end_of_jalali_year(jy)))
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
        self.from_date.setEnabled(kind in ("sales", "profit", "ledger", "journal"))
        self.to_date.setEnabled(kind in ("sales", "profit", "ledger", "journal"))
        if kind in ("aging_c", "aging_s"):
            self.from_date.setEnabled(False)
            self.to_date.setEnabled(False)
        getattr(self, "_" + kind)()

    # ------------------------------------------------------------------
    def _sales(self):
        d1, d2 = self._range()
        r = repo.report_sales(self.con, d1, d2)
        self._reset(["شماره", "تاریخ", "نوع", "مشتری", f"خالص ({self._unit})",
                     "بهای تمام‌شده", "سود ناخالص", "درصد سود", "مالیات", "جمع کل"])
        for x in r["detail"]:
            inv = x["inv"]
            margin = (100.0 * x["gross_profit"] / x["net"]) if x["net"] else 0
            add_row(self.table, [
                inv["no"], inv["jalali_date"],
                "فروش" if inv["kind"] == "sale" else "برگشت از فروش",
                inv["party_name"], repo.fmt_money(self.con, abs(x["net"])), repo.fmt_money(self.con, abs(x["cogs"])),
                repo.fmt_money(self.con, x["gross_profit"]), f"{margin:,.1f}٪",
                repo.fmt_money(self.con, inv["vat_amount"]), repo.fmt_money(self.con, inv["total"]),
            ], data=inv["id"])
        self.summary.setText(
            f"فروش ناخالص: {repo.fmt_money(self.con, r['gross_sales'])}  |  برگشت‌ها: {repo.fmt_money(self.con, r['returns'])}  |  "
            f"فروش خالص: {repo.fmt_money(self.con, r['net_sales'])}  |  بهای تمام‌شده: {repo.fmt_money(self.con, r['cogs'])}  |  "
            f"سود ناخالص: {repo.fmt_money(self.con, r['gross_profit'])} {self._unit} ({r['margin']:.1f}٪)")

    def _stock(self):
        r = repo.report_stock(self.con)
        self._reset(["کد", "نام کالا", "واحد", "موجودی", "میانگین بهای تمام‌شده",
                     f"ارزش موجودی ({self._unit})", "حداقل", "وضعیت"])
        for x in r["rows"]:
            add_row(self.table, [
                x["item"]["code"] or "", x["item"]["name"], x["item"]["unit"],
                utils.fmt_qty(x["qty"]), repo.fmt_money(self.con, x["avg_cost"]), repo.fmt_money(self.con, x["value"]),
                utils.fmt_qty(x["item"]["stock_min"]),
                "⚠️ زیر حد نصاب" if x["low"] else "عادی",
            ], data=x["item"]["id"])
        self.summary.setText(f"ارزش کل موجودی انبار: {repo.fmt_money(self.con, r['total_value'])} {self._unit}")

    def _customers(self):
        self._party_report("customer", "مشتریان")

    def _suppliers(self):
        self._party_report("supplier", "تامین‌کنندگان")

    def _party_report(self, kind: str, title: str):
        r = repo.report_customers(self.con, kind)
        self._reset(["کد", "نام", "تلفن", f"مانده ({self._unit})",
                     "تعداد فاکتور باز", "مبلغ فاکتورهای باز"])
        for x in r["rows"]:
            add_row(self.table, [
                x["party"]["code"] or "", x["party"]["name"], x["party"]["phone"] or "",
                repo.fmt_money(self.con, x["balance"]), x["open_invoices"], repo.fmt_money(self.con, x["open_amount"]),
            ], data=x["party"]["id"])
        self.summary.setText(f"مجموع ماندهٔ {title}: {repo.fmt_money(self.con, r['total'])} {self._unit}")

    def _aging(self, kind: str, title: str):
        r = repo.report_aging(self.con, kind)
        self._reset(["نام", "جاری (سررسید نرسیده)", "۱ تا ۳۰ روز", "۳۱ تا ۶۰ روز",
                     "۶۱ تا ۹۰ روز", "بیش از ۹۰ روز", f"جمع ({self._unit})", "تعداد فاکتور"])
        for x in r["rows"]:
            add_row(self.table, [
                x["party_name"], repo.fmt_money(self.con, x["current"]), repo.fmt_money(self.con, x["d1_30"]),
                repo.fmt_money(self.con, x["d31_60"]), repo.fmt_money(self.con, x["d61_90"]), repo.fmt_money(self.con, x["d90_plus"]),
                repo.fmt_money(self.con, x["total"]), x["invoices"],
            ], data=x["party_id"])
        b = r["buckets"]
        self.summary.setText(
            f"{title} — جاری: {repo.fmt_money(self.con, b['current'])}  |  ۱-۳۰ روز: {repo.fmt_money(self.con, b['d1_30'])}  |  "
            f"۳۱-۶۰: {repo.fmt_money(self.con, b['d31_60'])}  |  ۶۱-۹۰: {repo.fmt_money(self.con, b['d61_90'])}  |  "
            f"بیش از ۹۰: {repo.fmt_money(self.con, b['d90_plus'])}  |  جمع کل: {repo.fmt_money(self.con, r['total'])} {self._unit}")

    def _aging_c(self):
        self._aging("customer", "سنوات بدهی مشتریان")

    def _aging_s(self):
        self._aging("supplier", "سنوات بدهی تامین‌کنندگان")

    def _profit(self):
        d1, d2 = self._range()
        r = repo.report_profit_loss(self.con, d1, d2)
        self._reset(["عنوان", f"مبلغ ({self._unit})"])
        for label, val in [("درآمد خالص فروش", r["revenue"]),
                           ("بهای تمام‌شده کالای فروخته‌شده", -r["cogs"]),
                           ("سود ناخالص", r["gross_profit"]),
                           ("هزینه‌های عملیاتی", -r["expenses"]),
                           ("سود (زیان) خالص", r["net_profit"])]:
            add_row(self.table, [label, repo.fmt_money(self.con, val)])
        self.summary.setText(
            f"بازه: {self.from_date.jalali} تا {self.to_date.jalali}  |  "
            f"سود خالص: {repo.fmt_money(self.con, r['net_profit'])} {self._unit}")

    def _trial(self):
        r = repo.report_trial_balance(self.con)
        self._reset(["کد حساب", "نام حساب", "نوع", f"بدهکار ({self._unit})", f"بستانکار ({self._unit})", f"مانده ({self._unit})"])
        types = {"asset": "دارایی", "liability": "بدهی", "equity": "حقوق صاحبان سهام",
                 "revenue": "درآمد", "expense": "هزینه"}
        for row in r["rows"]:
            add_row(self.table, [row["code"], row["name"],
                                 types.get(row["type"], row["type"]),
                                 repo.fmt_money(self.con, row["debit"]), repo.fmt_money(self.con, row["credit"]),
                                 repo.fmt_money(self.con, row["balance"])])
        ok = "✅ تراز است" if r["balanced"] else "❌ نامتوازن!"
        self.summary.setText(
            f"جمع بدهکار: {repo.fmt_money(self.con, r['total_debit'])}  |  "
            f"جمع بستانکار: {repo.fmt_money(self.con, r['total_credit'])}  |  {ok}")

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
                r["party_name"] or "", repo.fmt_money(self.con, r["debit"]), repo.fmt_money(self.con, r["credit"]),
                repo.fmt_money(self.con, bal), r["entry_desc"] or "",
            ], data=r["no"])
        name = self.con.execute("SELECT name FROM accounts WHERE code=?", (code,)).fetchone()
        self.summary.setText(f"گردش حساب «{name['name'] if name else code}»  |  "
                             f"ماندهٔ پایانی: {repo.fmt_money(self.con, bal)} {self._unit}")

    def _journal(self):
        d1, d2 = self._range()
        rows = repo.report_journal(self.con, d1, d2)
        self._reset(["شماره سند", "تاریخ", "نوع", "مرجع", "ثبت‌کننده", "بدهکار", "بستانکار", "شرح"])
        for r in rows:
            add_row(self.table, [r["no"], r["jalali_date"], r["entry_type"], r["reference_no"] or "",
                                 r["posted_by"] or "", repo.fmt_money(self.con, r["debit"]), repo.fmt_money(self.con, r["credit"]),
                                 r["description"] or ""], data=r["id"])
        self.summary.setText(f"تعداد اسناد قطعی: {len(rows)}")

    def _balance_sheet(self):
        r = repo.report_balance_sheet(self.con, self._range()[1])
        self._reset(["کد", "حساب", "نوع", f"مانده ({self._unit})"])
        types = {"asset": "دارایی", "liability": "بدهی", "equity": "حقوق صاحبان سهام",
                 "revenue": "درآمد", "expense": "هزینه"}
        for row in r["rows"]:
            if row["bal"]:
                add_row(self.table, [row["code"], row["name"], types.get(row["type"], row["type"]), repo.fmt_money(self.con, row["bal"])])
        ok = "✅ دارایی = بدهی + حقوق صاحبان سهام" if r["balanced"] else "❌ ترازنامه متوازن نیست"
        self.summary.setText(f"دارایی: {repo.fmt_money(self.con, r['assets'])}  |  بدهی: {repo.fmt_money(self.con, r['liabilities'])}  |  "
                             f"حقوق صاحبان سهام: {repo.fmt_money(self.con, r['equity'])}  |  {ok}")

    def _reconciliation(self):
        r = repo.report_reconciliation(self.con)
        self._reset(["کنترل", "مقدار", "وضعیت"])
        add_row(self.table, ["ارزش انبار (کاردکس)", repo.fmt_money(self.con, r["stock_report"]), ""])
        add_row(self.table, ["مانده حساب موجودی کالا", repo.fmt_money(self.con, r["inventory_gl"]), ""])
        add_row(self.table, ["مغایرت", repo.fmt_money(self.con, r["stock_difference"]), "✅ صفر" if not r["stock_difference"] else "⚠️ بررسی شود"])
        add_row(self.table, ["تراز آزمایشی", "", "✅ متوازن" if r["trial"]["balanced"] else "❌ نامتوازن"])
        add_row(self.table, ["ترازنامه", "", "✅ متوازن" if r["balance_sheet"]["balanced"] else "❌ نامتوازن"])
        add_row(self.table, ["پرداخت‌های ناسازگار", str(len(r["invalid_payments"])), "✅" if not r["invalid_payments"] else "⚠️"])
        self.summary.setText("این گزارش برای پایش سلامت داده‌ها پس از مهاجرت و عملیات روزانه است.")

    # ------------------------------------------------------------------
    def export(self):
        export_csv(self, self.table, self.combo.currentData())

    def print_report(self):
        if self.table.rowCount() == 0:
            msg_warn(self, "گزارشی برای چاپ وجود ندارد")
            return
        cols = [self.table.horizontalHeaderItem(i).text()
                for i in range(self.table.columnCount())]
        head = "".join(f"<th style='padding:6px;border:1px solid #ccc'>{escape(c)}</th>" for c in cols)
        body = ""
        for r in range(self.table.rowCount()):
            tds = "".join(
                f"<td style='padding:5px;border:1px solid #ccc'>"
                f"{escape(self.table.item(r, c).text() if self.table.item(r, c) else '')}</td>"
                for c in range(self.table.columnCount()))
            body += f"<tr>{tds}</tr>"
        html = f"""<html><body dir="rtl" style="font-family:Tahoma;font-size:11px">
        <h3 style="text-align:center">{escape(self.combo.currentText())}</h3>
        <table width="100%" style="border-collapse:collapse" dir="rtl">
        <tr style="background:#eef3f7">{head}</tr>{body}</table>
        <p>{escape(self.summary.text())}</p></body></html>"""
        print_html(self, html, self.combo.currentData())
