# -*- coding: utf-8 -*-
"""
ایجاد دادهٔ نمونه برای آشنایی با برنامه
اجرا:  python seed_demo.py
(داده‌های نمونه به پایگاه دادهٔ اصلی برنامه اضافه می‌شود)
"""
import os
import random
import sys

import auth
import db
import repo


def main():
    # به‌صورت پیش‌فرض دادهٔ نمونه در یک پایگاه دادهٔ جدا ساخته می‌شود،
    # مگر اینکه کاربر صریحاً --main را بدهد یا ACC_DB_PATH تنظیم کرده باشد.
    if "--main" not in sys.argv and not os.environ.get("ACC_DB_PATH"):
        os.environ["ACC_DB_PATH"] = os.path.join(db.data_dir(), "demo.db")
    with auth.service_mode():
        return _seed()


def _seed():
    con = db.connect()
    db.init_db(con)

    if con.execute("SELECT COUNT(*) c FROM parties").fetchone()["c"] > 0:
        print("پایگاه داده قبلاً دارای اطلاعات است؛ دادهٔ نمونه‌ای اضافه نشد.")
        print("اگر می‌خواهید از ابتدا شروع کنید، فایل پایگاه داده را حذف کنید.")
        return

    db.set_setting(con, "company_name", "فروشگاه نمونه")
    db.set_setting(con, "company_phone", "۰۲۱-۱۲۳۴۵۶۷۸")
    db.set_setting(con, "default_vat_rate", "10")

    customers = ["شرکت آریا", "فروشگاه البرز", "مهندس احمدی", "سارا کریمی"]
    suppliers = ["پخش پارس", "تولیدی سپیدار"]
    cust_ids = [repo.save_party(con, None, {"name": n, "kind": "customer",
                                            "phone": f"0912{random.randint(1000000,9999999)}"})
                for n in customers]
    sup_ids = [repo.save_party(con, None, {"name": n, "kind": "supplier"}) for n in suppliers]

    items = [
        ("لپ‌تاپ مدل A", "دستگاه", 45_000_000, 38_000_000, 2),
        ("مانیتور ۲۴ اینچ", "عدد", 12_000_000, 9_500_000, 5),
        ("کیبورد و ماوس", "ست", 2_500_000, 1_700_000, 10),
        ("هارد اکسترنال ۱ ترابایت", "عدد", 6_800_000, 5_200_000, 6),
    ]
    item_ids = [repo.save_item(con, None, {"name": n, "unit": u, "sale_price": s,
                                           "purchase_price": p, "vat_rate": 10,
                                           "track_stock": True, "stock_min": m})
                for n, u, s, p, m in items]
    service_id = repo.save_item(con, None, {"name": "خدمت نصب و راه‌اندازی", "unit": "ساعت",
                                            "sale_price": 3_000_000, "purchase_price": 0,
                                            "vat_rate": 10, "track_stock": False})

    def line(item_id, qty, price, vat=10.0, discount=0):
        return {"item_id": item_id, "qty": qty, "unit_price": price,
                "discount": discount, "vat_rate": vat,
                **{k: v for k, v in repo.calc_line(qty, price, discount, vat).items()
                   if k in ("net", "vat")}}

    # ورود کالا به انبار (خرید)
    purchases = [
        ("1405/06/01", sup_ids[0], [(item_ids[0], 10, 38_000_000), (item_ids[1], 20, 9_500_000)]),
        ("1405/06/05", sup_ids[1], [(item_ids[2], 50, 1_700_000), (item_ids[3], 30, 5_200_000)]),
    ]
    for jdate, sup, rows in purchases:
        g = repo.jalali.from_jalali_str(jdate)
        inv = repo.save_invoice(con, None, {"kind": "purchase", "party_id": sup,
                                            "gregorian_date": g, "discount": 0},
                                [line(i, q, p) for i, q, p in rows])
        repo.confirm_invoice(con, inv)

    # فروش
    sales = [
        ("1405/06/10", cust_ids[0], [(item_ids[0], 2, 45_000_000), (service_id, 1, 3_000_000)], 500_000),
        ("1405/06/12", cust_ids[1], [(item_ids[1], 5, 12_000_000)], 0),
        ("1405/06/15", cust_ids[2], [(item_ids[2], 10, 2_500_000), (item_ids[3], 4, 6_800_000)], 200_000),
        ("1405/06/18", cust_ids[3], [(item_ids[0], 1, 45_000_000)], 0),
    ]
    for jdate, cust, rows, disc in sales:
        g = repo.jalali.from_jalali_str(jdate)
        inv = repo.save_invoice(con, None, {"kind": "sale", "party_id": cust,
                                            "gregorian_date": g, "discount": disc},
                                [line(i, q, p) for i, q, p in rows])
        repo.confirm_invoice(con, inv)

    # دریافت وجه
    for cust, amount, jdate in [(cust_ids[0], 50_000_000, "1405/06/14"),
                                (cust_ids[1], 40_000_000, "1405/06/16")]:
        repo.add_payment(con, "receipt", cust, amount,
                         repo.jalali.from_jalali_str(jdate), "cash")

    print("✅ دادهٔ نمونه با موفقیت ایجاد شد:")
    print(f"   • {len(cust_ids)} مشتری، {len(sup_ids)} تامین‌کننده")
    print(f"   • {len(item_ids) + 1} کالا/خدمت")
    print(f"   • {len(purchases)} فاکتور خرید و {len(sales)} فاکتور فروش")
    print(f"\nمسیر پایگاه دادهٔ نمونه: {db.db_path()}")
    print("برای اجرای برنامه با دادهٔ نمونه، ACC_DB_PATH را به همین مسیر تنظیم کنید.")


if __name__ == "__main__":
    main()
