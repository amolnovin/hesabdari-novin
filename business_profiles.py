# -*- coding: utf-8 -*-
"""پروفایل‌های ۲۰گانهٔ کسب‌وکارهای رایج ایران.

هر پروفایل فقط «پیش‌فرض و چیدمان» را تعیین می‌کند؛ هستهٔ حسابداری دوطرفه
برای همه یکسان است. کاربر می‌تواند بعداً در تنظیمات هر گزینه را تغییر دهد.
"""

from __future__ import annotations

import json

import db

MODULES = (
    "parties",
    "items",
    "stock",
    "invoices",
    "payments",
    "cheques",
    "reports",
    "woo",
)

PROFILES: dict[str, dict] = {
    "supermarket": {
        "title": "سوپرمارکت / خواربارفروشی",
        "description": "فروش سریع کالاهای تندمصرف، بارکد، تاریخ انقضا و موجودی زیاد.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "expiry", "weight"],
        "kpis": ["sales", "profit", "stock", "cash", "receivable", "low_stock"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "برای کالاهای تاریخ‌دار، گزارش انقضا را در فاز بعدی اضافه کنید.",
    },
    "clothing": {
        "title": "پوشاک / کیف و کفش",
        "description": "تنوع سایز و رنگ، فصلی بودن فروش و مرجوعی بالا.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "variant", "season"],
        "kpis": ["sales", "profit", "stock", "returns", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "در ووکامرس از محصول variable استفاده کنید؛ هر variation یک کالا-sync می‌شود.",
    },
    "cosmetics": {
        "title": "آرایشی و بهداشتی",
        "description": "برند، تاریخ انقضا، اصالت کالا و فروش آنلاین.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "expiry", "brand"],
        "kpis": ["sales", "profit", "stock", "expiry", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "کد بهداشتی/اصالت را در شرح یا فیلد سفارشی کالا نگه دارید.",
    },
    "mobile": {
        "title": "موبایل و لوازم جانبی",
        "description": "کالای گران‌قیمت، سریال/IMEI، گارانتی و نوسان قیمت.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "serial", "warranty"],
        "kpis": ["sales", "profit", "stock", "cash", "payable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "برای گوشی، سریال/IMEI را در شرح ردیف فاکتور ثبت کنید.",
    },
    "home_appliances": {
        "title": "لوازم خانگی و صوتی‌تصویری",
        "description": "فروش اقساطی/چکی، گارانتی، حمل و نصب.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "دستگاه",
        "item_fields": ["serial", "warranty", "brand"],
        "kpis": ["sales", "receivable", "cheques_in", "stock", "profit"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "هزینه حمل/نصب را به‌صورت ردیف خدماتی در فاکتور اضافه کنید.",
    },
    "auto_parts": {
        "title": "قطعات خودرو و لوازم یدکی",
        "description": "کد فنی، شماره OEM، سازگاری با مدل خودرو و مرجوعی.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "oem", "brand"],
        "kpis": ["sales", "stock", "profit", "payable", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "کد فنی/OEM را در کد کالا یا SKU ووکامرس قرار دهید.",
    },
    "hardware": {
        "title": "ابزار، یراق و رنگ",
        "description": "فروش عددی/وزنی/متری، مشتری فنی و عمده.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "weight", "brand"],
        "kpis": ["sales", "stock", "profit", "receivable", "payable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "برای فروش وزنی/متری، واحد کالا را دقیق تعریف کنید.",
    },
    "building_materials": {
        "title": "مصالح ساختمانی",
        "description": "فروش حجیم، تن/متر/کیسه، حمل و تسویه چکی.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "کیسه",
        "item_fields": ["weight", "brand"],
        "kpis": ["sales", "receivable", "cheques_in", "stock", "payable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": False,
        },
        "note": "برای فله، موجودی را با واحد پایه (کیلوگرم/تن) نگه دارید.",
    },
    "bookstore_stationery": {
        "title": "کتاب و لوازم‌التحریر",
        "description": "شابک/ISBN، تنوع زیاد، فروش فصلی مدارس.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "isbn", "brand"],
        "kpis": ["sales", "stock", "profit", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "کتاب ممکن است معاف از ارزش افزوده باشد؛ نرخ را با حوزه مالیاتی چک کنید.",
    },
    "jewelry_gold": {
        "title": "طلا، جواهر و ساعت",
        "description": "قیمت روز، وزن/عیار، اجرت و مالیات خاص؛ نیازمند دقت بالا.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "گرم",
        "item_fields": ["weight", "serial", "brand"],
        "kpis": ["sales", "stock", "cash", "profit", "payable"],
        "woo": {
            "sync_products": False,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": False,
        },
        "note": "هشدار: محاسبه اجرت/عیار/مالیات طلا تخصصی است و باید قبل از استفاده رسمی بازبینی شود.",
    },
    "furniture": {
        "title": "مبلمان و دکوراسیون",
        "description": "سفارشی‌سازی، پیش‌دریافت، حمل و نصب، زمان تحویل.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["variant", "brand"],
        "kpis": ["sales", "receivable", "cheques_in", "profit", "stock"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "پیش‌دریافت را به‌صورت دریافت وجه بدون تسویه فاکتور ثبت کنید.",
    },
    "carpet_handicrafts": {
        "title": "فرش و صنایع دستی",
        "description": "کالای نفیس، شناسنامه، ابعاد/رج‌شمار و فروش امانی.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["serial", "weight", "variant"],
        "kpis": ["sales", "stock", "profit", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "شناسنامه/ابعاد را در شرح کالا ثبت کنید.",
    },
    "florist": {
        "title": "گل و گیاه",
        "description": "کالای فاسدشدنی، مناسبتی، سفارش سریع و ارسال محلی.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "شاخه",
        "item_fields": ["expiry", "variant"],
        "kpis": ["sales", "stock", "profit", "cash", "waste"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "ضایعات را با اصلاح موجودی و حساب تعدیلات انبار ثبت کنید.",
    },
    "pet_shop": {
        "title": "پت‌شاپ و لوازم حیوانات",
        "description": "غذا/لوازم، تاریخ انقضا، برند و مشتری تکرارشونده.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "expiry", "brand"],
        "kpis": ["sales", "stock", "profit", "receivable"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "برای غذای حیوانات، تاریخ انقضا را کنترل کنید.",
    },
    "restaurant_cafe": {
        "title": "رستوران / کافه / فست‌فود",
        "description": "فروش سریع، مواد اولیه، ضایعات و سفارش آنلاین.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "پرس",
        "item_fields": ["expiry", "weight"],
        "kpis": ["sales", "profit", "stock", "cash", "waste"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "برای تولید غذا، فعلاً مواد اولیه را با اصلاح موجودی مصرف کنید؛ BOM در فاز بعدی.",
    },
    "bakery_confectionery": {
        "title": "نانوایی / شیرینی و شکلات",
        "description": "تولید روزانه، وزن/عدد، ضایعات و سفارش مناسبتی.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "کیلوگرم",
        "item_fields": ["expiry", "weight"],
        "kpis": ["sales", "profit", "stock", "cash", "waste"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "تولید را فعلاً با ورود کالا و مصرف مواد ثبت کنید.",
    },
    "repair_services": {
        "title": "تعمیرگاه / خدمات فنی",
        "description": "اجرت، قطعات مصرفی، گارانتی تعمیر و مشتری تکراری.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "خدمت",
        "item_fields": ["serial", "warranty"],
        "kpis": ["sales", "profit", "receivable", "cash", "stock"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": False,
        },
        "note": "اجرت را کالای غیرانباری و قطعه را کالای انباری تعریف کنید.",
    },
    "wholesale_distribution": {
        "title": "عمده‌فروشی / پخش",
        "description": "فاکتورهای بزرگ، چک، سقف اعتبار، تخفیف حجمی و ویزیتور.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "rial",
        "track_stock": True,
        "unit": "کارتن",
        "item_fields": ["barcode", "weight"],
        "kpis": ["sales", "receivable", "cheques_in", "payable", "stock", "profit"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "سقف اعتبار مشتری و سنوات بدهی را روزانه کنترل کنید.",
    },
    "manufacturing_workshop": {
        "title": "تولیدی / کارگاه کوچک",
        "description": "خرید مواد، تولید محصول، ضایعات و بهای تمام‌شده ساده.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "cheques",
            "reports",
        ],
        "vat": None,
        "money_unit": "rial",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["weight", "brand"],
        "kpis": ["sales", "stock", "profit", "payable", "cash"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "BOM/مراکز هزینه در فاز بعدی؛ فعلاً تولید با اصلاح موجودی و سند تعدیل ثبت می‌شود.",
    },
    "online_digital": {
        "title": "فروشگاه اینترنتی / کالای دیجیتال",
        "description": "سفارش آنلاین، پرداخت درگاه، ارسال و مرجوعی؛ ووکامرس محور اصلی است.",
        "modules": [
            "parties",
            "items",
            "stock",
            "invoices",
            "payments",
            "reports",
            "woo",
        ],
        "vat": None,
        "money_unit": "toman",
        "track_stock": True,
        "unit": "عدد",
        "item_fields": ["barcode", "serial", "warranty"],
        "kpis": ["sales", "profit", "stock", "cash", "receivable", "woo_orders"],
        "woo": {
            "sync_products": True,
            "sync_orders": True,
            "sync_customers": True,
            "sync_stock": True,
        },
        "note": "همگام‌سازی ووکامرس را فعال و فاصله sync را کوتاه کنید.",
    },
}

DEFAULT_PROFILE = "online_digital"


def list_profiles() -> list[tuple[str, str, str]]:
    return [(k, v["title"], v["description"]) for k, v in PROFILES.items()]


def get_profile(key: str) -> dict:
    return PROFILES.get(key or DEFAULT_PROFILE, PROFILES[DEFAULT_PROFILE])


def current_key(con) -> str:
    return db.get_setting(con, "business_profile", DEFAULT_PROFILE)


def current(con) -> dict:
    return get_profile(current_key(con))


def module_enabled(con, module: str) -> bool:
    raw = db.get_setting(con, "enabled_modules", "")
    if raw:
        try:
            return module in json.loads(raw)
        except Exception:
            pass
    return module in current(con)["modules"]


def apply_profile(con, key: str, *, overwrite: bool = False) -> dict:
    p = get_profile(key)
    with db.tx(con):
        db.set_setting(con, "business_profile", key, require_permission=False)
        db.set_setting(
            con, "enabled_modules", json.dumps(p["modules"]), require_permission=False
        )
        db.set_setting(
            con, "business_profile_note", p["note"], require_permission=False
        )
        if overwrite or not db.get_setting(con, "money_unit", ""):
            db.set_setting(con, "money_unit", p["money_unit"], require_permission=False)
        # VAT is intentionally not guessed from the business type: exemptions and rates vary
        # by product, activity and current Iranian tax rules. Keep the existing configured rate.
        db.set_setting(
            con, "profile_vat_review_required", "1", require_permission=False
        )
        db.set_setting(con, "default_item_unit", p["unit"], require_permission=False)
        db.set_setting(
            con,
            "default_track_stock",
            "1" if p["track_stock"] else "0",
            require_permission=False,
        )
        db.set_setting(
            con,
            "profile_item_fields",
            json.dumps(p["item_fields"], ensure_ascii=False),
            require_permission=False,
        )
        db.set_setting(
            con, "profile_kpis", json.dumps(p["kpis"]), require_permission=False
        )
        for k, v in p["woo"].items():
            db.set_setting(con, "woo_" + k, "1" if v else "0", require_permission=False)
        db.audit(con, "apply_business_profile", "settings", None, p["title"])
    return p
