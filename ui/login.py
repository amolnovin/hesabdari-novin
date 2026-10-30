# -*- coding: utf-8 -*-
"""دیالوگ ورود به برنامه و ساخت نخستین کاربر"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QVBoxLayout,
)

import auth


class LoginDialog(QDialog):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self.user = None
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("ورود به برنامه حسابداری")
        self.setModal(True)
        self.resize(360, 210)

        lay = QVBoxLayout(self)
        title = QLabel("لطفاً نام کاربری و رمز عبور خود را وارد کنید")
        title.setStyleSheet("font-weight:bold;color:#123c5a;padding:6px")
        lay.addWidget(title)

        form = QFormLayout()
        self.username = QLineEdit()
        self.username.setPlaceholderText("مثال: admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        form.addRow("نام کاربری:", self.username)
        form.addRow("رمز عبور:", self.password)
        lay.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#b3261e")
        self.error.setVisible(False)
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("ورود")
        buttons.button(QDialogButtonBox.Cancel).setText("خروج")
        buttons.accepted.connect(self.try_login)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def try_login(self):
        user = auth.authenticate(self.con, self.username.text(), self.password.text())
        if user:
            self.user = user
            self.accept()
        else:
            self.error.setText("نام کاربری یا رمز عبور اشتباه است")
            self.error.setVisible(True)
            self.password.clear()
            self.password.setFocus()


class FirstRunDialog(QDialog):
    """ساخت نخستین کاربر (مدیر سیستم) در اولین اجرا"""

    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self.user = None
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("خوش آمدید — ساخت مدیر سیستم")
        self.setModal(True)
        self.resize(400, 280)

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(
            "برای امنیت اطلاعات مالی، برنامه دارای کاربر و رمز عبور است.\n"
            "لطفاً یک مدیر سیستم ایجاد کنید."))
        form = QFormLayout()
        self.full_name = QLineEdit()
        self.username = QLineEdit("admin")
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password2 = QLineEdit()
        self.password2.setEchoMode(QLineEdit.Password)
        form.addRow("نام و نام خانوادگی:", self.full_name)
        form.addRow("نام کاربری:", self.username)
        form.addRow("رمز عبور:", self.password)
        form.addRow("تکرار رمز عبور:", self.password2)
        lay.addLayout(form)

        self.error = QLabel("")
        self.error.setStyleSheet("color:#b3261e")
        lay.addWidget(self.error)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("ایجاد و ورود")
        buttons.button(QDialogButtonBox.Cancel).setText("خروج")
        buttons.accepted.connect(self.create)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def create(self):
        if self.password.text() != self.password2.text():
            self.error.setText("رمز عبور و تکرار آن یکسان نیست")
            return
        try:
            uid = auth.create_user(self.con, self.username.text(), self.password.text(),
                                   "admin", self.full_name.text())
        except Exception as e:
            self.error.setText(str(e))
            return
        self.user = auth.authenticate(self.con, self.username.text(), self.password.text())
        if self.user:
            self.accept()
        else:
            self.error.setText("خطا در ورود خودکار")


class ChangePasswordDialog(QDialog):
    def __init__(self, con, user, parent=None):
        super().__init__(parent)
        self.con = con
        self.user = user
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle("تغییر رمز عبور")
        form = QFormLayout(self)
        self.p1 = QLineEdit()
        self.p1.setEchoMode(QLineEdit.Password)
        self.p2 = QLineEdit()
        self.p2.setEchoMode(QLineEdit.Password)
        form.addRow("رمز عبور جدید:", self.p1)
        form.addRow("تکرار رمز عبور:", self.p2)
        self.error = QLabel("")
        self.error.setStyleSheet("color:#b3261e")
        form.addRow(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.apply)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def apply(self):
        if self.p1.text() != self.p2.text():
            self.error.setText("رمز عبور و تکرار آن یکسان نیست")
            return
        try:
            auth.change_password(self.con, self.user["id"], self.p1.text())
            self.accept()
        except Exception as e:
            self.error.setText(str(e))
