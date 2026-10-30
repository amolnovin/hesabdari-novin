# -*- coding: utf-8 -*-
"""
مرحله ۳) لایه دسترسی به داده
=============================
تمام ارتباط با پایگاه داده از این ماژول عبور می‌کند تا بعداً بتوان
موتور پایگاه داده را عوض کرد بدون آنکه رابط کاربری تغییر کند.

نکتهٔ مهم: فایل داده در پوشهٔ کاربر ذخیره می‌شود (٪APPDATA٪ در ویندوز)،
نه کنار فایل اجرایی — چون در Program Files معمولاً اجازهٔ نوشتن ندارید.
"""

import os
import sqlite3
import sys
from contextlib import contextmanager
from datetime import date

import jalali

APP_NAME = "SmallBizAccounting"
DB_FILE_NAME = "accounting.db"


def _resource_path(name: str) -> str:
    """مسیر فایل‌های همراه برنامه — سازگار با حالت عادی و اجرای فریزشده (PyInstaller)"""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def schema_file() -> str:
    return _resource_path("schema.sql")


def schema_sql() -> str:
    """
    متنِ کاملِ شِما.
    ابتدا از فایل schema.sql خوانده می‌شود؛ اگر در نسخه‌ی بسته‌بندی‌شده
    این فایل در دسترس نبود، از نسخه‌ی جاسازی‌شده استفاده می‌گردد
    (این اتفاق یکی از خطاهای رایجِ اجرای exe است).
    """
    path = schema_file()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    try:
        from schema_embedded import SCHEMA_SQL
        return SCHEMA_SQL
    except Exception:
        raise FileNotFoundError(
            f"فایل schema.sql پیدا نشد:\n{path}\n"
            "اگر برنامه را از سورس اجرا می‌کنید، مطمئن شوید فایل در کنار main.py است."
        )


# ---------------------------------------------------------------------------
# مسیر داده
# ---------------------------------------------------------------------------
def data_dir() -> str:
    """
    پوشهٔ دادهٔ برنامه (Writable)

    متغیر محیطی ACC_DATA_DIR در صورت نیاز مسیر را کاملاً تعیین می‌کند؛
    این قابلیت برای اجرای تست‌ها (تا کنار دادهٔ واقعی چیزی ننویسند)
    و برای نسخهٔ پرتابل (ذخیره در کنار برنامه) به کار می‌رود.
    """
    override = os.environ.get("ACC_DATA_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    return path


def db_path() -> str:
    return os.environ.get("ACC_DB_PATH") or os.path.join(data_dir(), DB_FILE_NAME)


def backup_dir() -> str:
    path = os.path.join(data_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


# ---------------------------------------------------------------------------
# اتصال
# ---------------------------------------------------------------------------
def connect(path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or db_path(), isolation_level=None)  # کنترل دستی تراکنش‌ها
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    return con


# ---------------------------------------------------------------------------
# تراکنش اتمی (قابل تودرتو بودن)
# ---------------------------------------------------------------------------
_tx_depth = {"n": 0}


@contextmanager
def tx(con: sqlite3.Connection):
    """
    یک بلوک تراکنشِ اتمی: یا همه‌چیز ذخیره می‌شود یا هیچ‌چیز.

    از SAVEPOINT استفاده شده تا بتوان آن را تودرتو فراخوانی کرد
    (مثلاً «قطعی کردن فاکتور» که خودش چند ثبت سند و حرکت انبار دارد).
    """
    _tx_depth["n"] += 1
    name = f"sp_{_tx_depth['n']}"
    con.execute(f"SAVEPOINT {name}")
    try:
        yield con
        con.execute(f"RELEASE {name}")
    except Exception:
        con.execute(f"ROLLBACK TO {name}")
        con.execute(f"RELEASE {name}")
        raise
    finally:
        _tx_depth["n"] -= 1


def init_db(con: sqlite3.Connection) -> None:
    """اجرای شِما و آماده‌سازی داده‌های پایه"""
    con.executescript(schema_sql())
    _ensure_fiscal_years(con)
    con.commit()


def _ensure_fiscal_years(con: sqlite3.Connection) -> None:
    """ساخت خودکار سال مالیِ جاری و سال بعد (اگر وجود نداشته باشد)"""
    today = date.today()
    jy = jalali.gregorian_to_jalali(today.year, today.month, today.day)[0]
    for year in (jy - 1, jy, jy + 1):
        start = jalali.start_of_jalali_year(year)
        end = jalali.end_of_jalali_year(year)
        con.execute(
            "INSERT OR IGNORE INTO fiscal_year (title, start_date, end_date) VALUES (?,?,?)",
            (f"سال مالی {year}", start, end),
        )


def current_fiscal_year(con: sqlite3.Connection, gdate: str | None = None) -> sqlite3.Row:
    """سال مالی متناظر با یک تاریخ میلادی (پیش‌فرض: امروز)"""
    gdate = gdate or date.today().isoformat()
    row = con.execute(
        "SELECT * FROM fiscal_year WHERE ? BETWEEN start_date AND end_date ORDER BY start_date LIMIT 1",
        (gdate,),
    ).fetchone()
    if row:
        return row
    return con.execute("SELECT * FROM fiscal_year ORDER BY start_date DESC LIMIT 1").fetchone()


# ---------------------------------------------------------------------------
# تنظیمات
# ---------------------------------------------------------------------------
def get_setting(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(con, key: str, value: str) -> None:
    con.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


# ---------------------------------------------------------------------------
# شماره‌گذاری خودکار (بدون تداخل و بدون شمارهٔ تکراری)
# ---------------------------------------------------------------------------
def next_no(con, name: str, year: str = "") -> int:
    con.execute(
        "INSERT INTO sequences (name, year, last_value) VALUES (?, ?, 0) "
        "ON CONFLICT(name, year) DO NOTHING",
        (name, year),
    )
    con.execute("UPDATE sequences SET last_value = last_value + 1 WHERE name = ? AND year = ?",
                (name, year))
    return con.execute("SELECT last_value FROM sequences WHERE name = ? AND year = ?",
                       (name, year)).fetchone()["last_value"]


# ---------------------------------------------------------------------------
# لاگ حسابرسی
# ---------------------------------------------------------------------------
def audit(con, action: str, table_name: str = "", record_id: int | None = None, detail: str = "") -> None:
    con.execute(
        "INSERT INTO audit_log (action, table_name, record_id, detail) VALUES (?,?,?,?)",
        (action, table_name, record_id, detail),
    )


# ---------------------------------------------------------------------------
# پشتیبان‌گیری
# ---------------------------------------------------------------------------
def prune_backups(keep: int = 10) -> list[str]:
    """حذف نسخه‌های قدیمی پشتیبان و نگهداری N نسخهٔ آخر"""
    import glob

    files = sorted(glob.glob(os.path.join(backup_dir(), "backup-*.db")),
                   key=os.path.getmtime, reverse=True)
    removed = []
    for f in files[keep:]:
        try:
            os.remove(f)
            removed.append(f)
        except OSError:
            pass
    return removed


def auto_backup(con: sqlite3.Connection, label: str = "auto") -> str | None:
    """پشتیبان خودکار (در صورت فعال بودن در تنظیمات) + حذف نسخه‌های قدیمی"""
    if get_setting(con, "auto_backup", "1") != "1":
        return None
    try:
        keep = int(get_setting(con, "backup_keep", "10") or 10)
        path = make_backup(con, label)
        prune_backups(max(1, keep))
        return path
    except Exception:
        return None


def make_backup(con: sqlite3.Connection, label: str = "manual") -> str:
    """یک کپی سالم از پایگاه داده — با VACUUM INTO که نسخهٔ سازگار و فشرده می‌سازد"""
    import shutil
    from datetime import datetime

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = os.path.join(backup_dir(), f"backup-{stamp}-{label}.db").replace("\\", "/")

    # نام فایل فقط تا دقتِ «ثانیه» است؛ اگر در همان ثانیه پشتیبانِ دیگری
    # گرفته شود، نباید نسخهٔ قبلی بازنویسی شود (وگرنه عملاً از دست می‌رود).
    base, counter = target[:-3], 1
    while os.path.exists(target):
        counter += 1
        target = f"{base}-{counter}.db"

    try:
        con.execute("VACUUM INTO ?", (target,))
    except sqlite3.Error:
        con.execute("PRAGMA wal_checkpoint(FULL)")
        shutil.copy2(db_path(), target)
    return target
