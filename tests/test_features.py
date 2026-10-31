# -*- coding: utf-8 -*-
"""
تست ویژگی‌های مرحلهٔ ۹: کاربران و دسترسی • چک‌ها • سنوات بدهی • قفل دوره • پشتیبان خودکار
اجرا:  python tests/test_features.py
"""
import os
import sys
import tempfile
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMPDIR = tempfile.mkdtemp()
os.environ["ACC_DB_PATH"] = os.path.join(TMPDIR, "features.db")
os.environ["ACC_DATA_DIR"] = TMPDIR   # ایزوله: پشتیبان‌ها کنارِ دادهٔ واقعی نروند

import db          # noqa: E402
import jalali      # noqa: E402
import auth        # noqa: E402
import repo        # noqa: E402

_SERVICE = auth.service_mode(); _SERVICE.__enter__()

con = db.connect()
db.init_db(con)

passed = failed = 0


def check(label, cond, extra=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ✅ {label} {extra}")
    else:
        failed += 1
        print(f"  ❌ {label} {extra}")


def balance(account_code):
    """ماندهٔ یک حساب (بدهکار منهای بستانکار)"""
    return con.execute(
        """SELECT COALESCE(SUM(l.debit - l.credit),0) v
           FROM journal_lines l
           JOIN journal_entries e ON e.id = l.entry_id
           JOIN accounts a ON a.id = l.account_id
           WHERE a.code = ? AND e.status = 'posted'""", (account_code,)).fetchone()["v"]


def party_balance(party_id):
    return con.execute("SELECT balance FROM v_party_balance WHERE party_id = ?",
                       (party_id,)).fetchone()["balance"]


def trial_ok():
    t = repo.report_trial_balance(con)
    return t["balanced"]


print("=" * 70)
print("ویژگی‌های جدید")
print("=" * 70)

# ---------------------------------------------------------------------------
_SERVICE.__exit__(None,None,None)
print("\n── ۱) کاربران، رمز عبور و سطح دسترسی ──")
uid = auth.create_user(con, "admin", "12345678", "admin", "مدیر سیستم")
check("ایجاد کاربر مدیر", uid > 0)
check("تعداد کاربران = ۱", auth.count_users(con) == 1)

user = auth.authenticate(con, "admin", "12345678")
check("ورود با رمز صحیح", user is not None and user["role"] == "admin")
check("ورود با رمز اشتباه رد می‌شود", auth.authenticate(con, "admin", "wrong") is None)
check("ورود با نام کاربری اشتباه رد می‌شود", auth.authenticate(con, "nobody", "12345678") is None)

raw = con.execute("SELECT password_hash, salt FROM users WHERE id=?", (uid,)).fetchone()
check("رمز عبور به صورت متن ساده ذخیره نشده", "12345678" not in (raw["password_hash"] + raw["salt"]))
check("هش و نمک تولید شده‌اند", len(raw["salt"]) == 32 and len(raw["password_hash"]) == 64,
      f"(نمک {len(raw['salt'])} کاراکتر)")

op_id = auth.create_user(con, "op", "43214321", "operator", "اپراتور")
auth.set_current(auth.authenticate(con, "op", "43214321"))
check("اپراتور می‌تواند فاکتور ثبت کند", auth.has("invoice.create"))
check("اپراتور نمی‌تواند فاکتور را ابطال کند", not auth.has("invoice.cancel"))
check("اپراتور نمی‌تواند کاربران را مدیریت کند", not auth.has("user.manage"))
try:
    auth.require("invoice.cancel")
    check("require برای دسترسیِ غیرمجاز خطا می‌دهد", False)
except PermissionError as e:
    check("require برای دسترسیِ غیرمجاز خطا می‌دهد", True, f"({e})")
auth.set_current(None)
check("بدون ورود دسترسی ندارد", not auth.has("invoice.cancel"))

# ---------------------------------------------------------------------------
_SERVICE = auth.service_mode(); _SERVICE.__enter__()
print("\n── ۲) چک‌های دریافتنی ──")
cust = repo.save_party(con, None, {"name": "مشتری چکی", "kind": "customer"})
sup = repo.save_party(con, None, {"name": "تامین‌کننده چکی", "kind": "supplier"})
item = repo.save_item(con, None, {"name": "کالای چکی", "unit": "عدد", "sale_price": 5_000_000,
                                  "purchase_price": 3_000_000, "vat_rate": 10,
                                  "track_stock": True})

# تأمین موجودی اولیه
pur = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                    "gregorian_date": date.today().isoformat()},
                        [{"item_id": item, "qty": 5, "unit_price": 3_000_000, "discount": 0, "vat_rate": 10,
                          **{k: v for k, v in repo.calc_line(5, 3_000_000, 0, 10).items() if k in ("net", "vat")}}])
repo.confirm_invoice(con, pur)

# فروش ۲ عدد = ۱۰،۰۰۰،۰۰۰ + ۱،۰۰۰،۰۰۰ مالیات = ۱۱،۰۰۰،۰۰۰
inv = repo.save_invoice(con, None, {"kind": "sale", "party_id": cust,
                                    "gregorian_date": date.today().isoformat()},
                        [{"item_id": item, "qty": 2, "unit_price": 5_000_000,
                          "discount": 0, "vat_rate": 10,
                          **{k: v for k, v in repo.calc_line(2, 5_000_000, 0, 10).items()
                             if k in ("net", "vat")}}])
repo.confirm_invoice(con, inv)
check("ماندهٔ مشتری پس از فروش = ۱۱،۰۰۰،۰۰۰", party_balance(cust) == 11_000_000,
      f"({party_balance(cust):,})")

today = date.today().isoformat()
next_week = (date.today() + timedelta(days=7)).isoformat()

ch1 = repo.add_cheque(con, "received", cust, "1001", 5_000_000, today, next_week, "بانک ملی")
check("ثبت چک دریافتنی: اسناد دریافتنی = ۵،۰۰۰،۰۰۰",
      balance(repo.A_NOTES_RECEIVABLE) == 5_000_000, f"({balance(repo.A_NOTES_RECEIVABLE):,})")
check("ثبت چک دریافتنی: ماندهٔ مشتری = ۶،۰۰۰،۰۰۰", party_balance(cust) == 6_000_000,
      f"({party_balance(cust):,})")
check("تراز آزمایشی پس از ثبت چک", trial_ok())

repo.clear_cheque(con, ch1, "bank")
check("وصول چک: موجودی بانک = ۵،۰۰۰،۰۰۰", balance(repo.A_BANK) == 5_000_000,
      f"({balance(repo.A_BANK):,})")
check("وصول چک: اسناد دریافتنی صفر شد", balance(repo.A_NOTES_RECEIVABLE) == 0)
check("وضعیت چک = وصول‌شده",
      con.execute("SELECT status FROM cheques WHERE id=?", (ch1,)).fetchone()["status"] == "cleared")
check("تراز آزمایشی پس از وصول", trial_ok())

# برگشت خوردن چک
ch2 = repo.add_cheque(con, "received", cust, "1002", 6_000_000, today, next_week, "بانک صادرات")
check("چک دوم ثبت شد (ماندهٔ مشتری صفر)", party_balance(cust) == 0, f"({party_balance(cust):,})")
repo.bounce_cheque(con, ch2)
check("برگشت چک: ماندهٔ مشتری دوباره = ۶،۰۰۰،۰۰۰", party_balance(cust) == 6_000_000,
      f"({party_balance(cust):,})")
check("برگشت چک: اسناد دریافتنی صفر شد", balance(repo.A_NOTES_RECEIVABLE) == 0)
check("تراز آزمایشی پس از برگشت", trial_ok())

# ابطال چک
ch3 = repo.add_cheque(con, "received", cust, "1003", 1_000_000, today, next_week)
repo.cancel_cheque(con, ch3, "اشتباه در ثبت")
check("ابطال چک: ماندهٔ مشتری تغییر نکرد", party_balance(cust) == 6_000_000)
check("تراز آزمایشی پس از ابطال چک", trial_ok())

try:
    repo.add_cheque(con, "received", cust, "1003", 2_000_000, today, next_week)
    check("جلوگیری از شماره سریال تکراری", False)
except repo.AccountingError as e:
    check("جلوگیری از شماره سریال تکراری", True, f"({e})")

# ---------------------------------------------------------------------------
print("\n── ۳) چک‌های پرداختنی ──")
pur = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                    "gregorian_date": today},
                        [{"item_id": item, "qty": 10, "unit_price": 3_000_000,
                          "discount": 0, "vat_rate": 10,
                          **{k: v for k, v in repo.calc_line(10, 3_000_000, 0, 10).items()
                             if k in ("net", "vat")}}])
repo.confirm_invoice(con, pur)
debt = party_balance(sup)           # بدهیِ ما به تامین‌کننده (مثبت)
check("بدهی به تامین‌کننده = ۴۹،۵۰۰،۰۰۰", debt == 49_500_000, f"({debt:,})")

paid_ch = repo.add_cheque(con, "paid", sup, "2001", 10_000_000, today, next_week, "بانک تجارت")
check("ثبت چک پرداختنی: بدهی = ۳۹،۵۰۰،۰۰۰", party_balance(sup) == 39_500_000,
      f"({party_balance(sup):,})")
check("ثبت چک پرداختنی: اسناد پرداختنی = ۱۰،۰۰۰،۰۰۰",
      -balance(repo.A_NOTES_PAYABLE) == 10_000_000, f"({-balance(repo.A_NOTES_PAYABLE):,})")

repo.clear_cheque(con, paid_ch, "bank")
check("پرداخت چک: اسناد پرداختنی صفر شد", -balance(repo.A_NOTES_PAYABLE) == 0)
check("پرداخت چک: موجودی بانک = ۵،۰۰۰،۰۰۰ − ۱۰،۰۰۰،۰۰۰", balance(repo.A_BANK) == -5_000_000,
      f"({balance(repo.A_BANK):,})")
check("تراز آزمایشی پس از پرداخت چک", trial_ok())

# ---------------------------------------------------------------------------
print("\n── ۴) قفل دوره مالی ──")
jd = jalali.to_jalali_str(today)
month = int(jd.split("/")[1])
fy = db.current_fiscal_year(con, today)
repo.set_period_lock(con, fy["id"], month, True)
check("قفل شدن ماه جاری", repo.period_locked(con, fy["id"], month))
try:
    repo.add_payment(con, "receipt", cust, 1_000_000, today, "cash")
    check("جلوگیری از ثبت سند در دورهٔ قفل‌شده", False)
except repo.AccountingError as e:
    check("جلوگیری از ثبت سند در دورهٔ قفل‌شده", True, f"({e})")
repo.set_period_lock(con, fy["id"], month, False)
check("باز شدن دوره", not repo.period_locked(con, fy["id"], month))
repo.add_payment(con, "receipt", cust, 1_000_000, today, "cash")
check("ثبت سند پس از باز شدن دوره", balance(repo.A_CASH) == 1_000_000,
      f"({balance(repo.A_CASH):,})")

# ---------------------------------------------------------------------------
print("\n── ۵) سنوات بدهی (Aging) ──")
old_cust = repo.save_party(con, None, {"name": "مشتری معوق", "kind": "customer"})
# فاکتوری با سررسیدِ ۴۵ روز پیش (معوق)
service_item = repo.save_item(con, None, {"name": "خدمت مشاوره", "unit": "ساعت", "sale_price": 5_000_000,
                                          "vat_rate": 10, "track_stock": False})
old_inv = repo.save_invoice(
    con, None,
    {"kind": "sale", "party_id": old_cust,
     "gregorian_date": (date.today() - timedelta(days=75)).isoformat(),
     "gregorian_due_date": (date.today() - timedelta(days=45)).isoformat()},
    [{"item_id": service_item, "qty": 1, "unit_price": 5_000_000, "discount": 0, "vat_rate": 10,
      **{k: v for k, v in repo.calc_line(1, 5_000_000, 0, 10).items()
         if k in ("net", "vat")}}])
repo.confirm_invoice(con, old_inv)
aging = repo.report_aging(con, "customer")
row = [r for r in aging["rows"] if r["party_id"] == old_cust]
check("مشتری معوق در گزارش سنوات ظاهر شد", len(row) == 1)
if row:
    check("مبلغ در بازهٔ ۳۱ تا ۶۰ روز قرار گرفت", row[0]["d31_60"] == 5_500_000,
          f"({row[0]['d31_60']:,} ریال — ۵،۰۰۰،۰۰۰ + ۱۰٪ مالیات)")
check("جمع بازه‌های گزارش محاسبه شد", sum(aging["buckets"].values()) == aging["total"])

# ---------------------------------------------------------------------------
print("\n── ۶) پشتیبان خودکار ──")
db.set_setting(con, "auto_backup", "1")
db.set_setting(con, "backup_keep", "3")
for i in range(6):
    db.make_backup(con, "test")
kept = [f for f in os.listdir(db.backup_dir()) if f.endswith(".db")]
db.auto_backup(con)
kept = [f for f in os.listdir(db.backup_dir()) if f.endswith(".db")]
check("محدود کردن تعداد نسخه‌های پشتیبان به ۳", len(kept) == 3, f"({len(kept)} نسخه باقی‌مانده)")
db.set_setting(con, "auto_backup", "0")
check("غیرفعال‌سازی پشتیبان خودکار", db.auto_backup(con) is None)

# ---------------------------------------------------------------------------
print("\n── ۷) خلاصهٔ چک‌ها برای داشبورد ──")
repo.add_cheque(con, "received", cust, "1004", 2_000_000, today, next_week)   # در جریان وصول
repo.add_cheque(con, "paid", sup, "2002", 3_000_000, (date.today() - timedelta(days=10)).isoformat(),
                (date.today() - timedelta(days=3)).isoformat())               # سررسید گذشته
summ = repo.cheques_summary(con)
check("چکِ سررسید گذشته شناسایی شد", summ["overdue"] >= 1, f"({summ['overdue']} مورد)")
check("خلاصهٔ چک‌ها شامل چک‌های در جریان است",
      summ["received_count"] + summ["paid_count"] >= 1,
      f"(دریافتنی: {summ['received_count']} | پرداختنی: {summ['paid_count']})")

print("\n" + "=" * 70)
print(f"نتیجه: {passed} موفق / {failed} ناموفق")
print("=" * 70)
sys.exit(1 if failed else 0)
