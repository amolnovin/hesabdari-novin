# -*- coding: utf-8 -*-
"""
نقطهٔ ورود برنامه — حسابداری کسب‌وکار کوچک
==========================================
اجرا:  python main.py

در اولین اجرا یک «مدیر سیستم» ساخته می‌شود و پس از آن ورود با رمز عبور الزامی است.
"""
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

import auth
import db
from ui.login import FirstRunDialog, LoginDialog
from ui.main_window import MainWindow


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)          # رابط راست‌چین
    app.setFont(QFont("Tahoma", 9))                 # فونت سازگار با فارسی

    con = db.connect()
    db.init_db(con)

    # --- ورود به سیستم -------------------------------------------------
    user = None
    if auth.count_users(con) == 0:
        dlg = FirstRunDialog(con)
        if dlg.exec():
            user = dlg.user
    else:
        dlg = LoginDialog(con)
        if dlg.exec():
            user = dlg.user

    if not user:
        sys.exit(0)
    auth.set_current(user)

    w = MainWindow(con)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
