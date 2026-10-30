# -*- coding: utf-8 -*-
"""
تست سناریوی کاملِ کسب‌وکار (بدون رابط کاربری)
اجرا:  python tests/test_logic.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TMP = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["ACC_DB_PATH"] = TMP
os.environ["ACC_DATA_DIR"] = os.path.dirname(TMP)

import db          # noqa: E402
import jalali      # noqa: E402
import repo        # noqa: E402

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


def tb_balanced():
    t = repo.report_trial_balance(con)
    return t["balanced"], t["total_debit"], t["total_credit"]


print("=" * 70)
print("سناریو: خرید کالا → فروش → دریافت وجه → برگشت → ابطال")
print("=" * 70)

# --- ۱) تعریف مشتری و تامین‌کننده -------------------------------------------
cust = repo.save_party(con, None, {"name": "شرکت آریا", "kind": "customer",
                                   "phone": "09120000000", "opening_balance": 0})
sup = repo.save_party(con, None, {"name": "تامین‌کننده پارس", "kind": "supplier"})
check("ایجاد مشتری و تامین‌کننده", cust > 0 and sup > 0, f"(مشتری #{cust})")

# --- ۲) تعریف کالا ----------------------------------------------------------
item = repo.save_item(con, None, {"name": "کالای آ", "unit": "عدد",
                                  "sale_price": 1_500_000, "purchase_price": 1_000_000,
                                  "vat_rate": 10, "track_stock": True, "stock_min": 2})
srv = repo.save_item(con, None, {"name": "خدمت نصب", "unit": "ساعت",
                                 "sale_price": 2_000_000, "purchase_price": 0,
                                 "vat_rate": 10, "track_stock": False})
check("ایجاد کالا و خدمت", item > 0 and srv > 0)

# --- ۳) خرید ۱۰ عدد کالا، هر عدد ۱،۰۰۰،۰۰۰ ریال + ۱۰٪ مالیات ---------------
lines = [{"item_id": item, "qty": 10, "unit_price": 1_000_000, "discount": 0,
          "vat_rate": 10, **{k: v for k, v in repo.calc_line(10, 1_000_000, 0, 10).items()
                             if k in ("net", "vat")}}]
pur = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                    "gregorian_date": "2026-09-01", "discount": 0}, lines)
repo.confirm_invoice(con, pur)
qty, cost = repo.stock_state(con, item)
check("موجودی پس از خرید = ۱۰", qty == 10, f"(موجودی: {qty})")
check("بهای تمام‌شده = ۱،۰۰۰،۰۰۰ ریال", cost == 1_000_000, f"({cost:,})")
inv = con.execute("SELECT * FROM invoices WHERE id=?", (pur,)).fetchone()
check("جمع فاکتور خرید = ۱۱،۰۰۰،۰۰۰", inv["total"] == 11_000_000, f"({inv['total']:,})")
check("تراز آزمایشی پس از خرید", tb_balanced()[0], f"{tb_balanced()[1]:,}")

# --- ۴) خرید دوم با قیمت بالاتر (تست میانگین موزون) -------------------------
lines2 = [{"item_id": item, "qty": 10, "unit_price": 1_200_000, "discount": 0,
           "vat_rate": 10, **{k: v for k, v in repo.calc_line(10, 1_200_000, 0, 10).items()
                              if k in ("net", "vat")}}]
pur2 = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                     "gregorian_date": "2026-09-05", "discount": 0}, lines2)
repo.confirm_invoice(con, pur2)
qty, cost = repo.stock_state(con, item)
check("موجودی پس از خرید دوم = ۲۰", qty == 20)
check("میانگین موزون = ۱،۱۰۰،۰۰۰ ریال", cost == 1_100_000, f"({cost:,}) ← (۱۰×۱،۰۰۰،۰۰۰ + ۱۰×۱،۲۰۰،۰۰۰)/۲۰")

# --- ۵) فروش ۵ عدد، هر عدد ۱،۵۰۰،۰۰۰ ریال + ۱۰٪ مالیات --------------------
sale_lines = [{"item_id": item, "qty": 5, "unit_price": 1_500_000, "discount": 0,
               "vat_rate": 10, **{k: v for k, v in repo.calc_line(5, 1_500_000, 0, 10).items()
                                  if k in ("net", "vat")}},
              {"item_id": srv, "qty": 1, "unit_price": 2_000_000, "discount": 0,
               "vat_rate": 10, **{k: v for k, v in repo.calc_line(1, 2_000_000, 0, 10).items()
                                  if k in ("net", "vat")}}]
sale = repo.save_invoice(con, None, {"kind": "sale", "party_id": cust,
                                     "gregorian_date": "2026-09-10", "discount": 100_000}, sale_lines)
repo.confirm_invoice(con, sale)
sinv = con.execute("SELECT * FROM invoices WHERE id=?", (sale,)).fetchone()
# خالص فروش: (۵×۱،۵۰۰،۰۰۰) + (۱×۲،۰۰۰،۰۰۰) = ۹،۵۰۰،۰۰۰ − تخفیف ۱۰۰،۰۰۰ = ۹،۴۰۰،۰۰۰
# مالیات: ۱۰٪ (۷،۵۰۰،۰۰۰ + ۲،۰۰۰،۰۰۰) = ۹۵۰،۰۰۰ → کل = ۱۰،۳۵۰،۰۰۰
check("خالص فاکتور فروش = ۹،۴۰۰،۰۰۰", sinv["subtotal"] - sinv["discount"] == 9_400_000,
      f"({sinv['subtotal']:,} - {sinv['discount']:,})")
check("مالیات فروش = ۹۵۰،۰۰۰", sinv["vat_amount"] == 950_000, f"({sinv['vat_amount']:,})")
check("جمع فاکتور فروش = ۱۰،۳۵۰،۰۰۰", sinv["total"] == 10_350_000, f"({sinv['total']:,})")
qty, cost = repo.stock_state(con, item)
check("موجودی پس از فروش = ۱۵", qty == 15, f"({qty})")

# بهای تمام‌شدهٔ فروش: فقط کالا (خدمت انبار نمی‌شود): ۵ × ۱،۱۰۰،۰۰۰ = ۵،۵۰۰،۰۰۰
cogs = con.execute(
    "SELECT SUM(qty * -unit_cost) c FROM stock_moves WHERE move_type='sale' AND item_id=?", (item,)
).fetchone()["c"]
check("بهای تمام‌شدهٔ فروش = ۵،۵۰۰،۰۰۰", cogs == 5_500_000, f"({cogs:,})")
check("تراز آزمایشی پس از فروش", tb_balanced()[0], f"{tb_balanced()[1]:,}")

# --- ۶) ماندهٔ مشتری ---------------------------------------------------------
bal = con.execute("SELECT balance FROM v_party_balance WHERE party_id=?", (cust,)).fetchone()["balance"]
check("ماندهٔ مشتری = ۱۰،۳۵۰،۰۰۰", bal == 10_350_000, f"({bal:,})")

# --- ۷) دریافت ۵،۰۰۰،۰۰۰ ریال -----------------------------------------------
repo.add_payment(con, "receipt", cust, 5_000_000, "2026-09-12", "cash", sale)
bal = con.execute("SELECT balance FROM v_party_balance WHERE party_id=?", (cust,)).fetchone()["balance"]
check("ماندهٔ مشتری پس از دریافت = ۵،۳۵۰،۰۰۰", bal == 5_350_000, f"({bal:,})")
cash = con.execute(
    """SELECT COALESCE(SUM(debit-credit),0) v FROM journal_lines l
       JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
       WHERE a.code='10101' AND e.status='posted'"""
).fetchone()["v"]
check("موجودی صندوق = ۵،۰۰۰،۰۰۰", cash == 5_000_000, f"({cash:,})")
check("تراز آزمایشی پس از دریافت", tb_balanced()[0])

# --- ۸) گزارش سود و زیان -----------------------------------------------------
pl = repo.report_profit_loss(con, "2026-01-01", "2026-12-31")
check("درآمد خالص = ۹،۴۰۰،۰۰۰", pl["revenue"] == 9_400_000, f"({pl['revenue']:,})")
check("بهای تمام‌شده = ۵،۵۰۰،۰۰۰", pl["cogs"] == 5_500_000, f"({pl['cogs']:,})")
check("سود ناخالص = ۳،۹۰۰،۰۰۰", pl["gross_profit"] == 3_900_000, f"({pl['gross_profit']:,})")

# --- ۹) برگشت از فروش (۲ عدد) ------------------------------------------------
ret_lines = [{"item_id": item, "qty": 2, "unit_price": 1_500_000, "discount": 0,
              "vat_rate": 10, **{k: v for k, v in repo.calc_line(2, 1_500_000, 0, 10).items()
                                 if k in ("net", "vat")}}]
ret = repo.save_invoice(con, None, {"kind": "sale_return", "party_id": cust,
                                    "gregorian_date": "2026-09-15", "discount": 0}, ret_lines)
repo.confirm_invoice(con, ret)
qty, _ = repo.stock_state(con, item)
check("موجودی پس از برگشت = ۱۷", qty == 17, f"({qty}) ← ۱۵ + ۲ برگشتی")
bal = con.execute("SELECT balance FROM v_party_balance WHERE party_id=?", (cust,)).fetchone()["balance"]
check("ماندهٔ مشتری پس از برگشت = ۲،۰۵۰،۰۰۰", bal == 2_050_000, f"({bal:,}) ← ۵،۳۵۰،۰۰۰ - ۳،۳۰۰،۰۰۰")
check("تراز آزمایشی پس از برگشت", tb_balanced()[0])

# --- ۱۰) قوانین سخت‌گیرانه ---------------------------------------------------
print("\n--- تست قوانین پایگاه داده ---")
try:
    repo.post_entry(con, "2026-09-20", "general",
                    [(repo.A_CASH, 1000, 0, None), (repo.A_SALES, 0, 500, None)])
    check("رد کردن سند نامتوازن", False)
except Exception as e:
    check("رد کردن سند نامتوازن", "تراز نیست" in str(e), f"({e})")

try:
    repo.save_invoice(con, sale, {"kind": "sale", "party_id": cust,
                                  "gregorian_date": "2026-09-10"}, sale_lines)
    check("رد ویرایش فاکتور قطعی‌شده", False)
except repo.AccountingError as e:
    check("رد ویرایش فاکتور قطعی‌شده", True, f"({e})")

try:
    repo.delete_party(con, cust)
    check("رد حذف مشتریِ دارای سند", False)
except repo.AccountingError as e:
    check("رد حذف مشتریِ دارای سند", True)

# --- ۱۱) ابطال فاکتور فروش ---------------------------------------------------
repo.cancel_payment(con, 1, "اشتباه در ثبت")
repo.cancel_invoice(con, sale, "اشتباه در صدور")
cancelled = con.execute("SELECT status FROM invoices WHERE id=?", (sale,)).fetchone()["status"]
check("وضعیت فاکتور = ابطال‌شده", cancelled == "cancelled")
qty, _ = repo.stock_state(con, item)
check("موجودی پس از ابطال = ۲۲", qty == 22, f"({qty}) ← ۱۷ + ۵ کالایِ فاکتورِ ابطالی")
bal = con.execute("SELECT balance FROM v_party_balance WHERE party_id=?", (cust,)).fetchone()["balance"]
check("ماندهٔ مشتری پس از ابطال = ۳،۳۰۰،۰۰۰- (بستانکار)", bal == -3_300_000,
      f"({bal:,}) ← فقط اثرِ برگشت از فروش باقی مانده است")
ok, d, c = tb_balanced()
check("تراز آزمایشی پس از ابطال", ok, f"بدهکار {d:,} / بستانکار {c:,}")

# --- ۱۲) گزارشات --------------------------------------------------------------
print("\n--- گزارش‌ها ---")
st = repo.report_stock(con)
check("ارزش موجودی انبار = ۲۴،۲۰۰،۰۰۰", st["total_value"] == 24_200_000,
      f"({st['total_value']:,} ← ۲۲ × ۱،۱۰۰،۰۰۰)")
custs = repo.report_customers(con, "customer")
check("گزارش مشتریان تولید شد", len(custs["rows"]) >= 1)
sups = repo.report_customers(con, "supplier")
check("ماندهٔ تامین‌کننده = ۲۴،۲۰۰،۰۰۰", int(sups["total"]) == 24_200_000,
      f"({sups['total']:,} ← ۱۱،۰۰۰،۰۰۰ + ۱۳،۲۰۰،۰۰۰)")
led = repo.report_ledger(con, "10101")
check("دفتر صندوق تولید شد", len(led) >= 2, f"({len(led)} ردیف)")

# --- ۱۳) تقویم ---------------------------------------------------------------
check("تاریخ شمسی فاکتورها", con.execute(
    "SELECT jalali_date FROM invoices WHERE id=?", (sale,)).fetchone()["jalali_date"] == "1405/06/19",
    f"({con.execute('SELECT jalali_date FROM invoices WHERE id=?', (sale,)).fetchone()['jalali_date']})")

print("\n" + "=" * 70)
print(f"نتیجه: {passed} موفق / {failed} ناموفق")
print("=" * 70)
sys.exit(1 if failed else 0)
