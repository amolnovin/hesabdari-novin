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
    return {
        "item_id": item,
        "qty": qty,
        "unit_price": price,
        "discount": discount,
        "vat_rate": vat,
        **{
            k: v
            for k, v in repo.calc_line(qty, price, discount, vat).items()
            if k in ("net", "vat")
        },
    }


def inv(con, kind, party, rows, gdate=None, discount=0):
    return repo.save_invoice(
        con,
        None,
        {
            "kind": kind,
            "party_id": party,
            "gregorian_date": gdate or date.today().isoformat(),
            "discount": discount,
        },
        rows,
    )


def balance(con, code):
    return con.execute(
        """SELECT COALESCE(SUM(l.debit-l.credit),0) v FROM journal_lines l
        JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
        WHERE a.code=? AND e.status='posted'""",
        (code,),
    ).fetchone()["v"]


def test_db_rejects_unbalanced_and_posted_tampering(con):
    with pytest.raises(Exception):
        repo.post_entry(
            con,
            date.today().isoformat(),
            "general",
            [(repo.A_CASH, 100, 0, None), (repo.A_SALES, 0, 99, None)],
        )
    eid = repo.post_entry(
        con,
        date.today().isoformat(),
        "general",
        [(repo.A_CASH, 100, 0, None), (repo.A_SALES, 0, 100, None)],
    )
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
    item = repo.save_item(
        con,
        None,
        {
            "name": "کالا",
            "sale_price": 2_000_000,
            "purchase_price": 1_000_000,
            "vat_rate": 10,
            "track_stock": True,
        },
    )
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
    item = repo.save_item(
        con, None, {"name": "کالا", "track_stock": True, "vat_rate": 0}
    )
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
    item = repo.save_item(
        con, None, {"name": "خدمت", "track_stock": False, "sale_price": 1000}
    )
    i = inv(con, "sale", c1, [line(item, 1, 1000, vat=0)])
    repo.confirm_invoice(con, i)
    with pytest.raises(repo.AccountingError):
        repo.add_payment(
            con, "receipt", c2, 100, date.today().isoformat(), invoice_id=i
        )
    with pytest.raises(repo.AccountingError):
        repo.add_payment(
            con, "receipt", c1, 1001, date.today().isoformat(), invoice_id=i
        )
    pay = repo.add_payment(
        con, "receipt", c1, 1000, date.today().isoformat(), invoice_id=i
    )
    assert (
        con.execute("SELECT paid_amount FROM invoices WHERE id=?", (i,)).fetchone()[0]
        == 1000
    )
    repo.cancel_payment(con, pay)
    assert (
        con.execute("SELECT paid_amount FROM invoices WHERE id=?", (i,)).fetchone()[0]
        == 0
    )
    assert repo.report_trial_balance(con)["balanced"]


def test_paid_cheque_bounce_does_not_create_bank(con):
    sup = repo.save_party(con, None, {"name": "تامین", "kind": "supplier"})
    item = repo.save_item(con, None, {"name": "کالا", "track_stock": True})
    p = inv(con, "purchase", sup, [line(item, 1, 10_000_000, vat=0)])
    repo.confirm_invoice(con, p)
    before_bank = balance(con, repo.A_BANK)
    ch = repo.add_cheque(
        con,
        "paid",
        sup,
        "S1",
        10_000_000,
        date.today().isoformat(),
        (date.today() + timedelta(days=1)).isoformat(),
    )
    repo.bounce_cheque(con, ch)
    assert balance(con, repo.A_BANK) == before_bank
    assert repo.report_trial_balance(con)["balanced"]
    ch2 = repo.add_cheque(
        con,
        "paid",
        sup,
        "S2",
        10_000_000,
        date.today().isoformat(),
        (date.today() + timedelta(days=1)).isoformat(),
    )
    repo.clear_cheque(con, ch2)
    repo.bounce_cheque(con, ch2)
    assert balance(con, repo.A_BANK) == before_bank
    assert repo.report_trial_balance(con)["balanced"]


def test_fiscal_year_numbering_and_draft_date(con):
    c = repo.save_party(con, None, {"name": "مشتری", "kind": "customer"})
    item = repo.save_item(con, None, {"name": "خدمت", "track_stock": False})
    y = jalali.gregorian_to_jalali(*map(int, date.today().isoformat().split("-")))[0]
    d1 = jalali.from_jalali_str(f"{y}/01/10")
    d2 = jalali.from_jalali_str(f"{y + 1}/01/10")
    i1 = inv(con, "sale", c, [line(item, 1, 100, vat=0)], gdate=d1)
    i2 = inv(con, "sale", c, [line(item, 1, 100, vat=0)], gdate=d2)
    n1 = con.execute("SELECT no FROM invoices WHERE id=?", (i1,)).fetchone()[0]
    n2 = con.execute("SELECT no FROM invoices WHERE id=?", (i2,)).fetchone()[0]
    assert n1 == n2 == 1
    repo.save_invoice(
        con,
        i1,
        {"kind": "sale", "party_id": c, "gregorian_date": d2, "discount": 0},
        [line(item, 1, 100, vat=0)],
    )
    fy = con.execute(
        "SELECT fiscal_year_id FROM invoices WHERE id=?", (i1,)
    ).fetchone()[0]
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
    assert con.execute("PRAGMA user_version").fetchone()[0] == 5
    assert con.execute("SELECT value FROM stock_moves").fetchone()[0] == 100
    assert "cogs_amount" in {r[1] for r in con.execute("PRAGMA table_info(invoices)")}
    con.close()


def test_business_profiles_are_twenty_and_applied(con):
    import business_profiles

    assert len(business_profiles.PROFILES) == 20
    assert len({v["title"] for v in business_profiles.PROFILES.values()}) == 20
    profile = business_profiles.apply_profile(con, "clothing", overwrite=True)
    assert profile["title"] == "پوشاک / کیف و کفش"
    assert db.get_setting(con, "business_profile") == "clothing"
    assert db.get_setting(con, "default_item_unit") == "عدد"
    assert "woo" in business_profiles.current(con)["modules"]
    assert con.execute("PRAGMA user_version").fetchone()[0] == 5


def test_woo_schema_queue_and_hmac_are_safe(con):
    import json
    import sync_outbox
    from woo_webhook import signature, verify

    assert con.execute("SELECT COUNT(*) FROM woo_map").fetchone()[0] == 0
    db.set_setting(con, "woo_enabled", "1", require_permission=False)
    with db.tx(con):
        first = sync_outbox.enqueue(con, "product", 17, "upsert", {"name": "الف"})
        second = sync_outbox.enqueue(con, "product", 17, "upsert", {"name": "ب"})
    row = con.execute("SELECT * FROM woo_queue WHERE id=?", (first,)).fetchone()
    assert first == second and json.loads(row["payload"])["name"] == "ب"
    raw = b'{"id":123}'
    sig = signature(raw, "shared-secret")
    assert verify(raw, sig, "shared-secret")
    assert not verify(raw, sig, "other-secret")
    assert not verify(raw, "", "shared-secret")


def test_woo_rest_client_uses_basic_auth_and_wc_v3():
    import base64
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from woocommerce import WooClient

    seen = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_GET(self):
            seen["path"] = self.path
            seen["auth"] = self.headers.get("Authorization")
            body = b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-WP-TotalPages", "1")
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = WooClient(
            f"http://127.0.0.1:{server.server_port}", "ck_demo", "cs_demo", retries=0
        )
        assert client.get("products", per_page=1) == []
        assert seen["path"].startswith("/wp-json/wc/v3/products?")
        assert seen["auth"] == "Basic " + base64.b64encode(b"ck_demo:cs_demo").decode()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_woo_paid_order_import_is_idempotent_and_posts_accounting(con):
    from datetime import datetime, timezone
    from woo_sync import _ensure_product, import_order

    class FakeWoo:
        def get(self, path):
            assert path == "products/501"
            return {
                "id": 501,
                "name": "کالای سایت",
                "sku": "SITE-501",
                "price": "1000.00",
                "status": "publish",
                "type": "simple",
                "date_modified_gmt": "2026-10-31T00:00:00",
            }

    today = date.today().isoformat()
    order = {
        "id": 9001,
        "status": "processing",
        "date_created_gmt": datetime.now(timezone.utc).isoformat(),
        "date_modified_gmt": datetime.now(timezone.utc).isoformat(),
        "customer_id": 0,
        "total": "1000.00",
        "billing": {"first_name": "مشتری آنلاین", "phone": "09120000000"},
        "line_items": [
            {
                "id": 1,
                "product_id": 501,
                "variation_id": 0,
                "name": "کالای سایت",
                "sku": "SITE-501",
                "quantity": 1,
                "subtotal": "1000.00",
                "total": "1000.00",
                "total_tax": "0.00",
            }
        ],
        "shipping_lines": [],
        "fee_lines": [],
    }
    with auth.service_mode():
        with db.tx(con):
            item = _ensure_product(con, FakeWoo(), FakeWoo().get("products/501"), 10)
        repo.adjust_stock(con, item["id"], 5, 4000, today, "موجودی افتتاحیه تست")
        pending = {**order, "status": "pending"}
        with db.tx(con):
            invoice_id = import_order(con, FakeWoo(), pending, 10)
        assert (
            con.execute(
                "SELECT paid_amount FROM invoices WHERE id=?", (invoice_id,)
            ).fetchone()[0]
            == 0
        )
        with db.tx(con):
            import_order(con, FakeWoo(), order, 10)
        with db.tx(con):
            again = import_order(con, FakeWoo(), order, 10)
    assert invoice_id == again
    invrow = con.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
    assert (
        invrow["status"] == "confirmed"
        and invrow["paid_amount"] == invrow["total"] == 10000
    )
    assert (
        con.execute(
            "SELECT COUNT(*) FROM invoices WHERE description LIKE '%9001'"
        ).fetchone()[0]
        == 1
    )
    assert repo.report_trial_balance(con)["balanced"]
    assert repo.report_reconciliation(con)["stock_difference"] == 0


def test_item_profile_metadata_persists_and_survives_remote_field_updates(con):
    item_id = repo.save_item(
        con,
        None,
        {
            "name": "کفش",
            "track_stock": True,
            "sale_price": 10000,
            "metadata": {"barcode": "6260001", "variant": "۳۸ / مشکی"},
        },
    )
    row = repo.get_item(con, item_id)
    import json

    assert json.loads(row["metadata_json"]) == {
        "barcode": "6260001",
        "variant": "۳۸ / مشکی",
    }
    repo.save_item(
        con, item_id, {"name": "کفش جدید", "track_stock": True, "sale_price": 12000}
    )
    assert json.loads(repo.get_item(con, item_id)["metadata_json"]) == {
        "barcode": "6260001",
        "variant": "۳۸ / مشکی",
    }


def test_woo_customer_update_preserves_accounting_fields(con):
    import sync_outbox
    from woo_sync import import_customer

    party_id = repo.save_party(
        con,
        None,
        {
            "code": "C-88",
            "name": "مشتری قدیمی",
            "kind": "customer",
            "phone": "09125550000",
            "email": "old@example.ir",
            "national_id": "1234567890",
            "postal_code": "1111111111",
            "economic_code": "E-1",
            "note": "یادداشت داخلی",
        },
    )
    with db.tx(con):
        sync_outbox.put_map(con, "customer", party_id, 7001)
    with auth.service_mode(), sync_outbox.suppress_outbound(), db.tx(con):
        result = import_customer(
            con,
            {
                "id": 7001,
                "first_name": "نام تازه",
                "last_name": "خانوادگی",
                "email": "new@example.ir",
                "billing": {"phone": "09120001111", "address_1": "نشانی جدید"},
            },
        )
    row = repo.get_party(con, result)
    assert row["id"] == party_id
    assert row["code"] == "C-88" and row["national_id"] == "1234567890"
    assert row["postal_code"] == "1111111111" and row["economic_code"] == "E-1"
    assert row["note"] == "یادداشت داخلی" and row["address"] == "نشانی جدید"
    assert row["email"] == "new@example.ir"


def test_database_v4_migrates_to_v5_with_party_email(tmp_path, monkeypatch):
    import sqlite3

    legacy_path = tmp_path / "v4.db"
    schema = db.schema_sql().replace(
        "PRAGMA user_version = 5;", "PRAGMA user_version = 4;"
    )
    schema = schema.replace("    email         TEXT,\n", "")
    old = sqlite3.connect(legacy_path)
    old.executescript(schema)
    assert old.execute("PRAGMA user_version").fetchone()[0] == 4
    old.close()
    monkeypatch.setenv("ACC_DB_PATH", str(legacy_path))
    monkeypatch.setenv("ACC_DATA_DIR", str(tmp_path))
    upgraded = db.connect()
    try:
        assert db.init_db(upgraded) == []
        assert upgraded.execute("PRAGMA user_version").fetchone()[0] == 5
        assert "email" in {
            r["name"] for r in upgraded.execute("PRAGMA table_info(parties)")
        }
        assert list((tmp_path / "backups").glob("backup-*-pre-migration.db"))
    finally:
        upgraded.close()


def test_webhook_http_server_enqueues_only_valid_signed_events(con):
    import json
    import threading
    import urllib.error
    import urllib.request
    from woo_webhook import WooWebhookServer, signature

    db.set_setting(con, "woo_webhook_enabled", "1", require_permission=False)
    db.set_setting(con, "woo_webhook_secret", "test-secret", require_permission=False)
    server = WooWebhookServer("127.0.0.1", 0).start()
    port = server.server.server_address[1]
    raw = json.dumps({"id": 9876}).encode()
    try:
        bad = urllib.request.Request(
            f"http://127.0.0.1:{port}/woo/webhook",
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-WC-Webhook-Topic": "order.created",
                "X-WC-Webhook-Signature": "invalid",
            },
        )
        with pytest.raises(urllib.error.HTTPError) as err:
            urllib.request.urlopen(bad, timeout=5)
        assert err.value.code == 401
        good = urllib.request.Request(
            f"http://127.0.0.1:{port}/woo/webhook",
            data=raw,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-WC-Webhook-Topic": "order.created",
                "X-WC-Webhook-Signature": signature(raw, "test-secret"),
            },
        )
        with urllib.request.urlopen(good, timeout=5) as response:
            assert response.status == 202
        assert (
            con.execute(
                "SELECT COUNT(*) FROM woo_events WHERE remote_id=9876 AND topic='order.created'"
            ).fetchone()[0]
            == 1
        )
    finally:
        server.stop()


def test_woo_customer_outbound_requires_and_sends_email(con):
    import sync_outbox
    from woo_sync import _push_queue

    class FakeWoo:
        def __init__(self):
            self.sent = []

        def post(self, endpoint, body):
            self.sent.append((endpoint, body))
            return {"id": 8801, "date_modified_gmt": "2026-10-31T00:00:00"}

        def put(self, endpoint, body):
            return {"id": 8801, **body}

    db.set_setting(con, "woo_enabled", "1", require_permission=False)
    db.set_setting(con, "woo_sync_customers", "1", require_permission=False)
    missing_email = repo.save_party(
        con, None, {"name": "بدون ایمیل", "kind": "customer"}
    )
    with db.tx(con):
        sync_outbox.enqueue(con, "customer", missing_email, "upsert")
    client = FakeWoo()
    with auth.service_mode():
        _push_queue(con, client, 10)
    assert not client.sent
    assert (
        con.execute(
            "SELECT status FROM woo_queue WHERE local_id=? ORDER BY id DESC LIMIT 1",
            (missing_email,),
        ).fetchone()[0]
        == "skipped"
    )
    with auth.service_mode():
        party = repo.save_party(
            con,
            None,
            {"name": "با ایمیل", "kind": "customer", "email": "buyer@example.ir"},
        )
    with db.tx(con):
        sync_outbox.enqueue(con, "customer", party, "upsert")
    with auth.service_mode():
        _push_queue(con, client, 10)
    assert client.sent[0][0] == "customers"
    assert client.sent[0][1]["email"] == "buyer@example.ir"
