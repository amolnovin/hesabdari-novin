# -*- coding: utf-8 -*-
"""مهاجرت امن پایگاه داده از نسخهٔ اولیه به نسخهٔ ۲.

اصل‌ها:
- هیچ سند قطعی حذف یا بازنویسی مالی نمی‌شود.
- پیش از مهاجرت، نسخهٔ پشتیبان گرفته می‌شود.
- تغییرات ساختاری در یک تراکنش انجام می‌شوند.
- مغایرت‌های تاریخی به‌جای دستکاری پنهان، در گزارش سازگاری نمایش داده می‌شوند.
"""
from __future__ import annotations

import sqlite3
from datetime import date

import jalali

SCHEMA_VERSION = 2
REQUIRED_TABLES = {
    "settings", "fiscal_year", "accounts", "parties", "items", "stock_moves",
    "invoices", "invoice_lines", "payments", "journal_entries", "journal_lines",
    "sequences", "audit_log", "users", "cheques", "period_lock",
}


def _cols(con, table):
    return {r[1] for r in con.execute(f"PRAGMA table_info({table})")}


def _add_col(con, table, col, ddl):
    if col not in _cols(con, table):
        con.execute(f"ALTER TABLE {table} ADD COLUMN {col} {ddl}")


def _ensure_years(con):
    dates = []
    for table, col in (("journal_entries", "entry_date"), ("invoices", "inv_date"),
                       ("payments", "pay_date"), ("cheques", "issue_date"), ("stock_moves", "move_date")):
        try:
            dates += [r[0] for r in con.execute(f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL")]
        except sqlite3.OperationalError:
            pass
    today = date.today()
    years = {jalali.gregorian_to_jalali(today.year, today.month, today.day)[0]}
    for d in dates:
        try:
            y, m, dd = map(int, str(d)[:10].split("-"))
            years.add(jalali.gregorian_to_jalali(y, m, dd)[0])
        except Exception:
            continue
    for jy in sorted(years):
        for y in (jy - 1, jy, jy + 1):
            con.execute("INSERT OR IGNORE INTO fiscal_year (title,start_date,end_date) VALUES (?,?,?)",
                        (f"سال مالی {y}", jalali.start_of_jalali_year(y), jalali.end_of_jalali_year(y)))


def _fy_id(con, gdate):
    row = con.execute("SELECT id FROM fiscal_year WHERE ? BETWEEN start_date AND end_date", (gdate,)).fetchone()
    return row[0] if row else None


def migrate(con: sqlite3.Connection) -> list[str]:
    """مهاجرت نسخهٔ ۰/۱ به ۲. پیام‌های هشدار برای گزارش به کاربر برمی‌گردد."""
    warnings: list[str] = []
    version = con.execute("PRAGMA user_version").fetchone()[0]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if not tables:
        return warnings
    if version >= SCHEMA_VERSION:
        return warnings
    if "journal_entries" not in tables:
        return warnings

    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("BEGIN")
    try:
        for t in ("trg_lines_no_edit_posted", "trg_lines_no_delete_posted", "trg_lines_no_insert_posted",
                  "trg_entry_no_update_posted", "trg_entry_no_delete_posted", "trg_entry_no_direct_posted",
                  "trg_entry_must_balance", "trg_invoice_no_edit_confirmed", "trg_invoice_no_delete_confirmed",
                  "trg_invoice_lines_no_edit_confirmed", "trg_invoice_lines_no_delete_confirmed"):
            con.execute(f"DROP TRIGGER IF EXISTS {t}")
        _ensure_years(con)
        # ستون‌های جدید
        _add_col(con, "stock_moves", "value", "INTEGER NOT NULL DEFAULT 0")
        _add_col(con, "journal_entries", "created_by", "INTEGER REFERENCES users(id)")
        _add_col(con, "journal_entries", "posted_by", "INTEGER REFERENCES users(id)")
        _add_col(con, "journal_entries", "reversed_entry_id", "INTEGER REFERENCES journal_entries(id)")
        for col, ddl in (("user_id", "INTEGER"), ("username", "TEXT"), ("role", "TEXT"),
                         ("before_json", "TEXT"), ("after_json", "TEXT")):
            _add_col(con, "audit_log", col, ddl)
        _add_col(con, "invoices", "cogs_amount", "INTEGER NOT NULL DEFAULT 0")
        _add_col(con, "invoices", "stock_amount", "INTEGER NOT NULL DEFAULT 0")
        _add_col(con, "invoices", "expense_amount", "INTEGER NOT NULL DEFAULT 0")

        con.execute("UPDATE stock_moves SET value = CAST(ROUND(qty * unit_cost) AS INTEGER) WHERE value = 0")
        con.execute("""INSERT OR IGNORE INTO accounts (id,code,name,parent_id,type,level,is_postable,has_party,is_system)
                       VALUES (26,'505','تعدیلات و ضایعات انبار',21,'expense',2,1,0,1)""")

        # اصلاح سال مالی اسناد/فاکتورها بر اساس تاریخ واقعی
        fixed = 0
        for r in con.execute("SELECT id,entry_date,fiscal_year_id FROM journal_entries").fetchall():
            fy = _fy_id(con, r[1])
            if fy and fy != r[2]:
                con.execute("UPDATE journal_entries SET fiscal_year_id=? WHERE id=?", (fy, r[0])); fixed += 1
        for r in con.execute("SELECT id,inv_date,fiscal_year_id FROM invoices").fetchall():
            fy = _fy_id(con, r[1])
            if fy and fy != r[2]:
                con.execute("UPDATE invoices SET fiscal_year_id=? WHERE id=?", (fy, r[0])); fixed += 1
        if fixed:
            warnings.append(f"سال مالی {fixed} سند/فاکتور بر اساس تاریخ واقعی اصلاح شد.")

        # بازسازی فاکتورها با یکتایی (نوع، سال مالی، شماره)
        con.execute("""CREATE TABLE invoices_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            no INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('sale','sale_return','purchase','purchase_return')),
            party_id INTEGER NOT NULL REFERENCES parties(id),
            fiscal_year_id INTEGER NOT NULL REFERENCES fiscal_year(id),
            inv_date TEXT NOT NULL,
            jalali_date TEXT NOT NULL,
            due_date TEXT,
            subtotal INTEGER NOT NULL DEFAULT 0,
            discount INTEGER NOT NULL DEFAULT 0,
            vat_amount INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            paid_amount INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','confirmed','cancelled')),
            journal_entry_id INTEGER REFERENCES journal_entries(id),
            description TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            cogs_amount INTEGER NOT NULL DEFAULT 0,
            stock_amount INTEGER NOT NULL DEFAULT 0,
            expense_amount INTEGER NOT NULL DEFAULT 0,
            UNIQUE (kind, fiscal_year_id, no)
        )""")
        cols = "id,no,kind,party_id,fiscal_year_id,inv_date,jalali_date,due_date,subtotal,discount,vat_amount,total,paid_amount,status,journal_entry_id,description,created_at,cogs_amount,stock_amount,expense_amount"
        con.execute(f"INSERT INTO invoices_v2 ({cols}) SELECT {cols} FROM invoices")
        con.execute("DROP TABLE invoices")
        con.execute("ALTER TABLE invoices_v2 RENAME TO invoices")
        con.execute("CREATE INDEX IF NOT EXISTS ix_inv_party ON invoices(party_id)")
        con.execute("CREATE INDEX IF NOT EXISTS ix_inv_date ON invoices(inv_date)")

        # شماره‌های تکراری احتمالی در یک سال مالی، پس از اصلاح سال، باز شماره‌گذاری می‌شوند.
        for kind, fy in con.execute("SELECT kind,fiscal_year_id FROM invoices GROUP BY kind,fiscal_year_id HAVING COUNT(*)<>COUNT(DISTINCT no)").fetchall():
            n = 0
            for r in con.execute("SELECT id FROM invoices WHERE kind=? AND fiscal_year_id=? ORDER BY inv_date,id", (kind, fy)).fetchall():
                n += 1
                con.execute("UPDATE invoices SET no=? WHERE id=?", (n, r[0]))
            jy = con.execute("SELECT substr(start_date,1,4) FROM fiscal_year WHERE id=?", (fy,)).fetchone()[0]
            con.execute("INSERT INTO sequences(name,year,last_value) VALUES (?,?,?) ON CONFLICT(name,year) DO UPDATE SET last_value=excluded.last_value",
                        ("invoice_" + kind, str(int(jy) - 621), n))
            warnings.append(f"شماره‌گذاری فاکتورهای {kind} در یک سال مالی بازسازی شد.")

        # paid_amount از پرداخت‌های واقعی بازسازی می‌شود.
        con.execute("""UPDATE invoices SET paid_amount = COALESCE((
            SELECT SUM(amount) FROM payments WHERE invoice_id=invoices.id AND is_cancelled=0),0)""")

        con.execute("PRAGMA user_version=2")
        con.execute("COMMIT")
    except Exception:
        con.execute("ROLLBACK")
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
    return warnings
