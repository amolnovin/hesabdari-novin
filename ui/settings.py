# -*- coding: utf-8 -*-
"""برگهٔ تنظیمات، پشتیبان‌گیری و مشاهدهٔ کدینگ حساب‌ها"""

import os
import shutil
import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QInputDialog,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)

import auth
import db
import business_profiles
import jalali
import repo
import utils
from ui.login import ChangePasswordDialog
from ui.widgets import (FormDialog, add_row, apply_permissions, make_table,
                        msg_error, msg_info, msg_warn, msg_ask, selected_id)


class SettingsTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()
        self.load()

    def _build(self):
        lay = QVBoxLayout(self)
        form = QFormLayout()

        self.f_company = QLineEdit()
        self.f_national = QLineEdit()
        self.f_economic = QLineEdit()
        self.f_address = QLineEdit()
        self.f_phone = QLineEdit()
        self.f_footer = QLineEdit()
        self.f_vat = QLineEdit()
        self.f_vat.setPlaceholderText("مثلاً ۱۰")
        self.money = QComboBox()
        self.money.addItem("ریال", "rial")
        self.money.addItem("تومان", "toman")

        for label, w in [
            ("نام شرکت / فروشگاه:", self.f_company),
            ("شناسه ملی:", self.f_national),
            ("کد اقتصادی:", self.f_economic),
            ("آدرس:", self.f_address),
            ("تلفن:", self.f_phone),
            ("نرخ پیش‌فرض مالیات بر ارزش افزوده (٪):", self.f_vat),
            ("واحد نمایش مبالغ:", self.money),
            ("متن پایین فاکتور:", self.f_footer),
        ]:
            form.addRow(label, w)
        lay.addLayout(form)
        self.vat_warning = QLabel("نرخ مالیات از پروفایل حدس زده نمی‌شود؛ نرخ/معافیت هر کالا را با مقررات جاری و مشاور مالیاتی بررسی کنید.")
        self.vat_warning.setWordWrap(True)
        self.vat_warning.setStyleSheet("color:#9a3412;background:#fff7ed;padding:7px;border-radius:5px")
        lay.addWidget(self.vat_warning)

        btns = QHBoxLayout()
        b_save = QPushButton("💾 ذخیره تنظیمات")
        b_save.setStyleSheet("QPushButton{background:#1f5f8b;color:#fff;padding:8px 16px;border-radius:6px;font-weight:bold}")
        b_save.clicked.connect(self.save)
        btns.addWidget(b_save)
        self.profile_combo = QComboBox()
        for key, title, description in business_profiles.list_profiles():
            self.profile_combo.addItem(title, key)
            self.profile_combo.setItemData(self.profile_combo.count() - 1, description, Qt.ToolTipRole)
        self.profile_desc = QLabel(""); self.profile_desc.setWordWrap(True)
        self.profile_combo.currentIndexChanged.connect(self._profile_preview)
        b_profile = QPushButton("اعمال نوع کسب‌وکار")
        b_profile.clicked.connect(self.save_profile)
        btns.addWidget(self.profile_combo); btns.addWidget(b_profile)
        self.b_woo = QPushButton("🛒 تنظیم اتصال ووکامرس")
        self.b_woo.clicked.connect(self.open_woo_settings)
        btns.addWidget(self.b_woo)
        lay.addWidget(self.profile_desc)
        lay.addLayout(btns)

        # --- پشتیبان‌گیری ---
        box = QVBoxLayout()
        box.addWidget(QLabel("<b>پشتیبان‌گیری و بازیابی</b>"))
        row = QHBoxLayout()
        b_backup = QPushButton("📦 تهیهٔ پشتیبان")
        b_backup.clicked.connect(self.backup)
        b_restore = QPushButton("♻️ بازیابی از فایل")
        b_restore.clicked.connect(self.restore)
        b_folder = QPushButton("📂 باز کردن پوشهٔ داده")
        b_folder.clicked.connect(self.open_folder)
        for b in (b_backup, b_restore, b_folder):
            row.addWidget(b)
        row.addStretch(1)
        box.addLayout(row)
        self.lbl_path = QLabel("")
        self.lbl_path.setStyleSheet("color:#5c6b7a;font-size:11px")
        box.addWidget(self.lbl_path)
        lay.addLayout(box)

        # --- کاربران ---
        lay.addWidget(QLabel("<b>کاربران و دسترسی‌ها</b>"))
        ub = QHBoxLayout()
        b_users = QPushButton("👤 مدیریت کاربران")
        b_users.clicked.connect(self.manage_users)
        b_pass = QPushButton("🔑 تغییر رمز عبور من")
        b_pass.clicked.connect(self.change_my_password)
        for b in (b_users, b_pass):
            ub.addWidget(b)
        ub.addStretch(1)
        lay.addLayout(ub)
        self.lbl_user = QLabel("")
        self.lbl_user.setStyleSheet("color:#5c6b7a;font-size:11px")
        lay.addWidget(self.lbl_user)

        # --- قفل دوره ---
        lay.addWidget(QLabel("<b>قفل دوره‌های مالی</b>"))
        pl = QHBoxLayout()
        self.period_year = QComboBox()
        for fy in self.con.execute("SELECT * FROM fiscal_year ORDER BY start_date"):
            self.period_year.addItem(fy["title"], fy["id"])
        self.period_month = QComboBox()
        for m in range(1, 13):
            self.period_month.addItem(f"{m:02d} — {jalali.jalali_month_name(m)}", m)
        b_lock = QPushButton("🔒 قفل/باز کردن دوره")
        b_lock.clicked.connect(self.toggle_period_lock)
        pl.addWidget(QLabel("سال:"))
        pl.addWidget(self.period_year)
        pl.addWidget(QLabel("ماه:"))
        pl.addWidget(self.period_month)
        pl.addWidget(b_lock)
        pl.addStretch(1)
        lay.addLayout(pl)
        self.period_status = QLabel("")
        self.period_status.setStyleSheet("color:#5c6b7a;font-size:11px")
        lay.addWidget(self.period_status)
        self.period_year.currentIndexChanged.connect(self.update_period_status)
        self.period_month.currentIndexChanged.connect(self.update_period_status)

        # --- کدینگ ---
        lay.addWidget(QLabel("<b>چارت حساب‌ها (کدینگ)</b>"))
        self.accounts = make_table(["کد", "نام حساب", "گروه", "نوع", "قابل ثبت سند"])
        lay.addWidget(self.accounts, 1)
        b_chart = QPushButton("🔄 بروزرسانی کدینگ")
        b_chart.clicked.connect(self.load_accounts)
        lay.addWidget(b_chart)
        b_audit = QPushButton("🕘 گزارش رویدادها (Audit)")
        b_audit.clicked.connect(self.show_audit)
        lay.addWidget(b_audit)

        self.load_accounts()

    def _profile_preview(self, *_):
        p = business_profiles.get_profile(self.profile_combo.currentData())
        self.profile_desc.setText(f"{p['description']} امکانات پیشنهادی: {', '.join(p['modules'])}. {p['note']} نرخ مالیات به‌صورت خودکار تغییر نمی‌کند؛ آن را طبق مقررات جاری تنظیم کنید.")

    def save_profile(self):
        try:
            p = business_profiles.apply_profile(self.con, self.profile_combo.currentData())
            self.profile_desc.setText(f"پروفایل «{p['title']}» اعمال شد. واحد پول و نرخ مالیات موجود تغییر نکرد تا اطلاعات ثبت‌شده دست‌کاری نشود.")
            mw = self.parent()
            if mw and hasattr(mw, "refresh_business_profile"):
                mw.refresh_business_profile()
            msg_info(self, "نوع کسب‌وکار و امکانات پیشنهادی ذخیره شد.")
        except Exception as e:
            msg_error(self, str(e))

    def open_woo_settings(self):
        from ui.woo_settings import WooSettingsDialog
        dlg = WooSettingsDialog(self.con, worker_getter=lambda: getattr(self.parent(), "woo_worker", None), parent=self)
        dlg.exec()
        self._load_business_profile()

    def restart_woo_worker(self):
        mw = self.parent()
        if mw and hasattr(mw, "restart_woo_worker"):
            mw.restart_woo_worker()

    def _load_business_profile(self):
        key = business_profiles.current_key(self.con)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(key)))
        self._profile_preview()

    # ------------------------------------------------------------------
    def load(self):
        g = lambda k, d="": db.get_setting(self.con, k, d)
        self.f_company.setText(g("company_name"))
        self._load_business_profile()
        self.f_national.setText(g("company_national_id"))
        self.f_economic.setText(g("company_economic_code"))
        self.f_address.setText(g("company_address"))
        self.f_phone.setText(g("company_phone"))
        self.f_footer.setText(g("invoice_footer"))
        self.f_vat.setText(g("default_vat_rate", "10"))
        idx = self.money.findData(g("money_unit", "rial"))
        self.money.setCurrentIndex(max(0, idx))
        self.lbl_path.setText(f"مسیر پایگاه داده: {db.db_path()}")
        u = auth.current()
        self.lbl_user.setText(
            f"کاربرِ جاری: {u['full_name'] or u['username']} "
            f"(نقش: {auth.role_label(u['role'])})" if u else "حالت بدون ورود")
        self.update_period_status()
        apply_permissions(self)

    def save(self):
        try:
            self._save_settings()
        except Exception as e:
            msg_error(self, str(e))

    def _save_settings(self):
        s = lambda w: utils.normalize(w.text())
        db.set_setting(self.con, "company_name", s(self.f_company))
        db.set_setting(self.con, "company_national_id", s(self.f_national))
        db.set_setting(self.con, "company_economic_code", s(self.f_economic))
        db.set_setting(self.con, "company_address", s(self.f_address))
        db.set_setting(self.con, "company_phone", s(self.f_phone))
        db.set_setting(self.con, "invoice_footer", s(self.f_footer))
        try:
            vat = float(utils.parse_float(self.f_vat.text()))
            db.set_setting(self.con, "default_vat_rate", str(vat))
        except ValueError:
            msg_warn(self, "نرخ مالیات باید عدد باشد")
        db.set_setting(self.con, "money_unit", self.money.currentData())
        self.con.commit()
        msg_info(self, "تنظیمات ذخیره شد")

    def update_period_status(self):
        fy_id = self.period_year.currentData()
        month = self.period_month.currentData()
        if not fy_id or not month:
            return
        locked = repo.period_locked(self.con, fy_id, month)
        self.period_status.setText(
            f"وضعیت {self.period_year.currentText()} / {jalali.jalali_month_name(month)}: "
            + ("🔒 قفل شده — ثبت سند در این ماه ممکن نیست" if locked else "🔓 باز"))

    def toggle_period_lock(self):
        fy_id = self.period_year.currentData()
        month = self.period_month.currentData()
        locked = repo.period_locked(self.con, fy_id, month)
        if locked and not msg_ask(self, f"ماه انتخابی باز شود؟"):
            return
        if not locked and not msg_ask(
                self, f"ماه انتخابی قفل شود؟\nپس از قفل شدن، ثبت سند در این ماه ممکن نیست."):
            return
        try:
            repo.set_period_lock(self.con, fy_id, month, not locked)
            self.update_period_status()
            msg_info(self, "انجام شد")
        except PermissionError as e:
            msg_error(self, str(e))

    def change_my_password(self):
        u = auth.current()
        if not u:
            msg_warn(self, "در حالت بدون ورود، کاربری تعریف نشده است")
            return
        d = ChangePasswordDialog(self.con, u, self)
        if d.exec():
            msg_info(self, "رمز عبور تغییر کرد")

    def manage_users(self):
        d = UsersDialog(self.con, self)
        d.exec()

    def load_accounts(self):
        types = {"asset": "دارایی", "liability": "بدهی", "equity": "حقوق صاحبان سهام",
                 "revenue": "درآمد", "expense": "هزینه"}
        rows = self.con.execute(
            """SELECT a.code, a.name, a.type, a.is_postable, p.name AS parent
               FROM accounts a LEFT JOIN accounts p ON p.id = a.parent_id
               ORDER BY a.code""").fetchall()
        self.accounts.setRowCount(0)
        for r in rows:
            add_row(self.accounts, [r["code"], r["name"], r["parent"] or "",
                                    types.get(r["type"], r["type"]),
                                    "بله" if r["is_postable"] else "خیر"])

    # ------------------------------------------------------------------
    def backup(self):
        try:
            path = db.make_backup(self.con, "manual")
            msg_info(self, f"پشتیبان با موفقیت ساخته شد:\n{path}")
        except Exception as e:
            msg_error(self, str(e))

    def restore(self):
        if not msg_ask(self, "بازیابی، تمام اطلاعات فعلی را با فایل پشتیبان جایگزین می‌کند.\n"
                               "ادامه می‌دهید؟"):
            return
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(self, "انتخاب فایل پشتیبان",
                                              db.backup_dir(), "Database (*.db)")
        if not path:
            return
        try:
            info = db.stage_restore(self.con, path)
            counts = info["counts"]
            msg_info(self, "فایل پشتیبان معتبر است و برای بازیابی آماده شد.\n"
                           f"شامل {counts['invoices']} فاکتور، {counts['payments']} دریافت/پرداخت و {counts['journal_entries']} سند.\n"
                           "برنامه بسته می‌شود؛ در اجرای بعدی بازیابی اعمال خواهد شد.")
            QApplication = __import__("PySide6.QtWidgets", fromlist=["QApplication"]).QApplication
            QApplication.instance().quit()
        except Exception as e:
            msg_error(self, str(e))

    def show_audit(self):
        d = QDialog(self)
        d.setWindowTitle("گزارش رویدادها")
        d.setLayoutDirection(Qt.RightToLeft)
        d.resize(900, 520)
        lay = QVBoxLayout(d)
        t = make_table(["زمان", "کاربر", "نقش", "عملیات", "جدول", "شناسه", "شرح"])
        for r in self.con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 1000"):
            add_row(t, [r["created_at"], r["username"] or "سیستم", r["role"] or "", r["action"],
                        r["table_name"], r["record_id"], r["detail"]])
        lay.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.exec()

    def open_folder(self):
        path = db.data_dir()
        try:
            if sys.platform == "win32":
                os.startfile(path)
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception as e:
            msg_info(self, f"مسیر پوشه:\n{path}")



class UsersDialog(QDialog):
    """مدیریت کاربران، نقش‌ها و فعال/غیرفعال کردن"""

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("مدیریت کاربران")
        self.resize(620, 420)
        lay = QVBoxLayout(self)

        self.table = make_table(["شناسه", "نام کاربری", "نام", "نقش", "وضعیت", "آخرین ورود"])
        lay.addWidget(self.table)

        btns = QHBoxLayout()
        for text, slot in [("➕ کاربر جدید", self.add_user),
                           ("🔑 تغییر رمز", self.reset_password),
                           ("✏️ تغییر نقش", self.change_role),
                           ("🚫 غیرفعال/فعال", self.toggle_active),
                           ("🔄 بروزرسانی", self.refresh)]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        note = QLabel("نقش‌ها: مدیر سیستم (دسترسی کامل) • حسابدار (ثبت، قطعی کردن، ابطال، چک‌ها) • "
                      "اپراتور (فقط ثبت پیش‌نویس) • مشاهده‌گر (فقط گزارشات)")
        note.setStyleSheet("color:#5c6b7a;font-size:11px")
        note.setWordWrap(True)
        lay.addWidget(note)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)
        self.refresh()

    def refresh(self):
        self.table.setRowCount(0)
        for u in auth.list_users(self.con):
            add_row(self.table, [
                u["id"], u["username"], u["full_name"] or "",
                auth.role_label(u["role"]),
                "فعال" if u["is_active"] else "غیرفعال",
                (u["last_login_at"] or "").replace("T", " "),
            ], data=u["id"])

    def _selected(self):
        uid = selected_id(self.table)
        if not uid:
            msg_warn(self, "ابتدا یک کاربر را انتخاب کنید")
        return uid

    def add_user(self):
        d = FormDialog(self, "کاربر جدید",
                       [("username", "نام کاربری *", "text"),
                        ("full_name", "نام و نام خانوادگی", "text"),
                        ("password", "رمز عبور (حداقل ۸ کاراکتر) *", "text")])
        role = QComboBox()
        for k, label in auth.ROLES.items():
            role.addItem(label, k)
        d.layout().itemAt(0).layout().insertRow(3, "نقش", role)
        if d.exec():
            if len(d.get("password")) < 8:
                msg_warn(self, "رمز عبور باید حداقل ۸ کاراکتر باشد")
                return
            try:
                auth.create_user(self.con, d.get("username"), d.get("password"),
                                 role.currentData(), d.get("full_name"))
                self.refresh()
                msg_info(self, "کاربر ایجاد شد")
            except Exception as e:
                msg_error(self, str(e))

    def reset_password(self):
        uid = self._selected()
        if not uid:
            return
        pwd, ok = QInputDialog.getText(self, "رمز عبور جدید", "رمز عبور (حداقل ۸ کاراکتر):",
                                       QLineEdit.Password)
        if ok and pwd:
            try:
                auth.change_password(self.con, uid, pwd)
                msg_info(self, "رمز عبور تغییر کرد")
            except Exception as e:
                msg_error(self, str(e))

    def change_role(self):
        uid = self._selected()
        if not uid:
            return
        items = list(auth.ROLES.values())
        current = self.con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()["role"]
        label, ok = QInputDialog.getItem(self, "تغییر نقش", "نقش جدید:", items,
                                         list(auth.ROLES).index(current), False)
        if ok:
            role = [k for k, v in auth.ROLES.items() if v == label][0]
            auth.update_user(self.con, uid, role=role)
            self.refresh()

    def toggle_active(self):
        uid = self._selected()
        if not uid:
            return
        u = self.con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
        if u["id"] == (auth.current() or {}).get("id"):
            msg_warn(self, "نمی‌توانید کاربرِ خود را غیرفعال کنید")
            return
        auth.update_user(self.con, uid, is_active=0 if u["is_active"] else 1)
        self.refresh()
