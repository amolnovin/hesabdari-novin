# -*- coding: utf-8 -*-
"""لایه دسترسی به داده، مهاجرت، تراکنش، پشتیبان‌گیری و بازیابی امن."""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import threading
from contextlib import contextmanager
from datetime import date, datetime

import jalali

APP_NAME = "SmallBizAccounting"
DB_FILE_NAME = "accounting.db"
SCHEMA_VERSION = 5
_local = threading.local()
last_backup_error: str | None = None


def _resource_path(name: str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def schema_file() -> str:
    return _resource_path("schema.sql")


def schema_sql() -> str:
    path = schema_file()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    try:
        from schema_embedded import SCHEMA_SQL
        return SCHEMA_SQL
    except Exception:
        raise FileNotFoundError(f"فایل schema.sql پیدا نشد:\n{path}")


def data_dir() -> str:
    override = os.environ.get("ACC_DATA_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        if os.name != "nt":
            try:
                os.chmod(override, 0o700)
            except OSError:
                pass
        return override
    if sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.join(os.path.expanduser("~"), "Library", "Application Support")
    else:
        base = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, APP_NAME)
    os.makedirs(path, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def db_path() -> str:
    path = os.environ.get("ACC_DB_PATH") or os.path.join(data_dir(), DB_FILE_NAME)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    return path


def backup_dir() -> str:
    path = os.path.join(data_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def connect(path: str | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(path or db_path(), isolation_level=None, timeout=30)
    con.row_factory = sqlite3.Row
    if os.name != "nt":
        try:
            db_file = con.execute("PRAGMA database_list").fetchone()[2]
            if db_file:
                os.chmod(db_file, 0o600)
        except OSError:
            pass
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA busy_timeout = 30000")
    con.execute("PRAGMA synchronous = FULL")
    return con


@contextmanager
def tx(con: sqlite3.Connection):
    depth = getattr(_local, "depth", 0)
    _local.depth = depth + 1
    name = f"sp_{id(con)}_{_local.depth}"
    con.execute(f"SAVEPOINT {name}")
    try:
        yield con
        con.execute(f"RELEASE {name}")
    except BaseException:
        con.execute(f"ROLLBACK TO {name}")
        con.execute(f"RELEASE {name}")
        raise
    finally:
        _local.depth -= 1


def init_db(con: sqlite3.Connection) -> list[str]:
    """ساخت یا مهاجرت پایگاه داده. هشدارهای مهاجرت برمی‌گردد."""
    warnings: list[str] = []
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    version = con.execute("PRAGMA user_version").fetchone()[0]
    if tables and version < SCHEMA_VERSION and "journal_entries" in tables:
        from migrations import migrate
        try:
            make_backup(con, "pre-migration", require_permission=False, write_audit=False)
        except Exception as e:
            raise RuntimeError(f"پشتیبان‌گیری پیش از مهاجرت ناموفق بود؛ مهاجرت انجام نشد: {e}") from e
        warnings = migrate(con)
    con.executescript(schema_sql())
    _ensure_fiscal_years(con)
    con.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
    con.commit()
    return warnings


def _ensure_fiscal_years(con: sqlite3.Connection) -> None:
    today = date.today()
    jy = jalali.gregorian_to_jalali(today.year, today.month, today.day)[0]
    for year in (jy - 1, jy, jy + 1):
        con.execute("INSERT OR IGNORE INTO fiscal_year (title, start_date, end_date) VALUES (?,?,?)",
                    (f"سال مالی {year}", jalali.start_of_jalali_year(year), jalali.end_of_jalali_year(year)))


def validate_gdate(gdate: str) -> str:
    try:
        d = date.fromisoformat(str(gdate))
    except Exception as e:
        raise ValueError(f"تاریخ میلادی نامعتبر است: {gdate}") from e
    jy = jalali.gregorian_to_jalali(d.year, d.month, d.day)[0]
    if not 1300 <= jy <= 1500:
        raise ValueError("تاریخ خارج از بازهٔ پشتیبانی‌شدهٔ شمسی (۱۳۰۰ تا ۱۵۰۰) است")
    return d.isoformat()


def current_fiscal_year(con: sqlite3.Connection, gdate: str | None = None,
                        create: bool = False) -> sqlite3.Row | None:
    gdate = validate_gdate(gdate or date.today().isoformat())
    row = con.execute("SELECT * FROM fiscal_year WHERE ? BETWEEN start_date AND end_date ORDER BY start_date LIMIT 1",
                      (gdate,)).fetchone()
    if row or not create:
        return row
    y, m, d = map(int, gdate.split("-"))
    jy = jalali.gregorian_to_jalali(y, m, d)[0]
    con.execute("INSERT OR IGNORE INTO fiscal_year (title,start_date,end_date) VALUES (?,?,?)",
                (f"سال مالی {jy}", jalali.start_of_jalali_year(jy), jalali.end_of_jalali_year(jy)))
    return con.execute("SELECT * FROM fiscal_year WHERE ? BETWEEN start_date AND end_date", (gdate,)).fetchone()


def get_setting(con, key: str, default: str = "") -> str:
    row = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(con, key: str, value: str, *, require_permission: bool = True) -> None:
    if require_permission:
        import auth
        auth.require("settings.edit")
    before = get_setting(con, key)
    con.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)))
    audit(con, "set_setting", "settings", None, f"{key}", before={"value": before}, after={"value": str(value)})


def next_no(con, name: str, year: str = "") -> int:
    con.execute("INSERT INTO sequences (name, year, last_value) VALUES (?, ?, 0) ON CONFLICT(name, year) DO NOTHING",
                (name, year))
    con.execute("UPDATE sequences SET last_value = last_value + 1 WHERE name = ? AND year = ?", (name, year))
    return con.execute("SELECT last_value FROM sequences WHERE name = ? AND year = ?", (name, year)).fetchone()["last_value"]


def audit(con, action: str, table_name: str = "", record_id: int | None = None, detail: str = "",
          before: dict | None = None, after: dict | None = None) -> None:
    import auth
    u = auth.current() or {}
    con.execute("""INSERT INTO audit_log (action, table_name, record_id, detail, user_id, username, role, before_json, after_json)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (action, table_name, record_id, detail, u.get("id"), u.get("username"), u.get("role"),
                 json.dumps(before, ensure_ascii=False) if before is not None else None,
                 json.dumps(after, ensure_ascii=False) if after is not None else None))


def prune_backups(keep: int = 10) -> list[str]:
    import glob
    files = sorted(glob.glob(os.path.join(backup_dir(), "backup-*.db")), key=os.path.getmtime, reverse=True)
    removed = []
    for f in files[max(0, keep):]:
        try:
            os.remove(f); removed.append(f)
        except OSError:
            pass
    return removed


def auto_backup(con: sqlite3.Connection, label: str = "auto") -> str | None:
    global last_backup_error
    if get_setting(con, "auto_backup", "1") != "1":
        return None
    try:
        keep = int(get_setting(con, "backup_keep", "10") or 10)
        path = make_backup(con, label, require_permission=False)
        prune_backups(max(1, keep))
        last_backup_error = None
        return path
    except Exception as e:
        last_backup_error = str(e)
        return None


def _safe_label(label: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", label or "backup").strip("-")[:40] or "backup"


def make_backup(con: sqlite3.Connection, label: str = "manual", *, require_permission: bool = True, write_audit: bool = True) -> str:
    if require_permission:
        import auth
        auth.require("backup.create")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    target = os.path.join(backup_dir(), f"backup-{stamp}-{_safe_label(label)}.db")
    con.execute("VACUUM INTO ?", (target,))
    if os.name != "nt":
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
    check = sqlite3.connect(target)
    try:
        ok = check.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise RuntimeError(f"پشتیبان ناسالم است: {ok}")
    finally:
        check.close()
    if write_audit:
        audit(con, "backup", "database", None, target)
    return target


def validate_backup(path: str) -> dict:
    if not os.path.isfile(path):
        raise ValueError("فایل پشتیبان پیدا نشد")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise ValueError(f"فایل پشتیبان ناسالم است: {ok}")
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        from migrations import REQUIRED_TABLES
        missing = REQUIRED_TABLES - tables
        if missing:
            raise ValueError("فایل انتخاب‌شده پشتیبان این برنامه نیست؛ جداول کم دارد: " + ", ".join(sorted(missing)))
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise ValueError("فایل پشتیبان دارای خطای کلید خارجی است")
        version = con.execute("PRAGMA user_version").fetchone()[0]
        if version > SCHEMA_VERSION:
            raise ValueError("نسخهٔ پشتیبان از نسخهٔ برنامه جدیدتر است")
        counts = {t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("invoices", "payments", "journal_entries", "users")}
        return {"path": path, "version": version, "counts": counts}
    finally:
        con.close()


def stage_restore(con: sqlite3.Connection, path: str) -> dict:
    """فایل را اعتبارسنجی و برای بازیابی در اجرای بعدی آماده می‌کند."""
    import auth
    auth.require("backup.restore")
    info = validate_backup(path)
    pending = os.path.join(data_dir(), "restore-pending.json")
    staged = os.path.join(data_dir(), "restore-staged.db")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    dst = sqlite3.connect(staged)
    try:
        src.backup(dst)
    finally:
        dst.close(); src.close()
    if os.name != "nt":
        try:
            os.chmod(staged, 0o600)
        except OSError:
            pass
    with open(pending, "w", encoding="utf-8") as f:
        json.dump({"staged": staged, "source": path, "requested_at": datetime.now().isoformat()}, f, ensure_ascii=False)
    if os.name != "nt":
        try:
            os.chmod(pending, 0o600)
        except OSError:
            pass
    audit(con, "restore_staged", "database", None, path)
    con.commit()
    return info


def apply_pending_restore() -> str | None:
    """پیش از باز کردن اتصال اصلی، بازیابی مرحله‌بندی‌شده را اعمال می‌کند."""
    pending = os.path.join(data_dir(), "restore-pending.json")
    if not os.path.exists(pending):
        return None
    with open(pending, encoding="utf-8") as f:
        req = json.load(f)
    staged = req["staged"]
    validate_backup(staged)
    target = db_path()
    if os.path.exists(target):
        current = connect(target)
        try:
            make_backup(current, "pre-restore", require_permission=False)
        finally:
            current.close()
    for suffix in ("-wal", "-shm"):
        try:
            os.remove(target + suffix)
        except FileNotFoundError:
            pass
    os.replace(staged, target)
    os.remove(pending)
    con = connect(target)
    try:
        init_db(con)
        audit(con, "restore_applied", "database", None, req.get("source", ""))
        con.commit()
    finally:
        con.close()
    return target
