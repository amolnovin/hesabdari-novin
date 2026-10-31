# -*- coding: utf-8 -*-
"""
تست رابط کاربری بدون نیاز به صفحه نمایش (offscreen)
اجرا:  QT_QPA_PLATFORM=offscreen python tests/test_ui.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["ACC_DB_PATH"] = os.path.join(tempfile.mkdtemp(), "ui_test.db")
os.environ["ACC_DATA_DIR"] = os.path.dirname(os.environ["ACC_DB_PATH"])

from PySide6.QtCore import Qt, QTimer          # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

import auth                                    # noqa: E402
import db                                      # noqa: E402
import repo                                    # noqa: E402
import utils                                   # noqa: E402
_SERVICE = auth.service_mode(); _SERVICE.__enter__()
from ui.main_window import MainWindow          # noqa: E402
from ui.invoices import InvoiceDialog          # noqa: E402

con = db.connect()
db.init_db(con)

# --- دادهٔ نمونه ---
cust = repo.save_party(con, None, {"name": "فروشگاه آریا", "kind": "customer", "phone": "09121112222"})
sup = repo.save_party(con, None, {"name": "پخش پارس", "kind": "supplier"})
item = repo.save_item(con, None, {"name": "کالای نمونه", "unit": "عدد", "sale_price": 1_500_000,
                                  "purchase_price": 1_000_000, "vat_rate": 10,
                                  "track_stock": True, "stock_min": 3})
item2 = repo.save_item(con, None, {"name": "خدمت نصب", "unit": "ساعت", "sale_price": 2_000_000,
                                   "vat_rate": 10, "track_stock": False})

# خرید ۲۰ عدد
pur = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                    "gregorian_date": db.__dict__ and "2026-09-01"},
                        [{"item_id": item, "qty": 20, "unit_price": 1_000_000,
                          "discount": 0, "vat_rate": 10,
                          **{k: v for k, v in repo.calc_line(20, 1_000_000, 0, 10).items()
                             if k in ("net", "vat")}}])
repo.confirm_invoice(con, pur)

# فروش ۴ عدد + خدمت
sale = repo.save_invoice(con, None, {"kind": "sale", "party_id": cust,
                                     "gregorian_date": "2026-09-10", "discount": 50_000},
                         [{"item_id": item, "qty": 4, "unit_price": 1_500_000,
                           "discount": 0, "vat_rate": 10,
                           **{k: v for k, v in repo.calc_line(4, 1_500_000, 0, 10).items()
                              if k in ("net", "vat")}},
                          {"item_id": item2, "qty": 1, "unit_price": 2_000_000,
                           "discount": 0, "vat_rate": 10,
                           **{k: v for k, v in repo.calc_line(1, 2_000_000, 0, 10).items()
                              if k in ("net", "vat")}}])
repo.confirm_invoice(con, sale)
repo.add_payment(con, "receipt", cust, 3_000_000, "2026-09-12", "cash", sale)

app = QApplication(sys.argv)
app.setLayoutDirection(Qt.RightToLeft)

errors = []


def step(label, fn):
    try:
        fn()
        print(f"  ✅ {label}")
    except Exception as e:
        errors.append((label, e))
        print(f"  ❌ {label}: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()


print("=" * 66)
print("تست رابط کاربری")
print("=" * 66)

# کاربر برای تست دسترسی‌ها (اپراتور = دسترسی محدود)
if auth.count_users(con) == 0:
    auth.create_user(con, "admin", "12345678", "admin", "مدیر تست")
auth.set_current(auth.authenticate(con, "admin", "12345678"))

w = MainWindow(con)
w.show()
step("ساخت پنجرهٔ اصلی", lambda: w.show())

step("داشبورد", lambda: w.dashboard.refresh())


def switch_tabs():
    for i in range(w.tabs.count()):
        w.tabs.setCurrentIndex(i)
        app.processEvents()


step("رفتن به همهٔ برگه‌ها", switch_tabs)

step("برگهٔ مشتریان", w.tab_customers.refresh)
step("برگهٔ کالاها", w.tab_products.refresh)
step("برگهٔ فاکتورها", w.tab_invoices.refresh)
step("برگهٔ دریافت/پرداخت", w.tab_payments.refresh)
step("برگهٔ چک‌ها", w.tab_cheques.refresh)
step("برگهٔ تنظیمات", w.tab_settings.load)


def run_all_reports():
    for i in range(w.tab_reports.combo.count()):
        w.tab_reports.combo.setCurrentIndex(i)
        app.processEvents()
        assert w.tab_reports.table.rowCount() >= 0


step("اجرای همهٔ گزارشات", run_all_reports)


def cheque_flow():
    """ثبت، وصول و برگشت چک از طریق منطق برنامه"""
    cid = repo.add_cheque(con, "received", cust, "9001", 2_000_000,
                          "2026-09-20", "2026-10-20", "بانک تست")
    w.tab_cheques.refresh()
    assert w.tab_cheques.table.rowCount() >= 1
    repo.clear_cheque(con, cid, "bank")
    w.tab_cheques.refresh()
    assert con.execute("SELECT status FROM cheques WHERE id=?", (cid,)).fetchone()["status"] == "cleared"
    ch = repo.add_cheque(con, "paid", sup, "9002", 1_000_000, "2026-09-20", "2026-10-20", "بانک تست")
    repo.bounce_cheque(con, ch)
    w.tab_cheques.refresh()
    t = repo.report_trial_balance(con)
    assert t["balanced"], "دفاتر پس از عملیات چک نامتوازن شد"


step("گردش کاملِ چک‌ها", cheque_flow)


def permissions():
    """دکمه‌های غیرمجاز برای کاربرِ محدود غیرفعال می‌شوند"""
    global _SERVICE
    _SERVICE.__exit__(None,None,None)
    from ui.widgets import apply_permissions
    auth.set_current(auth.authenticate(con, "admin", "12345678"))
    before = apply_permissions(w.tab_invoices)
    assert before == 0, "مدیر نباید محدود شود"
    auth.create_user(con, "viewer1", "12345678", "viewer", "مشاهده‌گر")
    auth.set_current(auth.authenticate(con, "viewer1", "12345678"))
    after = apply_permissions(w.tab_invoices)
    assert after > 0, "دکمه‌های غیرمجاز غیرفعال نشدند"
    try:
        repo.cancel_invoice(con, sale, "تست دسترسی")
        raise AssertionError("مشاهده‌گر نباید بتواند فاکتور را ابطال کند")
    except PermissionError:
        pass
    auth.set_current(auth.authenticate(con, "admin", "12345678"))
    apply_permissions(w.tab_invoices)
    _SERVICE = auth.service_mode(); _SERVICE.__enter__()


step("اعمال سطح دسترسی", permissions)


def open_invoice_dialog():
    """صدور فاکتور + حذف ردیف میانی + ویرایش سلول (تست باگ‌های جابه‌جایی ردیف)"""
    d = InvoiceDialog(con, w, "sale")
    d._add_line(item_id=item, qty=2, price=1_500_000, discount=0, vat=10)
    d._add_line(item_id=item2, qty=1, price=2_000_000, discount=0, vat=10)
    d._add_line(item_id=item, qty=5, price=1_500_000, discount=0, vat=10)
    app.processEvents()
    assert d.lines.rowCount() == 4, "یک ردیف خالی در ابتدا + ۳ ردیف جدید"
    # حذف ردیف میانی (ایندکس ۲) و بررسی درست‌ماندن بقیه
    d._remove_line(2)
    app.processEvents()
    assert d.lines.rowCount() == 3
    assert d.rows[1]["price"] == 1_500_000, "ردیف‌ها پس از حذف جابه‌جا شده‌اند"
    # ویرایش مستقیم یک سلول عددی در جدول
    d.lines.item(2, 1).setText("10")
    app.processEvents()
    assert d.rows[2]["qty"] == 10, "ویرایش سلول در مدل داده ثبت نشد"
    # جمع نهایی: (۲×۱،۵۰۰،۰۰۰) + (۱۰×۱،۵۰۰،۰۰۰) = ۱۸،۰۰۰،۰۰۰ + مالیات ۱،۸۰۰،۰۰۰
    assert d.lbl_total.text() == utils.fmt(19_800_000), f"جمع اشتباه: {d.lbl_total.text()}"
    d.reject()


step("دیالوگ صدور فاکتور جدید", open_invoice_dialog)


def open_existing_invoice():
    d = InvoiceDialog(con, w, "sale", sale)
    app.processEvents()
    assert d.lines.rowCount() == 2
    d.reject()


step("دیالوگ مشاهدهٔ فاکتور موجود", open_existing_invoice)

def login_flow():
    """تست دیالوگِ اولین اجرا و ورود"""
    from ui.login import FirstRunDialog, LoginDialog
    import tempfile
    con2 = db.connect(os.path.join(tempfile.mkdtemp(), "login.db"))
    db.init_db(con2)
    assert auth.count_users(con2) == 0
    d = FirstRunDialog(con2, w)
    d.full_name.setText("مدیر آزمایشی")
    d.username.setText("boss")
    d.password.setText("12345678")
    d.password2.setText("12345678")
    d.create()          # فراخوانیِ مستقیمِ منطقِ دکمه (مانند کلیک کاربر)
    assert auth.count_users(con2) == 1, "کاربرِ مدیر ساخته نشد"
    assert d.result() == d.DialogCode.Accepted, "دیالوگ تأیید نشد"
    assert d.user and d.user["role"] == "admin"

    login = LoginDialog(con2, w)
    login.username.setText("boss")
    login.password.setText("wrong")
    login.try_login()
    assert login.user is None, "رمز اشتباه پذیرفته شد!"
    login.password.setText("12345678")
    login.try_login()
    assert login.user is not None, "ورود با رمز صحیح انجام نشد"
    auth.set_current(login.user)
    con2.close()


step("جریانِ ساخت مدیر و ورود", login_flow)

# --- اسکرین‌شات ---
os.makedirs("screenshots", exist_ok=True)
shots = []


def shot(name, widget):
    p = os.path.join("screenshots", name)
    widget.grab().save(p)
    shots.append(p)


for i, name in enumerate(["1-dashboard", "2-customers", "3-products", "4-invoices",
                          "5-payments", "6-cheques", "7-reports", "8-settings"]):
    w.open_tab(i)
    app.processEvents()
    shot(name + ".png", w)

d = InvoiceDialog(con, w, "sale")
d._add_line(item_id=item, qty=3, price=1_500_000, discount=0, vat=10)
d._add_line(item_id=item2, qty=1, price=2_000_000, discount=0, vat=10)
app.processEvents()
shot("9-invoice-dialog.png", d)
d.reject()

print("\nاسکرین‌شات‌ها:")
for p in shots:
    print("  📷", p, os.path.getsize(p), "bytes")

print("\n" + "=" * 66)
print(f"نتیجه: {'✅ همه تست‌های رابط کاربری موفق بود' if not errors else f'❌ {len(errors)} خطا'}")
print("=" * 66)
sys.exit(1 if errors else 0)
