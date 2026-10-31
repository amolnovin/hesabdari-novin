# -*- coding: utf-8 -*-
"""پنجرهٔ اصلی با ناوبری کناری، داشبورد و برگه‌ها."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QMainWindow,
    QMessageBox, QPushButton, QScrollArea, QStackedWidget, QStatusBar, QTabWidget,
    QVBoxLayout, QWidget,
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
from ui.theme import apply_theme, color, icon, load_font
from ui.widgets import StatCard, apply_permissions, msg_info, persian_now


class MainWindow(QMainWindow):
    PAGES = [
        ("dashboard", "داشبورد", "خلاصهٔ وضعیت کسب‌وکار"),
        ("users", "اشخاص", "مشتریان و تامین‌کنندگان"),
        ("box", "کالا و انبار", "کالاها، خدمات و موجودی"),
        ("invoice", "فاکتورها", "خرید، فروش و برگشت‌ها"),
        ("cash", "دریافت و پرداخت", "تسویه و گردش نقدینگی"),
        ("cheque", "چک‌ها", "دریافتنی، پرداختنی و سررسید"),
        ("chart", "گزارش‌ها", "دفاتر، تراز و صورت‌های مالی"),
        ("settings", "تنظیمات", "شرکت، کاربران، پشتیبان و دوره‌ها"),
    ]

    def __init__(self, con):
        super().__init__()
        self.con = con
        app = QApplication.instance()
        if app and not app.styleSheet():
            load_font(app)
            apply_theme(app, "light")
            app.setProperty("theme_mode", "light")
        self.setWindowTitle("حسابداری نوین — کسب‌وکار کوچک")
        self.resize(1320, 820)
        self.setLayoutDirection(Qt.RightToLeft)

        root = QWidget()
        root_lay = QHBoxLayout(root)
        root_lay.setContentsMargins(0, 0, 0, 0)
        root_lay.setSpacing(0)
        self.setCentralWidget(root)

        sidebar = QFrame(); sidebar.setObjectName("Sidebar"); sidebar.setFixedWidth(230)
        side = QVBoxLayout(sidebar); side.setContentsMargins(12, 8, 12, 12); side.setSpacing(4)
        brand = QLabel("حسابداری نوین"); brand.setObjectName("Brand")
        sub = QLabel("نسخهٔ کاربردی کسب‌وکار کوچک"); sub.setObjectName("BrandSub")
        side.addWidget(brand); side.addWidget(sub)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for i, (ic, title, hint) in enumerate(self.PAGES):
            btn = QPushButton(title)
            btn.setObjectName("NavButton")
            btn.setCheckable(True)
            btn.setIcon(icon(ic))
            btn.setToolTip(hint)
            btn.clicked.connect(lambda checked=False, idx=i: self.open_tab(idx))
            self.nav_group.addButton(btn, i)
            side.addWidget(btn)
            self.nav_buttons.append(btn)
        side.addStretch(1)
        self.user_label = QLabel("")
        self.user_label.setStyleSheet("color:#94a3b8;font-size:11px;padding:8px;")
        self.user_label.setWordWrap(True)
        side.addWidget(self.user_label)
        root_lay.addWidget(sidebar)

        right = QWidget()
        right_lay = QVBoxLayout(right); right_lay.setContentsMargins(0, 0, 0, 0); right_lay.setSpacing(0)
        top = QFrame(); top.setObjectName("TopBar"); top.setFixedHeight(72)
        top_lay = QHBoxLayout(top); top_lay.setContentsMargins(20, 10, 20, 10)
        self.page_title = QLabel("داشبورد"); self.page_title.setObjectName("PageTitle")
        self.page_hint = QLabel(""); self.page_hint.setObjectName("PageHint")
        titles = QVBoxLayout(); titles.setSpacing(2); titles.addWidget(self.page_title); titles.addWidget(self.page_hint)
        top_lay.addLayout(titles); top_lay.addStretch(1)
        self.clock = QLabel(persian_now()); self.clock.setObjectName("PageHint")
        top_lay.addWidget(self.clock)
        self.theme_btn = QPushButton("🌙 حالت تیره")
        self.theme_btn.clicked.connect(self.toggle_theme)
        top_lay.addWidget(self.theme_btn)
        right_lay.addWidget(top)

        self.stack = QStackedWidget()
        # برای سازگاری با تست‌ها و کدهای قبلی، tabs همچنان وجود دارد اما پنهان است.
        self.tabs = QTabWidget(); self.tabs.setVisible(False)
        self.dashboard = DashboardTab(con, self.open_tab)
        self.tab_customers = CustomersTab(con, self)
        self.tab_products = ProductsTab(con, self)
        self.tab_invoices = InvoicesTab(con, self)
        self.tab_payments = PaymentsTab(con, self)
        self.tab_cheques = ChequesTab(con, self)
        self.tab_reports = ReportsTab(con, self)
        self.tab_settings = SettingsTab(con, self)
        self.pages = [self.dashboard, self.tab_customers, self.tab_products, self.tab_invoices,
                      self.tab_payments, self.tab_cheques, self.tab_reports, self.tab_settings]
        for w in self.pages:
            self.tabs.addTab(w, "")
            scroll = QScrollArea(); scroll.setWidgetResizable(True); scroll.setFrameShape(QFrame.NoFrame)
            scroll.setWidget(w)
            self.stack.addWidget(scroll)
        right_lay.addWidget(self.stack, 1)
        root_lay.addWidget(right, 1)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("آماده")
        self._timer = QTimer(self); self._timer.timeout.connect(lambda: self.clock.setText(persian_now())); self._timer.start(30000)

        u = auth.current() or {}
        self.user_label.setText(f"{u.get('full_name') or u.get('username', '')}\n{auth.role_label(u.get('role', ''))}")
        self.apply_permissions()
        self.open_tab(0)

    def apply_permissions(self):
        blocked = 0
        for w in self.pages:
            blocked += apply_permissions(w)
        return blocked

    def open_tab(self, index: int):
        index = max(0, min(index, len(self.pages) - 1))
        self.stack.setCurrentIndex(index)
        self.tabs.setCurrentIndex(index)
        if index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        _, title, hint = self.PAGES[index]
        self.page_title.setText(title)
        self.page_hint.setText(hint)
        w = self.pages[index]
        if hasattr(w, "refresh"):
            try:
                w.refresh()
            except Exception as e:
                self.statusBar().showMessage(f"خطا در بروزرسانی: {e}")

    def toggle_theme(self):
        app = QApplication.instance()
        mode = "dark" if app.property("theme_mode") != "dark" else "light"
        app.setProperty("theme_mode", mode)
        apply_theme(app, mode)
        self.theme_btn.setText("☀️ حالت روشن" if mode == "dark" else "🌙 حالت تیره")

    def closeEvent(self, event):
        if QMessageBox.question(self, "خروج", "آیا از برنامه خارج می‌شوید؟",
                                QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            path = db.auto_backup(self.con, "exit")
            if path:
                self.statusBar().showMessage(f"پشتیبان خروج: {path}")
            elif db.last_backup_error:
                msg_info(self, f"پشتیبان خودکار ناموفق بود:\n{db.last_backup_error}")
            event.accept()
        else:
            event.ignore()


class DashboardTab(QWidget):
    def __init__(self, con, open_tab=None):
        super().__init__()
        self.con = con
        self.open_tab = open_tab
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 20)
        lay.setSpacing(14)
        self.hint = QLabel(""); self.hint.setObjectName("PageHint"); self.hint.setWordWrap(True)
        lay.addWidget(self.hint)
        grid = QGridLayout(); grid.setSpacing(12)
        self.cards = {}
        specs = [
            ("sales", "فروش خالص سال", "#2563eb"),
            ("profit", "سود ناخالص", "#059669"),
            ("stock", "ارزش موجودی انبار", "#d97706"),
            ("receivable", "طلب از مشتریان", "#0891b2"),
            ("payable", "بدهی به تامین‌کنندگان", "#dc2626"),
            ("cash", "نقدینگی (صندوق و بانک)", "#7c3aed"),
            ("cheques_in", "چک‌های دریافتنی در جریان", "#059669"),
            ("cheques_out", "چک‌های پرداختنی در جریان", "#dc2626"),
        ]
        for i, (key, title, c) in enumerate(specs):
            card = StatCard(title, "—", c)
            self.cards[key] = card
            grid.addWidget(card, i // 4, i % 4)
        lay.addLayout(grid)

        row = QHBoxLayout(); row.setSpacing(12)
        self.chart = MonthlyChart(self.con)
        row.addWidget(self.chart, 2)
        alerts = QFrame(); alerts.setObjectName("Card")
        al = QVBoxLayout(alerts)
        al.addWidget(QLabel("هشدارها و وضعیت"))
        self.alerts = QLabel(""); self.alerts.setWordWrap(True); self.alerts.setTextFormat(Qt.RichText)
        al.addWidget(self.alerts); al.addStretch(1)
        row.addWidget(alerts, 1)
        lay.addLayout(row, 1)

        quick = QHBoxLayout()
        for text, idx, perm in [("➕ فاکتور جدید", 3, "invoice.create"), ("💵 دریافت وجه", 4, "payment.create"),
                                ("📦 کالاها", 2, "item.edit"), ("📊 گزارش‌ها", 6, "report.view")]:
            b = QPushButton(text); b.setProperty("perm", perm)
            if perm == "invoice.create": b.setProperty("accent", "primary")
            b.clicked.connect(lambda checked=False, i=idx: self.open_tab and self.open_tab(i))
            quick.addWidget(b)
        quick.addStretch(1)
        lay.addLayout(quick)

    def refresh(self):
        d = repo.dashboard(self.con)
        s = d["sales"]
        f = lambda v: repo.fmt_money(self.con, v, with_unit=True)
        self.cards["sales"].set_value(f(s["net_sales"]), f"سود ناخالص: {s['margin']:.1f}٪")
        self.cards["profit"].set_value(f(s["gross_profit"]), f"بهای تمام‌شده: {f(s['cogs'])}")
        self.cards["stock"].set_value(f(d["stock"]["total_value"]), f"{len(d['stock']['rows'])} قلم کالا")
        self.cards["receivable"].set_value(f(d["customers"]["total"]), f"{len(d['customers']['rows'])} طرف حساب")
        self.cards["payable"].set_value(f(d["suppliers"]["total"]), f"{len(d['suppliers']['rows'])} طرف حساب")
        self.cards["cash"].set_value(f(d["cash"]))
        ch = d["cheques"]
        self.cards["cheques_in"].set_value(f(ch["received_pending"]), f"{ch['received_count']} فقره")
        self.cards["cheques_out"].set_value(f(ch["paid_pending"]), f"{ch['paid_count']} فقره")
        low = [r for r in d["stock"]["rows"] if r["low"]]
        parts = []
        parts.append("✅ تراز آزمایشی متوازن است." if d["trial"]["balanced"] else "⛔ تراز آزمایشی نامتوازن است!")
        if low: parts.append(f"⚠️ {len(low)} کالا زیر حداقل موجودی است.")
        if ch["overdue"]: parts.append(f"⏰ {ch['overdue']} چک سررسید گذشته دارد.")
        if ch["due_soon"]: parts.append(f"🔔 {ch['due_soon']} چک تا ۷ روز آینده سررسید می‌شود.")
        rec = repo.report_reconciliation(self.con)
        if rec["stock_difference"]: parts.append(f"🧮 مغایرت انبار و دفتر: {f(rec['stock_difference'])}")
        self.alerts.setText("<br>".join(parts))
        self.hint.setText(f"سال مالی {utils.to_persian_digits(str(d['jalali_year']))} — {persian_now()}")
        self.chart.refresh()


class MonthlyChart(QWidget):
    """نمودار میله‌ای فروش ماهانه با QPainter (بدون وابستگی خارجی)."""
    def __init__(self, con):
        super().__init__()
        self.con = con
        self.data = []
        self.setMinimumHeight(240)

    def refresh(self):
        today = utils.today_g()
        jy = int(utils.today_j()[:4])
        self.data = []
        for m in range(1, 13):
            start = repo.jalali.from_jalali_str(f"{jy}/{m:02d}/01")
            end = repo.jalali.from_jalali_str(f"{jy}/{m:02d}/{repo.jalali.days_in_jalali_month(jy, m):02d}")
            if start > today:
                self.data.append(0); continue
            rows = self.con.execute("""SELECT COALESCE(SUM(subtotal-discount),0) v FROM invoices
                WHERE kind='sale' AND status='confirmed' AND inv_date BETWEEN ? AND ?""", (start, min(end, today))).fetchone()
            ret = self.con.execute("""SELECT COALESCE(SUM(subtotal-discount),0) v FROM invoices
                WHERE kind='sale_return' AND status='confirmed' AND inv_date BETWEEN ? AND ?""", (start, min(end, today))).fetchone()
            self.data.append(rows["v"] - ret["v"])
        self.update()

    def paintEvent(self, event):
        from PySide6.QtGui import QPainter, QColor, QPen, QFont
        app = QApplication.instance()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(16, 30, -16, -30)
        p.setPen(QColor(color(app, "text")))
        p.setFont(QFont(load_font_name(), 11, QFont.Bold))
        p.drawText(self.rect().adjusted(16, 6, 0, 0), Qt.AlignRight | Qt.AlignTop, "فروش خالص ماهانه")
        if not self.data or max(self.data) <= 0:
            p.setPen(QColor(color(app, "muted")))
            p.drawText(rect, Qt.AlignCenter, "داده‌ای برای نمایش نیست")
            p.end(); return
        maxv = max(self.data)
        n = len(self.data)
        bw = rect.width() / n
        p.setPen(QPen(QColor(color(app, "border")), 1))
        for i in range(5):
            y = rect.top() + rect.height() * i / 4
            p.drawLine(rect.left(), int(y), rect.right(), int(y))
        for i, v in enumerate(self.data):
            h = int(rect.height() * (v / maxv)) if maxv else 0
            x = rect.left() + int(i * bw + bw * 0.2)
            y = rect.bottom() - h
            p.setBrush(QColor(color(app, "primary")))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(x, y, max(4, int(bw * 0.6)), h, 4, 4)
            p.setPen(QColor(color(app, "muted")))
            p.setFont(QFont(load_font_name(), 8))
            p.drawText(int(rect.left() + i * bw), rect.bottom() + 4, int(bw), 20, Qt.AlignCenter,
                       utils.to_persian_digits(str(i + 1)))
        p.end()


def load_font_name():
    app = QApplication.instance()
    return app.font().family() if app else "Vazirmatn"
