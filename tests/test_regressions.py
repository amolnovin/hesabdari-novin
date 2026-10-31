# -*- coding: utf-8 -*-
"""رگرسیون‌های گزارش بررسی کد و الزامات فایل پیوست."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

import auth
import db
import jalali
import repo


def line(item, qty, price, discount=0, vat=10):
    return {"item_id": item, "qty": qty, "unit_price": price, "discount": discount, "vat_rate": vat,
            **{k: v for k, v in repo.calc_line(qty, price, discount, vat).items() if k in ("net", "vat")}}


def inv(con, kind, party, rows, gdate=None, discount=0):
    return repo.save_invoice(con, None, {"kind": kind, "party_id": party,
                                         "gregorian_date": gdate or date.today().isoformat(),
                                         "discount": discount}, rows)


def balance(con, code):
    return con.execute("""SELECT COALESCE(SUM(l.debit-l.credit),0) v FROM journal_lines l
        JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
        WHERE a.code=? AND e.status='posted'""", (code,)).fetchone()["v"]


def test_db_rejects_unbalanced_and_posted_tampering(con):
    with pytest.raises(Exception):
        repo.post_entry(con, date.today().isoformat(), "general", [(repo.A_CASH, 100, 0, None), (repo.A_SALES, 0, 99, None)])
    eid = repo.post_entry(con, date.today().isoformat(), "general", [(repo.A_CASH, 100, 0, None), (repo.A_SALES, 0, 100, None)])
    with pytest.raises(Exception):
        con.execute("UPDATE journal_entries SET description='x' WHERE id=?", (eid,))
    with pytest.raises(Exception):
        con.execute("DELETE FROM journal_entries WHERE id=?", (eid,))
    with pytest.raises(Exception):
        con.execute("UPDATE journal_lines SET debit=1 WHERE entry_id=?", (eid,))
    with pytest.raises(Exception):
        con.execute("DELETE FROM journal_lines WHERE entry_id=?", (eid,))


def test_inventory_gl_matches_with_discount_and_vat(con):
    sup = repo.save_party(con, None, {"name": "تامین", "kind": "supplier"})
    cust = repo.save_party(con, None, {"name": "مشتری", "kind": "customer"})
    item = repo.save_item(con, None, {"name": "کالا", "sale_price": 2_000_000, "purchase_price": 1_000_000,
                                      "vat_rate": 10, "track_stock": True})
    p = inv(con, "purchase", sup, [line(item, 10, 1_000_000, vat=10)], discount=500_000)
    repo.confirm_invoice(con, p)
    s = inv(con, "sale", cust, [line(item, 4, 2_000_000, vat=10)], discount=300_000)
    repo.confirm_invoice(con, s)
    rec = repo.report_reconciliation(con)
    assert rec["stock_difference"] == 0
    assert rec["trial"]["balanced"] and rec["balance_sheet"]["balanced"]
    assert repo.stock_state(con, item)[0] == 6


def test_backdated_purchase_is_rejected_after_sale(con):
    sup = repo.save_party(con, None, {"name": "تامین", "kind": "supplier"})
    cust = repo.save_party(con, None, {"name": "مشتری", "kind": "customer"})
    item = repo.save_item(con, None, {"name": "کالا", "track_stock": True, "vat_rate": 0})
    repo.adjust_stock(con, item, 10, 1_000_000, date.today().isoformat())
    s = inv(con, "sale", cust, [line(item, 2, 2_000_000, vat=0)])
    repo.confirm_invoice(con, s)
    old = (date.today() - timedelta(days=5)).isoformat()
    p = inv(con, "purchase", sup, [line(item, 5, 900_000, vat=0)], gdate=old)
    with pytest.raises(repo.AccountingError):
        repo.confirm_invoice(con, p)


def test_payment_ownership_overpay_and_cancel(con):
    c1 = repo.save_party(con, None, {"name": "الف", "kind": "customer"})
    c2 = repo.save_party(con, None, {"name": "ب", "kind": "customer"})
    item = repo.save_item(con, None, {"name": "خدمت", "track_stock": False, "sale_price": 1000})
    i = inv(con, "sale", c1, [line(item, 1, 1000, vat=0)])
    repo.confirm_invoice(con, i)
    with pytest.raises(repo.AccountingError):
        repo.add_payment(con, "receipt", c2, 100, date.today().isoformat(), invoice_id=i)
    with pytest.raises(repo.AccountingError):
        repo.add_payment(con, "receipt", c1, 1001, date.today().isoformat(), invoice_id=i)
    pay = repo.add_payment(con, "receipt", c1, 1000, date.today().isoformat(), invoice_id=i)
    assert con.execute("SELECT paid_amount FROM invoices WHERE id=?", (i,)).fetchone()[0] == 1000
    repo.cancel_payment(con, pay)
    assert con.execute("SELECT paid_amount FROM invoices WHERE id=?", (i,)).fetchone()[0] == 0
    assert repo.report_trial_balance(con)["balanced"]


def test_paid_cheque_bounce_does_not_create_bank(con):
    sup = repo.save_party(con, None, {"name": "تامین", "kind": "supplier"})
    item = repo.save_item(con, None, {"name": "کالا", "track_stock": True})
    p = inv(con, "purchase", sup, [line(item, 1, 10_000_000, vat=0)])
    repo.confirm_invoice(con, p)
    before_bank = balance(con, repo.A_BANK)
    ch = repo.add_cheque(con, "paid", sup, "S1", 10_000_000, date.today().isoformat(),
                         (date.today() + timedelta(days=1)).isoformat())
    repo.bounce_cheque(con, ch)
    assert balance(con, repo.A_BANK) == before_bank
    assert repo.report_trial_balance(con)["balanced"]
    ch2 = repo.add_cheque(con, "paid", sup, "S2", 10_000_000, date.today().isoformat(),
                          (date.today() + timedelta(days=1)).isoformat())
    repo.clear_cheque(con, ch2)
    repo.bounce_cheque(con, ch2)
    assert balance(con, repo.A_BANK) == before_bank
    assert repo.report_trial_balance(con)["balanced"]


def test_fiscal_year_numbering_and_draft_date(con):
    c = repo.save_party(con, None, {"name": "مشتری", "kind": "customer"})
    item = repo.save_item(con, None, {"name": "خدمت", "track_stock": False})
    y = jalali.gregorian_to_jalali(*map(int, date.today().isoformat().split("-")))[0]
    d1 = jalali.from_jalali_str(f"{y}/01/10")
    d2 = jalali.from_jalali_str(f"{y+1}/01/10")
    i1 = inv(con, "sale", c, [line(item, 1, 100, vat=0)], gdate=d1)
    i2 = inv(con, "sale", c, [line(item, 1, 100, vat=0)], gdate=d2)
    n1 = con.execute("SELECT no FROM invoices WHERE id=?", (i1,)).fetchone()[0]
    n2 = con.execute("SELECT no FROM invoices WHERE id=?", (i2,)).fetchone()[0]
    assert n1 == n2 == 1
    repo.save_invoice(con, i1, {"kind": "sale", "party_id": c, "gregorian_date": d2, "discount": 0},
                      [line(item, 1, 100, vat=0)])
    fy = con.execute("SELECT fiscal_year_id FROM invoices WHERE id=?", (i1,)).fetchone()[0]
    assert fy == db.current_fiscal_year(con, d2)["id"]


def test_permissions_deny_by_default_and_mutations_require_auth(con):
    # خروج موقت از حالت سرویس برای آزمون دسترسی واقعی کاربر
    import auth as _auth
    old = _auth._service_mode
    _auth._service_mode = False
    try:
        auth.set_current(None)
        assert not auth.has("invoice.create")
        with pytest.raises(PermissionError):
            repo.save_party(con, None, {"name": "x", "kind": "customer"})
        with pytest.raises(PermissionError):
            db.set_setting(con, "x", "y")
    finally:
        _auth._service_mode = old


def test_restore_staging_and_validation(con, tmp_path):
    path = db.make_backup(con)
    info = db.validate_backup(path)
    assert info["counts"]["users"] == 0
    db.stage_restore(con, path)
    assert (tmp_path / "restore-pending.json").exists()
    with pytest.raises(ValueError):
        db.validate_backup(str(tmp_path / "missing.db"))


def test_money_decimal_and_csv_safe():
    import utils
    assert utils.parse_money("۱٬۲۰۰٬۰۰۰") == 1_200_000
    assert repo.rint(Decimal("1.5")) == 2
    assert utils.csv_safe("=1+1").startswith("'")
    assert utils.csv_safe("سلام") == "سلام"


def test_migration_legacy_db(tmp_path, monkeypatch):
    import sqlite3
    from migrations import migrate
    path = tmp_path / "legacy.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    # نسخهٔ قدیمی را از schema_embedded نمی‌سازیم؛ حداقل جداول لازم را دستی می‌سازیم.
    con.executescript("""
    CREATE TABLE fiscal_year(id INTEGER PRIMARY KEY,title TEXT,start_date TEXT,end_date TEXT,is_closed INTEGER DEFAULT 0);
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,code TEXT,name TEXT,parent_id INTEGER,type TEXT,level INTEGER,is_postable INTEGER,has_party INTEGER,is_system INTEGER);
    CREATE TABLE parties(id INTEGER PRIMARY KEY,code TEXT,name TEXT,kind TEXT,phone TEXT,address TEXT,national_id TEXT,economic_code TEXT,postal_code TEXT,opening_balance INTEGER DEFAULT 0,credit_limit INTEGER DEFAULT 0,note TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE items(id INTEGER PRIMARY KEY,code TEXT,name TEXT,unit TEXT,sale_price INTEGER,purchase_price INTEGER,vat_rate REAL,track_stock INTEGER,stock_min REAL,is_active INTEGER DEFAULT 1);
    CREATE TABLE stock_moves(id INTEGER PRIMARY KEY,item_id INTEGER,move_date TEXT,qty REAL,unit_cost INTEGER,move_type TEXT,ref_type TEXT,ref_id INTEGER,description TEXT);
    CREATE TABLE journal_entries(id INTEGER PRIMARY KEY,no INTEGER,fiscal_year_id INTEGER,entry_date TEXT,jalali_date TEXT,entry_type TEXT,reference_no TEXT,description TEXT,status TEXT,posted_at TEXT,created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE journal_lines(id INTEGER PRIMARY KEY,entry_id INTEGER,line_no INTEGER,account_id INTEGER,debit INTEGER,credit INTEGER,party_id INTEGER);
    CREATE TABLE invoices(id INTEGER PRIMARY KEY,no INTEGER,kind TEXT,party_id INTEGER,fiscal_year_id INTEGER,inv_date TEXT,jalali_date TEXT,due_date TEXT,subtotal INTEGER,discount INTEGER,vat_amount INTEGER,total INTEGER,paid_amount INTEGER DEFAULT 0,status TEXT,journal_entry_id INTEGER,description TEXT,created_at TEXT DEFAULT (datetime('now')),UNIQUE(kind,no));
    CREATE TABLE invoice_lines(id INTEGER PRIMARY KEY,invoice_id INTEGER,item_id INTEGER,description TEXT,qty REAL,unit_price INTEGER,discount INTEGER,vat_rate REAL,line_total INTEGER,unit_cost INTEGER DEFAULT 0);
    CREATE TABLE payments(id INTEGER PRIMARY KEY,no INTEGER,direction TEXT,method TEXT,party_id INTEGER,amount INTEGER,pay_date TEXT,jalali_date TEXT,invoice_id INTEGER,journal_entry_id INTEGER,description TEXT,is_cancelled INTEGER DEFAULT 0);
    CREATE TABLE sequences(name TEXT,year TEXT,last_value INTEGER,PRIMARY KEY(name,year));
    CREATE TABLE audit_log(id INTEGER PRIMARY KEY,action TEXT,table_name TEXT,record_id INTEGER,detail TEXT,created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,password_hash TEXT,salt TEXT,full_name TEXT,role TEXT,is_active INTEGER DEFAULT 1,last_login_at TEXT,created_at TEXT DEFAULT (datetime('now')));
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT);
    CREATE TABLE cheques(id INTEGER PRIMARY KEY,cheque_type TEXT,serial_no TEXT,bank_name TEXT,branch TEXT,amount INTEGER,issue_date TEXT,due_date TEXT,jalali_issue TEXT,jalali_due TEXT,party_id INTEGER,status TEXT,sayad_id TEXT,description TEXT,journal_entry_id INTEGER,cleared_entry_id INTEGER);
    CREATE TABLE period_lock(fiscal_year_id INTEGER,period_no INTEGER,is_locked INTEGER,locked_at TEXT,PRIMARY KEY(fiscal_year_id,period_no));
    INSERT INTO fiscal_year VALUES (1,'سال مالی 1404','2025-03-21','2026-03-20',0);
    INSERT INTO parties(id,name,kind) VALUES (1,'مشتری','customer');
    INSERT INTO invoices(id,no,kind,party_id,fiscal_year_id,inv_date,jalali_date,subtotal,discount,vat_amount,total,status)
      VALUES (1,1,'sale',1,1,'2025-04-01','1404/01/12',100,0,0,100,'draft');
    INSERT INTO stock_moves(item_id,move_date,qty,unit_cost,move_type) VALUES (1,'2025-04-01',2,50,'purchase');
    """)
    warnings = migrate(con)
    assert con.execute("PRAGMA user_version").fetchone()[0] == 2
    assert con.execute("SELECT value FROM stock_moves").fetchone()[0] == 100
    assert "cogs_amount" in {r[1] for r in con.execute("PRAGMA table_info(invoices)")}
    con.close()
