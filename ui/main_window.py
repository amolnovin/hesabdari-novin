# -*- coding: utf-8 -*-
"""پنجرهٔ اصلی برنامه — صفحهٔ داشبورد و نگهدارندهٔ برگه‌ها"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGridLayout, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QPushButton,
    QTabWidget, QVBoxLayout, QWidget,
)

import auth
import db
import repo
import utils
from ui.cheques import ChequesTab
from ui.customers import CustomersTab
from ui.invoices import InvoicesTab
from ui.payments import PaymentsTab
from ui.products import ProductsTab
from ui.reports import ReportsTab
from ui.settings import SettingsTab
from ui.widgets import (StatCard, add_row, apply_permissions, make_table,
                        msg_info, persian_now)


class MainWindow(QMainWindow):
    def __init__(self, con):
        super().__init__()
        self.con = con
        self.setWindowTitle("حسابداری کسب‌وکار کوچک")
        self.resize(1180, 740)
        self.setLayoutDirection(Qt.RightToLeft)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.setCentralWidget(self.tabs)

        self.dashboard = DashboardTab(con, self.open_tab)
        self.tabs.addTab(self.dashboard, "🏠 داشبورد")

        self.tab_customers = CustomersTab(con, self)
        self.tab_products = ProductsTab(con, self)
        self.tab_invoices = InvoicesTab(con, self)
        self.tab_payments = PaymentsTab(con, self)
        self.tab_cheques = ChequesTab(con, self)
        self.tab_reports = ReportsTab(con, self)
        self.tab_settings = SettingsTab(con, self)

        self.tabs.addTab(self.tab_customers, "👥 مشتریان و تامین‌کنندگان")
        self.tabs.addTab(self.tab_products, "📦 کالاها و انبار")
        self.tabs.addTab(self.tab_invoices, "🧾 فاکتورها")
        self.tabs.addTab(self.tab_payments, "💵 دریافت و پرداخت")
        self.tabs.addTab(self.tab_cheques, "🏷️ چک‌ها")
        self.tabs.addTab(self.tab_reports, "📊 گزارشات")
        self.tabs.addTab(self.tab_settings, "⚙️ تنظیمات")

        # غیرفعال کردن دکمه‌هایی که کاربر مجوزشان را ندارد
        blocked = 0
        for i in range(self.tabs.count()):
            blocked += apply_permissions(self.tabs.widget(i))
        u = auth.current()
        if u:
            self.setWindowTitle(
                f"حسابداری کسب‌وکار کوچک — {u['full_name'] or u['username']} "
                f"({auth.role_label(u['role'])})")

        self.tabs.currentChanged.connect(self._on_tab_changed)

    def open_tab(self, index: int):
        self.tabs.setCurrentIndex(index)

    def closeEvent(self, event):
        if QMessageBox.question(self, "خروج", "آیا از برنامه خارج می‌شوید؟",
                                QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes:
            path = db.auto_backup(self.con, "exit")   # پشتیبان خودکار هنگام خروج
            event.accept()
            _ = path
        else:
            event.ignore()

    def _on_tab_changed(self, i):
        w = self.tabs.widget(i)
        if hasattr(w, "refresh") and w is not self.dashboard:
            try:
                w.refresh()
            except Exception:
                pass
        if w is self.dashboard:
            self.dashboard.refresh()


class DashboardTab(QWidget):
    """صفحهٔ اصلی: اعداد کلیدی کسب‌وکار در یک نگاه"""

    def __init__(self, con, open_tab=None):
        super().__init__()
        self.con = con
        self.open_tab = open_tab
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        title = QLabel("خلاصهٔ وضعیت کسب‌وکار")
        title.setStyleSheet("font-size:17px;font-weight:bold;color:#123c5a;padding:6px")
        lay.addWidget(title)

        self.hint = QLabel("")
        self.hint.setStyleSheet("color:#5c6b7a;font-size:12px;padding-bottom:6px")
        lay.addWidget(self.hint)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.cards = {}
        specs = [
            ("sales", "فروش خالص سال جاری", "#1f5f8b"),
            ("profit", "سود ناخالص", "#17795e"),
            ("stock", "ارزش موجودی انبار", "#b5651d"),
            ("receivable", "طلب از مشتریان", "#2c7fb8"),
            ("payable", "بدهی به تامین‌کنندگان", "#b3261e"),
            ("cash", "موجودی نقد و بانک", "#123c5a"),
            ("cheques", "چک‌های در جریان", "#8a5cb8"),
        ]
        for i, (key, label, color) in enumerate(specs):
            c = StatCard(label, "—", color)
            self.cards[key] = c
            grid.addWidget(c, i // 3, i % 3)
        lay.addLayout(grid)

        lay.addWidget(QLabel("<b>آخرین فاکتورها</b>"))
        self.table = make_table(["شماره", "تاریخ", "نوع", "طرف حساب", "جمع (ریال)", "وضعیت"])
        self.table.setMaximumHeight(210)
        lay.addWidget(self.table)

        quick = QHBoxLayout()
        for text, idx in [("🧾 صدور فاکتور فروش", 3), ("📦 ثبت خرید ورود به انبار", 3),
                          ("💵 ثبت دریافت وجه", 4), ("🏷️ مدیریت چک‌ها", 5),
                          ("📊 مشاهدهٔ گزارشات", 6)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, i=idx: self.open_tab(i) if self.open_tab else None)
            quick.addWidget(b)
        quick.addStretch(1)
        lay.addLayout(quick)

        self.balance_note = QLabel("")
        self.balance_note.setStyleSheet("padding:8px;font-weight:bold")
        lay.addWidget(self.balance_note)
        self.refresh()

    def refresh(self):
        d = repo.dashboard(self.con)
        self.hint.setText(f"سال مالی {d['jalali_year']}  •  بروزرسانی: {persian_now()}")
        self.cards["sales"].set_value(utils.fmt(d["sales"]["net_sales"]) + " ریال",
                                      f"{len(d['sales']['detail'])} فاکتور")
        self.cards["profit"].set_value(utils.fmt(d["sales"]["gross_profit"]) + " ریال",
                                       f"حاشیه سود {d['sales']['margin']:.1f}٪")
        self.cards["stock"].set_value(utils.fmt(d["stock"]["total_value"]) + " ریال",
                                      f"{len(d['stock']['rows'])} قلم کالا")
        self.cards["receivable"].set_value(utils.fmt(d["customers"]["total"]) + " ریال")
        self.cards["payable"].set_value(utils.fmt(d["suppliers"]["total"]) + " ریال")
        self.cards["cash"].set_value(utils.fmt(d["cash"]) + " ریال")
        chq = d["cheques"]
        self.cards["cheques"].set_value(
            utils.fmt(chq["received_pending"]) + " ریال",
            f"دریافتنیِ در جریان: {chq['received_count']} • پرداختنی: {chq['paid_count']}"
            + (f" • ⚠️ {chq['overdue']} سررسید گذشته" if chq["overdue"] else ""))

        self.table.setRowCount(0)
        for inv in repo.list_invoices(self.con, "sale")[:8]:
            status = {"draft": "پیش‌نویس", "confirmed": "قطعی", "cancelled": "ابطال‌شده"}[inv["status"]]
            add_row(self.table, [inv["no"], inv["jalali_date"], "فروش", inv["party_name"],
                                 utils.fmt(inv["total"]), status], data=inv["id"])

        t = d["trial"]
        if t["balanced"]:
            self.balance_note.setStyleSheet("color:#17795e;padding:8px;font-weight:bold")
            self.balance_note.setText(
                f"✅ دفاتر تراز است — جمع بدهکار و بستانکار: {utils.fmt(t['total_debit'])} ریال")
        else:
            self.balance_note.setStyleSheet("color:#b3261e;padding:8px;font-weight:bold")
            self.balance_note.setText("❌ تراز آزمایشی نامتوازن است؛ دفاتر را بررسی کنید")
