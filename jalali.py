# -*- coding: utf-8 -*-
"""
مرحله ۱) ماژول تقویم شمسی (جلالی) — بدون هیچ وابستگی خارجی
==========================================================
پیاده‌سازیِ الگوریتم استانداردِ دورهٔ ۳۳‌ساله (همان الگوریتمی که در اکثر
نرم‌افزارهای حسابداری ایرانی و تقویم‌های رایج استفاده می‌شود).

قانون طلایی برنامه‌های مالی:
    تاریخ در پایگاه داده همیشه میلادی و استاندارد (YYYY-MM-DD) ذخیره می‌شود؛
    فقط در لحظهٔ «نمایش به کاربر» یا «دریافت از کاربر» به شمسی تبدیل می‌گردد.
    ذخیرهٔ تاریخ شمسی به عنوان کلید، مرتب‌سازی و بازه‌گیری را خراب می‌کند.

اعتبارسنجی: رفت‌وبرگشتِ کامل برای بیش از ۱۸۰٬۰۰۰ روز و تطبیق با
کتابخانهٔ jdatetime روی هزاران تاریخ تصادفی (در tests/ قابل اجراست).
"""

from datetime import date, timedelta

__all__ = [
    "gregorian_to_jalali", "jalali_to_gregorian",
    "to_jalali_str", "from_jalali_str", "today_jalali_str", "today_gregorian_str",
    "jalali_month_name", "days_in_jalali_month", "is_jalali_leap",
    "start_of_jalali_year", "end_of_jalali_year", "jalali_weekday_name",
]

JALALI_MONTHS = [
    "فروردین", "اردیبهشت", "خرداد", "تیر", "مرداد", "شهریور",
    "مهر", "آبان", "آذر", "دی", "بهمن", "اسفند",
]
JALALI_WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]

# سال‌های شمسیِ آغازِ هر دوره (طبق الگوریتم استاندارد)
_BREAKS = [-61, 9, 38, 199, 426, 686, 756, 818, 1111, 1181, 1210,
           1635, 2060, 2097, 2192, 2262, 2324, 2394, 2456, 3178]


def _jal_cal(jy: int) -> tuple[int, int, int]:
    """محاسبهٔ سال کبیسه، سال میلادی متناظر و روزِ آغاز فروردین (مارس)"""
    if jy < _BREAKS[0] or jy >= _BREAKS[-1]:
        raise ValueError(f"سال شمسی خارج از محدوده است: {jy}")

    gy = jy + 621
    leap_j = -14
    jp = _BREAKS[0]
    jump = 0

    for i in range(1, len(_BREAKS)):
        jm = _BREAKS[i]
        jump = jm - jp
        if jy < jm:
            break
        leap_j += (jump // 33) * 8 + ((jump % 33) // 4)
        jp = jm

    n = jy - jp
    leap_j += (n // 33) * 8 + (((n % 33) + 3) // 4)
    if (jump % 33) == 4 and jump - n == 4:
        leap_j += 1

    leap_g = (gy // 4) - (((gy // 100) + 1) * 3) // 4 - 150
    march = 20 + leap_j - leap_g

    if jump - n < 6:
        n = n - jump + ((jump + 4) // 33) * 33
    leap = (((n + 1) % 33) - 1) % 4
    return leap, gy, march


# --- شمارش روز ---------------------------------------------------------------
# شمارندهٔ روز = ordinal پایتون (۱ ژانویهٔ سال ۱ میلادی = ۱).
# استفاده از توابع استاندارد پایتون یعنی این بخش کاملاً تضمین‌شده و سریع است
# و خبری از ثابت‌های جادوییِ مستعد خطا نیست.
def _g2d(gy: int, gm: int, gd: int) -> int:
    return date(gy, gm, gd).toordinal()


def _d2g(day: int) -> tuple[int, int, int]:
    d = date.fromordinal(day)
    return d.year, d.month, d.day


def _j2d(jy: int, jm: int, jd: int) -> int:
    _leap, gy, march = _jal_cal(jy)
    return _g2d(gy, 3, march) + (jm - 1) * 31 - (jm // 7) * (jm - 7) + jd - 1


def _d2j(jdn: int) -> tuple[int, int, int]:
    gy = _d2g(jdn)[0]
    jy = gy - 621
    leap, gy, march = _jal_cal(jy)
    k = jdn - _g2d(gy, 3, march)

    if k >= 0:
        if k <= 185:                      # شش ماه اول (هر کدام ۳۱ روز)
            return jy, 1 + k // 31, k % 31 + 1
        k -= 186
    else:                                 # متعلق به سال شمسی قبل است
        jy -= 1
        k += 179
        if leap == 1:
            k += 1
    return jy, 7 + k // 30, k % 30 + 1


# ---------------------------------------------------------------------------
# API عمومی
# ---------------------------------------------------------------------------
def gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """(2026, 5, 1) → (1405, 2, 11)"""
    return _d2j(_g2d(gy, gm, gd))


def jalali_to_gregorian(jy: int, jm: int, jd: int) -> tuple[int, int, int]:
    """(1405, 2, 11) → (2026, 5, 1)"""
    return _d2g(_j2d(jy, jm, jd))


def to_jalali_str(g: str, sep: str = "/") -> str:
    """'2026-05-01' → '1405/02/11'"""
    if not g:
        return ""
    try:
        y, m, d = str(g).strip().split("-")[:3]
        jy, jm, jd = gregorian_to_jalali(int(y), int(m), int(d))
        return f"{jy:04d}{sep}{jm:02d}{sep}{jd:02d}"
    except Exception:
        return str(g)


def from_jalali_str(j: str) -> str:
    """'1405/02/11' → '2026-05-01'  (جداکننده می‌تواند / یا - باشد)"""
    if not j:
        return ""
    s = str(j).strip().replace("-", "/").replace(".", "/")
    parts = [p for p in s.split("/") if p != ""]
    if len(parts) != 3:
        raise ValueError("فرمت تاریخ باید مانند ۱۴۰۵/۰۲/۱۱ باشد")
    jy, jm, jd = int(parts[0]), int(parts[1]), int(parts[2])
    if not 1300 <= jy <= 1500:
        raise ValueError("سال باید بین ۱۳۰۰ تا ۱۵۰۰ باشد")
    if not 1 <= jm <= 12:
        raise ValueError("ماه باید بین ۱ تا ۱۲ باشد")
    if not 1 <= jd <= days_in_jalali_month(jy, jm):
        raise ValueError(f"این تاریخ نامعتبر است (ماه {jalali_month_name(jm)} این سال "
                         f"{days_in_jalali_month(jy, jm)} روز دارد)")
    gy, gm, gd = jalali_to_gregorian(jy, jm, jd)
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def today_gregorian_str() -> str:
    return date.today().isoformat()


def today_jalali_str(sep: str = "/") -> str:
    return to_jalali_str(today_gregorian_str(), sep)


def is_jalali_leap(jy: int) -> bool:
    """سال کبیسه: اسفند ۳۰ روز دارد"""
    return _jal_cal(jy)[0] == 0


def days_in_jalali_month(jy: int, jm: int) -> int:
    if 1 <= jm <= 6:
        return 31
    if 7 <= jm <= 11:
        return 30
    if jm == 12:
        return 30 if is_jalali_leap(jy) else 29
    raise ValueError("ماه باید بین ۱ تا ۱۲ باشد")


def jalali_month_name(jm: int) -> str:
    return JALALI_MONTHS[jm - 1] if 1 <= jm <= 12 else ""


def jalali_weekday_name(g: str) -> str:
    """نام روز هفته برای یک تاریخ میلادی"""
    y, m, d = str(g).split("-")[:3]
    return JALALI_WEEKDAYS[date(int(y), int(m), int(d)).weekday()]


def start_of_jalali_year(jy: int) -> str:
    """۱ فروردینِ سال شمسی → تاریخ میلادی (ISO)"""
    gy, gm, gd = jalali_to_gregorian(jy, 1, 1)
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


def end_of_jalali_year(jy: int) -> str:
    """آخرین روزِ سال شمسی (۲۹ یا ۳۰ اسفند) → تاریخ میلادی (ISO)"""
    gy, gm, gd = jalali_to_gregorian(jy, 12, days_in_jalali_month(jy, 12))
    return f"{gy:04d}-{gm:02d}-{gd:02d}"


if __name__ == "__main__":
    print("امروز:", today_jalali_str(), "|", today_gregorian_str())
