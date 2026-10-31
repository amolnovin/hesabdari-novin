# -*- coding: utf-8 -*-
"""نقطهٔ ورود برنامه — حسابداری نوین برای کسب‌وکار کوچک."""
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

import auth
import db
from ui.login import FirstRunDialog, LoginDialog
from ui.main_window import MainWindow
from ui.theme import apply_theme, load_font


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("حسابداری نوین")
    app.setLayoutDirection(Qt.RightToLeft)
    load_font(app)
    apply_theme(app, "light")
    app.setProperty("theme_mode", "light")

    try:
        restored = db.apply_pending_restore()
    except Exception as e:
        QMessageBox.critical(None, "خطای بازیابی", f"بازیابی مرحله‌بندی‌شده اعمال نشد:\n{e}")
        restored = None
    con = db.connect()
    try:
        warnings = db.init_db(con)
    except Exception as e:
        QMessageBox.critical(None, "خطای پایگاه داده", str(e))
        sys.exit(1)
    if restored:
        QMessageBox.information(None, "بازیابی انجام شد", "پشتیبان انتخاب‌شده با موفقیت بازیابی شد.")
    if warnings:
        QMessageBox.warning(None, "گزارش مهاجرت پایگاه داده", "\n".join(warnings))

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
    code = app.exec()
    con.close()
    sys.exit(code)


if __name__ == "__main__":
    main()
