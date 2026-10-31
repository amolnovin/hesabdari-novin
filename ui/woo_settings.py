# -*- coding: utf-8 -*-
"""پیکربندی، آزمون و گزارش اتصال WooCommerce."""

from __future__ import annotations

import secrets
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

import db
from ui.widgets import msg_error, msg_info
from woocommerce import WooClient


class WooSettingsDialog(QDialog):
    def __init__(self, con, worker_getter=None, parent=None):
        super().__init__(parent)
        self.con = con
        self.worker_getter = worker_getter
        self.setWindowTitle("اتصال فروشگاه ووکامرس")
        self.setLayoutDirection(Qt.RightToLeft)
        self.resize(850, 700)
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.enabled = QCheckBox("همگام‌سازی خودکار فعال باشد")
        self.url = QLineEdit()
        self.url.setPlaceholderText("https://shop.example.ir")
        self.ck = QLineEdit()
        self.ck.setPlaceholderText("ck_…")
        self.cs = QLineEdit()
        self.cs.setEchoMode(QLineEdit.Password)
        self.cs.setPlaceholderText("cs_… (در این برنامه ماسک می‌شود)")
        self.query_auth = QCheckBox(
            "استفاده از احراز هویت query string (فقط در صورت الزام هاست؛ HTTPS اجباری)"
        )
        self.factor = QComboBox()
        for label, value in (
            ("ووکامرس ریال است (×۱)", 1),
            ("ووکامرس تومان است (×۱۰ ریال)", 10),
            ("ووکامرس صدتومان است (×۱۰۰ ریال)", 100),
        ):
            self.factor.addItem(label, value)
        self.interval = QSpinBox()
        self.interval.setRange(10, 3600)
        self.interval.setSuffix(" ثانیه")
        self.sync_from = QLineEdit()
        self.sync_from.setPlaceholderText(
            "خالی = سفارش‌های پس از فعال‌سازی؛ نمونه: 2026-01-01T00:00:00Z"
        )
        self.stock_master = QLabel(
            "دفتر انبار حسابداری مرجع است؛ تغییر موجودی ووکامرس به‌صورت تعدیل مالی ثبت نمی‌شود."
        )
        self.products = QCheckBox("همگام‌سازی کالا / قیمت / موجودی")
        self.orders = QCheckBox("دریافت سفارش‌ها و ساخت فاکتور و سند حسابداری")
        self.customers = QCheckBox("همگام‌سازی مشتریان و طرف‌حساب‌ها")
        self.webhook = QCheckBox(
            "فعال‌سازی Webhook ورودی (دریافت رویدادها با تأخیر کمتر)"
        )
        self.webhook_port = QSpinBox()
        self.webhook_port.setRange(1024, 65535)
        self.webhook_port.setValue(8765)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.Password)
        self.secret_btn = QPushButton("تولید کلید امن")
        self.secret_btn.clicked.connect(
            lambda: self.secret.setText(secrets.token_urlsafe(32))
        )
        self.public_url = QLineEdit()
        self.public_url.setPlaceholderText("https://your-domain.example/woo/webhook")
        self.public_url.setToolTip(
            "این نشانی باید از اینترنت و با HTTPS قابل دسترس باشد؛ TLS را reverse proxy فراهم کند."
        )
        form.addRow("", self.enabled)
        form.addRow("نشانی فروشگاه:", self.url)
        form.addRow("Consumer key:", self.ck)
        form.addRow("Consumer secret:", self.cs)
        form.addRow("", self.query_auth)
        form.addRow("واحد قیمت ووکامرس:", self.factor)
        form.addRow("فاصلهٔ polling:", self.interval)
        form.addRow("شروع دریافت سفارش (UTC):", self.sync_from)
        form.addRow("", self.stock_master)
        form.addRow("امکانات:", self.products)
        form.addRow("", self.orders)
        form.addRow("", self.customers)
        form.addRow("", self.webhook)
        form.addRow("پورت Webhook:", self.webhook_port)
        secret_row = QHBoxLayout()
        secret_row.addWidget(self.secret, 1)
        secret_row.addWidget(self.secret_btn)
        form.addRow("کلید امضای Webhook:", secret_row)
        form.addRow("URL عمومی Webhook:", self.public_url)
        root.addLayout(form)
        warning = QLabel(
            "نکته: در ویندوز پشت NAT/فایروال، Webhook مستقیم قابل دسترسی نیست؛ برای دریافت نزدیک‌به‌لحظه باید URL عمومی HTTPS، reverse proxy/VPS و rule فایروال امن داشته باشید. بدون آن polling دوره‌ای فعال است. هیچ رویدادی بدون HMAC معتبر پذیرفته نمی‌شود."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet(
            "color:#9a3412;background:#fff7ed;padding:8px;border-radius:5px"
        )
        root.addWidget(warning)

        buttons = QHBoxLayout()
        self.save_btn = QPushButton("ذخیره و اجرا")
        self.test_btn = QPushButton("آزمون اتصال")
        self.sync_btn = QPushButton("همگام‌سازی همین حالا")
        self.hook_btn = QPushButton("ثبت Webhookها در ووکامرس")
        for b in (self.save_btn, self.test_btn, self.sync_btn, self.hook_btn):
            buttons.addWidget(b)
        buttons.addStretch(1)
        root.addLayout(buttons)
        self.save_btn.clicked.connect(self.save)
        self.test_btn.clicked.connect(self.test_connection)
        self.sync_btn.clicked.connect(self.sync_now)
        self.hook_btn.clicked.connect(self.register_webhooks)
        self.status = QLabel("")
        root.addWidget(self.status)
        self.logs = QTableWidget(0, 5)
        self.logs.setHorizontalHeaderLabels(["زمان", "جهت", "نوع", "وضعیت", "جزئیات"])
        self.logs.horizontalHeader().setStretchLastSection(True)
        self.logs.setAlternatingRowColors(True)
        root.addWidget(self.logs, 1)
        self._load()
        self.refresh_logs()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_logs)
        self.timer.start(3000)

    def _load(self):
        def g(key, default=""):
            return db.get_setting(self.con, key, default)

        self.enabled.setChecked(g("woo_enabled", "0") == "1")
        self.url.setText(g("woo_url"))
        self.ck.setText(g("woo_consumer_key"))
        self.cs.setText(g("woo_consumer_secret"))
        self.query_auth.setChecked(g("woo_query_auth", "0") == "1")
        self.factor.setCurrentIndex(
            max(0, self.factor.findData(int(g("woo_price_factor", "10") or 10)))
        )
        self.interval.setValue(int(g("woo_interval", "20") or 20))
        self.sync_from.setText(g("woo_sync_from"))
        self.products.setChecked(g("woo_sync_products", "1") == "1")
        self.orders.setChecked(g("woo_sync_orders", "1") == "1")
        self.customers.setChecked(g("woo_sync_customers", "1") == "1")
        self.webhook.setChecked(g("woo_webhook_enabled", "0") == "1")
        self.webhook_port.setValue(int(g("woo_webhook_port", "8765") or 8765))
        self.secret.setText(g("woo_webhook_secret"))
        self.public_url.setText(g("woo_webhook_url"))

    def save(self):
        try:
            self._persist()
            msg_info(
                self, "تنظیمات اتصال ذخیره شد. سرویس با تنظیمات جدید راه‌اندازی می‌شود."
            )
            if self.parent() and hasattr(self.parent(), "restart_woo_worker"):
                self.parent().restart_woo_worker()
            self.accept()
        except Exception as e:
            msg_error(self, str(e))

    def _persist(self):
        url = self.url.text().strip().rstrip("/")
        if url and not url.startswith("https://"):
            raise ValueError(
                "برای انتقال امن کلیدهای API، نشانی فروشگاه باید HTTPS باشد."
            )
        if self.enabled.isChecked() and (
            not url or not self.ck.text().strip() or not self.cs.text().strip()
        ):
            raise ValueError("برای فعال‌سازی، نشانی HTTPS و هر دو کلید API لازم است.")
        callback = self.public_url.text().strip().rstrip("/")
        if self.webhook.isChecked() and not self.enabled.isChecked():
            raise ValueError(
                "برای راه‌اندازی Webhook، همگام‌سازی خودکار و سرویس اتصال را نیز فعال کنید."
            )
        if self.webhook.isChecked() and (
            not self.secret.text().strip()
            or not callback.startswith("https://")
            or not callback.endswith("/woo/webhook")
        ):
            raise ValueError(
                "Webhook به secret و URL عمومی HTTPS با مسیر انتهایی /woo/webhook نیاز دارد."
            )
        sync_from = self.sync_from.text().strip()
        if sync_from:
            try:
                datetime.fromisoformat(sync_from.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "تاریخ شروع باید ISO UTC باشد؛ مانند 2026-01-01T00:00:00Z"
                ) from exc
        values = {
            "woo_enabled": "1" if self.enabled.isChecked() else "0",
            "woo_url": url,
            "woo_consumer_key": self.ck.text().strip(),
            "woo_consumer_secret": self.cs.text(),
            "woo_query_auth": "1" if self.query_auth.isChecked() else "0",
            "woo_price_factor": str(self.factor.currentData()),
            "woo_interval": str(self.interval.value()),
            "woo_sync_from": sync_from,
            "woo_stock_master": "accounting",
            "woo_sync_products": "1" if self.products.isChecked() else "0",
            "woo_sync_orders": "1" if self.orders.isChecked() else "0",
            "woo_sync_customers": "1" if self.customers.isChecked() else "0",
            "woo_webhook_enabled": "1" if self.webhook.isChecked() else "0",
            "woo_webhook_port": str(self.webhook_port.value()),
            "woo_webhook_secret": self.secret.text().strip(),
            "woo_webhook_url": self.public_url.text().strip(),
        }
        with db.tx(self.con):
            old_sync_from = db.get_setting(self.con, "woo_sync_from", "").strip()
            if old_sync_from != sync_from:
                self.con.execute(
                    "DELETE FROM woo_state WHERE key='orders_modified_after'"
                )
            sensitive = {
                "woo_consumer_key",
                "woo_consumer_secret",
                "woo_webhook_secret",
            }
            for k, v in values.items():
                if k in sensitive:
                    # Do not copy API credentials into audit_log before/after JSON.
                    self.con.execute(
                        "INSERT INTO settings(key,value) VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                        (k, v),
                    )
                else:
                    db.set_setting(self.con, k, v, require_permission=False)
            db.audit(
                self.con,
                "configure_woocommerce",
                "settings",
                None,
                f"enabled={values['woo_enabled']}; webhook={values['woo_webhook_enabled']}",
            )

    def _client(self):
        url = self.url.text().strip()
        if not url.lower().startswith("https://"):
            raise ValueError("آزمون اتصال نیز فقط با HTTPS مجاز است.")
        return WooClient(
            url,
            self.ck.text().strip(),
            self.cs.text(),
            query_auth=self.query_auth.isChecked(),
        )

    def test_connection(self):
        try:
            self._client().test_connection()
            self.status.setText("✅ اتصال موفق؛ REST API ووکامرس پاسخ داد.")
        except Exception as e:
            self.status.setText(f"❌ {e}")

    def sync_now(self):
        try:
            self.save_without_close()
            worker = self.worker_getter() if self.worker_getter else None
            if worker:
                worker.request_sync()
                self.status.setText("درخواست همگام‌سازی به صف سرویس فرستاده شد.")
            else:
                self.status.setText(
                    "ابتدا گزینهٔ همگام‌سازی خودکار را فعال و ذخیره کنید."
                )
        except Exception as e:
            self.status.setText(str(e))

    def save_without_close(self):
        self._persist()
        if self.parent() and hasattr(self.parent(), "restart_woo_worker"):
            self.parent().restart_woo_worker()

    def register_webhooks(self):
        try:
            endpoint = self.public_url.text().strip().rstrip("/")
            if (
                not endpoint.startswith("https://")
                or not endpoint.endswith("/woo/webhook")
                or not self.secret.text().strip()
            ):
                raise ValueError(
                    "ابتدا URL عمومی HTTPS با مسیر /woo/webhook و secret را وارد کنید."
                )
            client = self._client()
            topics = (
                "order.created",
                "order.updated",
                "product.created",
                "product.updated",
                "customer.created",
                "customer.updated",
            )
            existing = client.list_all("webhooks", per_page=100)
            found = {
                (x.get("topic"), (x.get("delivery_url") or "").rstrip("/")): x
                for x in existing
            }
            changed = 0
            for topic in topics:
                old = found.get((topic, endpoint))
                body = {
                    "name": f"Hesabdari Novin - {topic}",
                    "topic": topic,
                    "delivery_url": endpoint,
                    "secret": self.secret.text().strip(),
                    "status": "active",
                }
                if old:
                    client.put(f"webhooks/{int(old['id'])}", body)
                else:
                    client.post("webhooks", body)
                changed += 1
            self.status.setText(f"✅ هر {changed} webhook ثبت/به‌روزرسانی شد.")
        except Exception as e:
            self.status.setText(f"❌ ثبت Webhook ناموفق: {e}")

    def refresh_logs(self):
        if (
            not self.con
            or not self.con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='woo_log'"
            ).fetchone()
        ):
            return
        rows = self.con.execute(
            "SELECT * FROM woo_log ORDER BY id DESC LIMIT 80"
        ).fetchall()
        self.logs.setRowCount(len(rows))
        for r, row in enumerate(rows):
            vals = (
                row["ts"],
                row["direction"],
                row["entity"],
                row["status"],
                row["message"] or "",
            )
            for c, val in enumerate(vals):
                self.logs.setItem(r, c, QTableWidgetItem(str(val)))
