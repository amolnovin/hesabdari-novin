# -*- coding: utf-8 -*-
"""ابزارهای کمکیِ متن و عدد (نرمال‌سازی ورودی فارسی/عربی)"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import jalali

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"
_ARABIC_DIGITS = "٠١٢٣٤٥٦٧٨٩"
_LATIN_DIGITS = "0123456789"

_TRANS = str.maketrans(_PERSIAN_DIGITS + _ARABIC_DIGITS,
                       _LATIN_DIGITS + _LATIN_DIGITS)


def normalize(text: str) -> str:
    """
    نرمال‌سازی ورودی کاربر:
      * ارقام فارسی و عربی → لاتین
      * «ي» و «ك» عربی → «ی» و «ک» فارسی
      * حذف فاصله‌های نامرئی (برای جستجوی دقیق)
    """
    if text is None:
        return ""
    s = str(text).translate(_TRANS)
    s = s.replace("ي", "ی").replace("ك", "ک").replace(" ", " ").replace("‌", "")
    return s.strip()


def parse_money(text) -> int:
    """'۱،۲۰۰٬۰۰۰' یا '1,200,000' → 1200000"""
    s = normalize(text).replace(",", "").replace("٬", "").replace(" ", "")
    if s in ("", "-"):
        return 0
    try:
        return int(Decimal(s).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0


def parse_float(text) -> float:
    s = normalize(text).replace(",", "").replace("٬", "").replace(" ", "")
    if s in ("", "-"):
        return 0.0
    try:
        return float(Decimal(s))
    except Exception:
        return 0.0


def fmt(num, decimals: int = 0) -> str:
    """قالب‌بندی عدد با جداکنندهٔ هزارگان (ارقام لاتین برای مرتب‌سازی بهتر)"""
    try:
        return f"{Decimal(str(num)):,.{decimals}f}"
    except Exception:
        return "0"


def fmt_qty(num) -> str:
    return f"{float(num):,.2f}".rstrip("0").rstrip(".") if float(num) % 1 else f"{int(num):,}"


def today_j() -> str:
    return jalali.to_jalali_str(date.today().isoformat())


def today_g() -> str:
    return date.today().isoformat()


def to_persian_digits(text: str) -> str:
    """برای نمایش در چاپ و گزارش‌ها"""
    return "".join(_PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(text))


def csv_safe(text: str) -> str:
    """جلوگیری از اجرای فرمول در Excel/CSV."""
    t = str(text)
    if t.lstrip().startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + t
    return t
