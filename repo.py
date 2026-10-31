# -*- coding: utf-8 -*-
"""منطق کسب‌وکار و قوانین حسابداری دوطرفه.

تمام مبالغ به ریالِ صحیح ذخیره می‌شوند. محاسبات با Decimal انجام می‌شود.
حرکت انبار و سند حسابداری از یک محاسبهٔ واحد تولید می‌شوند تا ارزش انبار
با حساب موجودی کالا برابر بماند.
"""
from __future__ import annotations

import sqlite3
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

import auth
import db
import jalali

A_CASH = "10101"
A_BANK = "10102"
A_CUSTOMERS = "10103"
A_NOTES_RECEIVABLE = "10104"
A_NOTES_PAYABLE = "20102"
A_INVENTORY = "10105"
A_VAT_PURCHASE = "10106"
A_SUPPLIERS = "20101"
A_VAT_SALE = "20103"
A_RETAINED = "302"
A_SALES = "401"
A_SERVICES = "402"
A_SALES_RETURN = "403"
A_COGS = "501"
A_EXPENSE_GENERAL = "502"
A_STOCK_ADJUST = "505"
MAX_MONEY = 10**15


class AccountingError(Exception):
    """خطای قابل نمایش به کاربر."""


def D(x) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rint(x) -> int:
    return int(D(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def money_int(x, field="مبلغ") -> int:
    v = D(x)
    if not v.is_finite() or v != v.to_integral_value():
        raise AccountingError(f"{field} باید عدد صحیح ریال باشد")
    v = int(v)
    if abs(v) > MAX_MONEY:
        raise AccountingError(f"{field} خارج از بازهٔ مجاز است")
    return v


def qty_dec(x, field="تعداد", positive=True) -> Decimal:
    v = D(x)
    if not v.is_finite() or (positive and v <= 0) or (not positive and v < 0):
        raise AccountingError(f"{field} نامعتبر است")
    if v.as_tuple().exponent < -4:
        raise AccountingError(f"{field} حداکثر ۴ رقم اعشار می‌تواند داشته باشد")
    return v


def acc_id(con, code: str) -> int:
    row = con.execute("SELECT id FROM accounts WHERE code=?", (code,)).fetchone()
    if not row:
        raise AccountingError(f"حساب با کد {code} در کدینگ وجود ندارد")
    return row["id"]


def money_unit(con) -> tuple[str, int]:
    return ("تومان", 10) if db.get_setting(con, "money_unit", "rial") == "toman" else ("ریال", 1)


def fmt_money(con, rials: int, with_unit: bool = False) -> str:
    unit, div = money_unit(con)
    val = D(rials) / D(div)
    s = f"{val:,.0f}" if val == val.to_integral_value() else f"{val:,.2f}"
    return f"{s} {unit}" if with_unit else s


def period_locked(con, fiscal_year_id: int, period_no: int) -> bool:
    row = con.execute("SELECT is_locked FROM period_lock WHERE fiscal_year_id=? AND period_no=?",
                      (fiscal_year_id, period_no)).fetchone()
    return bool(row and row["is_locked"])


def set_period_lock(con, fiscal_year_id: int, period_no: int, locked: bool) -> None:
    auth.require("period.lock")
    with db.tx(con):
        con.execute("""INSERT INTO period_lock (fiscal_year_id,period_no,is_locked,locked_at)
                       VALUES (?,?,?,datetime('now'))
                       ON CONFLICT(fiscal_year_id,period_no) DO UPDATE SET
                       is_locked=excluded.is_locked,
                       locked_at=CASE WHEN excluded.is_locked=1 THEN datetime('now') ELSE NULL END""",
                    (fiscal_year_id, period_no, 1 if locked else 0))
        db.audit(con, "period_lock", "period_lock", fiscal_year_id, f"ماه {period_no} -> {'قفل' if locked else 'باز'}")


def _check_period(con, gdate: str) -> sqlite3.Row:
    fy = db.current_fiscal_year(con, gdate, create=True)
    if not fy:
        raise AccountingError("سال مالی متناظر با تاریخ یافت نشد")
    if fy["is_closed"]:
        raise AccountingError(f"سال مالی «{fy['title']}» بسته شده است")
    jdate = jalali.to_jalali_str(gdate)
    month = int(jdate.split("/")[1])
    if period_locked(con, fy["id"], month):
        raise AccountingError(f"ماه {month} از «{fy['title']}» قفل شده است؛ ثبت سند در این دوره ممکن نیست.")
    return fy


def post_entry(con, gdate: str, entry_type: str, lines: list[tuple], reference_no: str = "",
               description: str = "", reversed_entry_id: int | None = None) -> int:
    gdate = db.validate_gdate(gdate)
    fy = _check_period(con, gdate)
    jdate = jalali.to_jalali_str(gdate)
    year = jdate[:4]
    clean = []
    for code, debit, credit, party_id in lines:
        d, c = money_int(debit or 0, "بدهکار"), money_int(credit or 0, "بستانکار")
        if d < 0 or c < 0 or (d == 0 and c == 0) or (d and c):
            raise AccountingError("هر سطر سند باید فقط بدهکار یا فقط بستانکار و مثبت باشد")
        clean.append((code, d, c, party_id))
    if len(clean) < 2 or sum(x[1] for x in clean) != sum(x[2] for x in clean):
        raise AccountingError("سند تراز نیست: جمع بدهکار و بستانکار برابر نیست")
    u = auth.current() or {}
    with db.tx(con):
        no = db.next_no(con, "journal", year)
        cur = con.execute("""INSERT INTO journal_entries
            (no,fiscal_year_id,entry_date,jalali_date,entry_type,reference_no,description,status,created_by,reversed_entry_id)
            VALUES (?,?,?,?,?,?,?,'draft',?,?)""",
            (no, fy["id"], gdate, jdate, entry_type, reference_no or None, description or None, u.get("id"), reversed_entry_id))
        entry_id = cur.lastrowid
        for i, (code, d, c, party_id) in enumerate(clean, 1):
            con.execute("INSERT INTO journal_lines (entry_id,line_no,account_id,debit,credit,party_id) VALUES (?,?,?,?,?,?)",
                        (entry_id, i, acc_id(con, code), d, c, party_id))
        con.execute("UPDATE journal_entries SET status='posted', posted_at=datetime('now'), posted_by=? WHERE id=?",
                    (u.get("id"), entry_id))
        db.audit(con, "post_entry", "journal_entries", entry_id, f"{entry_type} {reference_no} - {description}")
    return entry_id


# ---------------------------------------------------------------- اشخاص
def list_parties(con, kind=None, search=""):
    sql = """SELECT p.*, COALESCE(b.balance,0) AS balance FROM parties p
             LEFT JOIN v_party_balance b ON b.party_id=p.id WHERE p.is_active=1"""
    args = []
    if kind and kind != "all":
        sql += " AND (p.kind=? OR p.kind='both')"; args.append(kind)
    if search:
        sql += " AND (p.name LIKE ? OR IFNULL(p.code,'') LIKE ? OR IFNULL(p.phone,'') LIKE ?)"
        args += [f"%{search}%"] * 3
    return con.execute(sql + " ORDER BY p.name", args).fetchall()


def get_party(con, party_id):
    return con.execute("SELECT * FROM parties WHERE id=?", (party_id,)).fetchone()


def save_party(con, party_id, data) -> int:
    auth.require("party.edit")
    name = (data.get("name") or "").strip()
    if not name:
        raise AccountingError("نام شخص نمی‌تواند خالی باشد")
    kind = data.get("kind", "customer")
    if kind not in ("customer", "supplier", "both"):
        raise AccountingError("نوع شخص نامعتبر است")
    opening = money_int(data.get("opening_balance") or 0, "مانده اولیه")
    credit = money_int(data.get("credit_limit") or 0, "سقف اعتبار")
    if credit < 0:
        raise AccountingError("سقف اعتبار نمی‌تواند منفی باشد")
    with db.tx(con):
        if party_id:
            before = dict(get_party(con, party_id) or {})
            con.execute("""UPDATE parties SET code=?,name=?,kind=?,phone=?,address=?,national_id=?,
                economic_code=?,postal_code=?,credit_limit=?,note=? WHERE id=?""",
                (data.get("code") or None, name, kind, data.get("phone"), data.get("address"),
                 data.get("national_id"), data.get("economic_code"), data.get("postal_code"), credit,
                 data.get("note"), party_id))
            new_id = party_id
            db.audit(con, "update_party", "parties", party_id, name, before=before, after=data)
        else:
            code = data.get("code") or str(db.next_no(con, "party"))
            cur = con.execute("""INSERT INTO parties (code,name,kind,phone,address,national_id,economic_code,
                postal_code,credit_limit,note) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (code, name, kind, data.get("phone"), data.get("address"), data.get("national_id"),
                 data.get("economic_code"), data.get("postal_code"), credit, data.get("note")))
            new_id = cur.lastrowid
            db.audit(con, "create_party", "parties", new_id, name)
        if opening and not party_id:
            set_party_opening(con, new_id, opening)
    return new_id


def set_party_opening(con, party_id: int, amount: int) -> None:
    amount = money_int(amount)
    if not amount:
        return
    party = get_party(con, party_id)
    if not party:
        raise AccountingError("شخص یافت نشد")
    recv = A_CUSTOMERS if party["kind"] in ("customer", "both") else A_SUPPLIERS
    if amount > 0:
        lines = [(recv, amount, 0, party_id), (A_RETAINED, 0, amount, None)]
    else:
        lines = [(A_RETAINED, -amount, 0, None), (recv, 0, -amount, party_id)]
    post_entry(con, date.today().isoformat(), "opening", lines, f"P-{party_id}", f"ماندهٔ اولیهٔ «{party['name']}»")


def delete_party(con, party_id: int) -> None:
    auth.require("party.edit")
    used = con.execute("SELECT COUNT(*) c FROM journal_lines WHERE party_id=?", (party_id,)).fetchone()["c"]
    if used:
        raise AccountingError("این شخص دارای سند حسابداری است و حذف نمی‌شود؛ می‌توانید غیرفعال کنید.")
    with db.tx(con):
        con.execute("UPDATE parties SET is_active=0 WHERE id=?", (party_id,))
        db.audit(con, "deactivate_party", "parties", party_id)


def party_ledger(con, party_id: int):
    return con.execute("""SELECT e.id AS entry_id, e.jalali_date, e.no, e.entry_type, e.reference_no,
        e.description AS entry_desc, a.code, a.name AS account_name, l.debit, l.credit
        FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
        WHERE l.party_id=? AND e.status='posted' ORDER BY e.entry_date,e.no,e.id""", (party_id,)).fetchall()


# ---------------------------------------------------------------- کالا و انبار
def list_items(con, search="", only_active=True):
    sql = "SELECT i.*, COALESCE(s.qty,0) AS stock FROM items i LEFT JOIN v_stock_balance s ON s.item_id=i.id"
    args, conds = [], []
    if only_active:
        conds.append("i.is_active=1")
    if search:
        conds.append("(i.name LIKE ? OR IFNULL(i.code,'') LIKE ?)"); args += [f"%{search}%"] * 2
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    out = []
    for r in con.execute(sql + " ORDER BY i.name", args).fetchall():
        d = dict(r)
        d["avg_cost"] = avg_cost(con, r["id"])[1] if r["track_stock"] else 0
        d["stock_value"] = stock_value(con, r["id"]) if r["track_stock"] else 0
        out.append(d)
    return out


def get_item(con, item_id):
    return con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()


def save_item(con, item_id, data) -> int:
    auth.require("item.edit")
    name = (data.get("name") or "").strip()
    if not name:
        raise AccountingError("نام کالا نمی‌تواند خالی باشد")
    sale = money_int(data.get("sale_price") or 0, "قیمت فروش")
    purchase = money_int(data.get("purchase_price") or 0, "قیمت خرید")
    vat = D(data.get("vat_rate") or 0)
    if sale < 0 or purchase < 0 or not vat.is_finite() or vat < 0 or vat > 100:
        raise AccountingError("قیمت یا نرخ مالیات نامعتبر است")
    track = 1 if data.get("track_stock") else 0
    if item_id:
        old = get_item(con, item_id)
        if old and old["track_stock"] != track and con.execute("SELECT 1 FROM stock_moves WHERE item_id=? LIMIT 1", (item_id,)).fetchone():
            raise AccountingError("تغییر نوع انبارش پس از ثبت گردش کالا مجاز نیست")
    fields = (data.get("code") or None, name, data.get("unit") or "عدد", sale, purchase, float(vat),
              track, float(qty_dec(data.get("stock_min") or 0, "حداقل موجودی", positive=False)),
              1 if data.get("is_active", True) else 0)
    with db.tx(con):
        if item_id:
            con.execute("""UPDATE items SET code=?,name=?,unit=?,sale_price=?,purchase_price=?,vat_rate=?,
                track_stock=?,stock_min=?,is_active=? WHERE id=?""", fields + (item_id,))
            new_id = item_id
        else:
            cur = con.execute("""INSERT INTO items (code,name,unit,sale_price,purchase_price,vat_rate,track_stock,
                stock_min,is_active) VALUES (?,?,?,?,?,?,?,?,?)""", fields)
            new_id = cur.lastrowid
        db.audit(con, "save_item", "items", new_id, name)
    return new_id


def delete_item(con, item_id: int) -> None:
    auth.require("item.edit")
    with db.tx(con):
        con.execute("UPDATE items SET is_active=0 WHERE id=?", (item_id,))
        db.audit(con, "deactivate_item", "items", item_id)


def _moves(con, item_id, upto_date=None, upto_id=None):
    sql = "SELECT id,move_date,qty,unit_cost,value FROM stock_moves WHERE item_id=?"
    args = [item_id]
    if upto_date:
        sql += " AND (move_date < ? OR (move_date=? AND id < ?))"
        args += [upto_date, upto_date, upto_id if upto_id is not None else 10**12]
    return con.execute(sql + " ORDER BY move_date,id", args).fetchall()


def stock_state(con, item_id: int, upto_date=None, upto_id=None) -> tuple[float, int]:
    qty = Decimal(0)
    value = 0
    for m in _moves(con, item_id, upto_date, upto_id):
        qty += D(m["qty"])
        value += int(m["value"])
    avg = rint(D(value) / qty) if qty > 0 else 0
    return float(qty), avg


def stock_value(con, item_id: int, upto_date=None, upto_id=None) -> int:
    return sum(int(m["value"]) for m in _moves(con, item_id, upto_date, upto_id))


def avg_cost(con, item_id):
    return stock_state(con, item_id)


def _last_move_date(con, item_id):
    r = con.execute("SELECT MAX(move_date) d FROM stock_moves WHERE item_id=?", (item_id,)).fetchone()
    return r["d"]


def _check_stock_date(con, item_id, gdate):
    last = _last_move_date(con, item_id)
    if last and gdate < last:
        raise AccountingError("ثبت با تاریخ گذشته پس از گردش‌های جدیدتر مجاز نیست؛ از سند اصلاحی در تاریخ جاری استفاده کنید.")


def item_cardex(con, item_id, date_from="", date_to=""):
    sql = "SELECT m.*, i.name AS item_name, i.unit FROM stock_moves m JOIN items i ON i.id=m.item_id WHERE m.item_id=?"
    args = [item_id]
    if date_from:
        sql += " AND m.move_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND m.move_date<=?"; args.append(date_to)
    return con.execute(sql + " ORDER BY m.move_date,m.id", args).fetchall()


def adjust_stock(con, item_id: int, new_qty: float, unit_cost: int, gdate: str, description="") -> None:
    auth.require("stock.adjust")
    item = get_item(con, item_id)
    if not item or not item["track_stock"]:
        raise AccountingError("این کالا انبار نمی‌شود")
    gdate = db.validate_gdate(gdate)
    _check_stock_date(con, item_id, gdate)
    new_qty = qty_dec(new_qty, "موجودی جدید", positive=False)
    cur_qty, cur_avg = stock_state(con, item_id)
    diff = new_qty - D(cur_qty)
    if diff == 0:
        return
    cost = money_int(unit_cost or cur_avg, "بهای واحد")
    if cost < 0:
        raise AccountingError("بهای واحد نمی‌تواند منفی باشد")
    value = rint(diff * D(cost if diff > 0 else cur_avg))
    with db.tx(con):
        _check_period(con, gdate)
        con.execute("""INSERT INTO stock_moves (item_id,move_date,qty,unit_cost,value,move_type,description)
                       VALUES (?,?,?,?,?,'adjust',?)""", (item_id, gdate, float(diff), cost, value, description or "اصلاح موجودی"))
        if value > 0:
            lines = [(A_INVENTORY, value, 0, None), (A_STOCK_ADJUST, 0, value, None)]
        else:
            lines = [(A_STOCK_ADJUST, -value, 0, None), (A_INVENTORY, 0, -value, None)]
        post_entry(con, gdate, "adjustment", lines, f"STOCK-{item_id}", description or "اصلاح موجودی")
        db.audit(con, "adjust_stock", "items", item_id, f"{cur_qty} → {new_qty}")


# ---------------------------------------------------------------- فاکتور
KIND_LABEL = {"sale": "فاکتور فروش", "sale_return": "برگشت از فروش",
              "purchase": "فاکتور خرید", "purchase_return": "برگشت از خرید"}


def calc_line(qty, unit_price, discount, vat_rate) -> dict:
    q = qty_dec(qty)
    p = money_int(unit_price, "قیمت واحد")
    d = money_int(discount or 0, "تخفیف")
    v = D(vat_rate or 0)
    if p < 0 or d < 0 or not v.is_finite() or v < 0 or v > 100:
        raise AccountingError("قیمت، تخفیف یا نرخ مالیات نامعتبر است")
    gross = rint(q * D(p))
    if d > gross:
        raise AccountingError("تخفیف ردیف نمی‌تواند بیشتر از مبلغ ردیف باشد")
    net = gross - d
    vat = rint(D(net) * v / D(100))
    return {"gross": gross, "net": net, "vat": vat, "total": net + vat}


def calc_invoice(lines: list[dict], invoice_discount=0) -> dict:
    subtotal = sum(money_int(l["net"]) for l in lines)
    vat = sum(money_int(l["vat"]) for l in lines)
    discount = money_int(invoice_discount or 0, "تخفیف کل")
    if discount < 0 or discount > subtotal:
        raise AccountingError("تخفیف کل باید بین صفر و جمع ردیف‌ها باشد")
    return {"subtotal": subtotal, "discount": discount, "vat_amount": vat, "total": subtotal - discount + vat}


def _allocate_discount(lines, discount):
    """تسهیم تخفیف کل به نسبت مبلغ خالص ردیف‌ها، با حفظ جمع دقیق."""
    total = sum(int(l["line_total"]) for l in lines)
    if not discount or not total:
        return [0] * len(lines)
    raw = [D(discount) * D(int(l["line_total"])) / D(total) for l in lines]
    alloc = [int(x.to_integral_value(rounding=ROUND_HALF_UP)) for x in raw]
    diff = discount - sum(alloc)
    order = sorted(range(len(lines)), key=lambda i: raw[i] - D(alloc[i]), reverse=diff > 0)
    i = 0
    while diff != 0 and order:
        idx = order[i % len(order)]
        step = 1 if diff > 0 else -1
        if 0 <= alloc[idx] + step <= int(lines[idx]["line_total"]):
            alloc[idx] += step; diff -= step
        i += 1
        if i > 10000:
            break
    return alloc


def save_invoice(con, inv_id, header, lines) -> int:
    auth.require("invoice.create")
    if not lines:
        raise AccountingError("فاکتور باید حداقل یک ردیف داشته باشد")
    kind = header["kind"]
    if kind not in KIND_LABEL:
        raise AccountingError("نوع فاکتور نامعتبر است")
    gdate = db.validate_gdate(header["gregorian_date"])
    due = header.get("gregorian_due_date") or None
    if due:
        due = db.validate_gdate(due)
        if due < gdate:
            raise AccountingError("سررسید نمی‌تواند قبل از تاریخ فاکتور باشد")
    party = get_party(con, header["party_id"])
    if not party or not party["is_active"]:
        raise AccountingError("طرف حساب فعال یافت نشد")
    need = "customer" if kind in ("sale", "sale_return") else "supplier"
    if party["kind"] not in (need, "both"):
        raise AccountingError("نوع طرف حساب با نوع فاکتور سازگار نیست")
    clean = []
    for l in lines:
        c = calc_line(l.get("qty"), l.get("unit_price"), l.get("discount"), l.get("vat_rate"))
        item_id = l.get("item_id")
        if item_id and not get_item(con, item_id):
            raise AccountingError("کالای انتخاب‌شده یافت نشد")
        if not item_id and not (l.get("description") or "").strip():
            raise AccountingError("ردیف بدون کالا باید شرح داشته باشد")
        clean.append({**l, **c, "item_id": item_id, "description": (l.get("description") or "").strip() or None})
    totals = calc_invoice(clean, header.get("discount", 0))
    fy = db.current_fiscal_year(con, gdate, create=True)
    jdate = jalali.to_jalali_str(gdate)
    with db.tx(con):
        if inv_id:
            inv = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
            if not inv:
                raise AccountingError("فاکتور یافت نشد")
            if inv["status"] != "draft":
                raise AccountingError("فاکتور قطعی‌شده قابل ویرایش نیست")
            new_no = inv["no"]
            if fy["id"] != inv["fiscal_year_id"]:
                new_no = db.next_no(con, "invoice_" + kind, jdate[:4])
            con.execute("""UPDATE invoices SET no=?,party_id=?,fiscal_year_id=?,inv_date=?,jalali_date=?,due_date=?,
                subtotal=?,discount=?,vat_amount=?,total=?,description=? WHERE id=?""",
                (new_no, header["party_id"], fy["id"], gdate, jdate, due, totals["subtotal"], totals["discount"],
                 totals["vat_amount"], totals["total"], header.get("description"), inv_id))
            con.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (inv_id,))
        else:
            no = db.next_no(con, "invoice_" + kind, jdate[:4])
            cur = con.execute("""INSERT INTO invoices
                (no,kind,party_id,fiscal_year_id,inv_date,jalali_date,due_date,subtotal,discount,vat_amount,total,status,description)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'draft',?)""",
                (no, kind, header["party_id"], fy["id"], gdate, jdate, due, totals["subtotal"],
                 totals["discount"], totals["vat_amount"], totals["total"], header.get("description")))
            inv_id = cur.lastrowid
        for l in clean:
            con.execute("""INSERT INTO invoice_lines
                (invoice_id,item_id,description,qty,unit_price,discount,vat_rate,line_total,unit_cost)
                VALUES (?,?,?,?,?,?,?,?,0)""",
                (inv_id, l["item_id"], l["description"], float(qty_dec(l["qty"])), money_int(l["unit_price"]),
                 money_int(l.get("discount") or 0), float(D(l.get("vat_rate") or 0)), l["net"]))
        db.audit(con, "save_invoice", "invoices", inv_id, f"{kind} #{inv_id}")
    return inv_id


def _stock_move(con, item_id, gdate, qty, value, mtype, inv_id, desc):
    con.execute("""INSERT INTO stock_moves (item_id,move_date,qty,unit_cost,value,move_type,ref_type,ref_id,description)
                   VALUES (?,?,?,?,?,?,'invoice',?,?)""",
                (item_id, gdate, float(qty), rint(D(value) / qty) if qty else 0, int(value), mtype, inv_id, desc))


def confirm_invoice(con, inv_id: int) -> int:
    auth.require("invoice.confirm")
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    if not inv:
        raise AccountingError("فاکتور یافت نشد")
    if inv["status"] == "confirmed":
        return inv["journal_entry_id"] or 0
    if inv["status"] == "cancelled":
        raise AccountingError("این فاکتور ابطال شده است")
    lines = con.execute("SELECT * FROM invoice_lines WHERE invoice_id=? ORDER BY id", (inv_id,)).fetchall()
    if not lines:
        raise AccountingError("فاکتور بدون قلم است")
    gdate, kind, party = inv["inv_date"], inv["kind"], inv["party_id"]
    _check_period(con, gdate)
    alloc = _allocate_discount(lines, inv["discount"])
    state = {}
    moves = []
    cogs_total = stock_amount = expense_amount = 0
    with db.tx(con):
        for ln, disc in zip(lines, alloc):
            item = get_item(con, ln["item_id"]) if ln["item_id"] else None
            net = int(ln["line_total"]) - disc
            if not item or not item["track_stock"]:
                if kind in ("purchase", "purchase_return"):
                    expense_amount += net
                continue
            _check_stock_date(con, item["id"], gdate)
            if item["id"] not in state:
                q, _ = stock_state(con, item["id"])
                state[item["id"]] = [D(q), stock_value(con, item["id"])]
            q, val = state[item["id"]]
            qty = D(ln["qty"])
            if kind == "purchase":
                mv_qty, mv_val = qty, net
            elif kind == "sale":
                if q < qty:
                    raise AccountingError(f"موجودی «{item['name']}» کافی نیست")
                avg = D(val) / q if q > 0 else D(0)
                mv_qty, mv_val = -qty, -rint(qty * avg)
                cogs_total += -mv_val
            elif kind == "sale_return":
                avg = D(val) / q if q > 0 else D(ln["unit_cost"] or 0)
                mv_qty, mv_val = qty, rint(qty * avg)
                cogs_total -= mv_val
            else:
                if q < qty:
                    raise AccountingError(f"موجودی «{item['name']}» برای برگشت خرید کافی نیست")
                avg = D(val) / q if q > 0 else D(0)
                mv_qty, mv_val = -qty, -rint(qty * avg)
            state[item["id"]] = [q + mv_qty, val + mv_val]
            moves.append((item["id"], mv_qty, mv_val, kind))
            if kind in ("purchase", "purchase_return"):
                stock_amount += mv_val
            con.execute("UPDATE invoice_lines SET unit_cost=? WHERE id=?",
                        (rint(D(mv_val) / mv_qty) if mv_qty else 0, ln["id"]))
        net_sales = inv["subtotal"] - inv["discount"]
        jl = []
        if kind == "sale":
            jl.append((A_CUSTOMERS, inv["total"], 0, party))
            jl.append((A_SALES, 0, inv["subtotal"], None))
            if inv["discount"]:
                jl.append((A_SALES_RETURN, inv["discount"], 0, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_SALE, 0, inv["vat_amount"], None))
            if cogs_total:
                jl += [(A_COGS, cogs_total, 0, None), (A_INVENTORY, 0, cogs_total, None)]
            desc = f"فاکتور فروش شماره {inv['no']}"
        elif kind == "sale_return":
            jl.append((A_CUSTOMERS, 0, inv["total"], party))
            jl.append((A_SALES_RETURN, net_sales, 0, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_SALE, inv["vat_amount"], 0, None))
            if cogs_total:
                jl += [(A_INVENTORY, -cogs_total, 0, None), (A_COGS, 0, -cogs_total, None)]
            desc = f"برگشت از فروش شماره {inv['no']}"
        elif kind == "purchase":
            if stock_amount:
                jl.append((A_INVENTORY, stock_amount, 0, None))
            if expense_amount:
                jl.append((A_EXPENSE_GENERAL, expense_amount, 0, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_PURCHASE, inv["vat_amount"], 0, None))
            jl.append((A_SUPPLIERS, 0, inv["total"], party))
            desc = f"فاکتور خرید شماره {inv['no']}"
        else:
            jl.append((A_SUPPLIERS, inv["total"], 0, party))
            if stock_amount:
                jl.append((A_INVENTORY, 0, -stock_amount, None))
            if expense_amount:
                jl.append((A_EXPENSE_GENERAL, 0, expense_amount, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_PURCHASE, 0, inv["vat_amount"], None))
            desc = f"برگشت از خرید شماره {inv['no']}"
        entry_id = post_entry(con, gdate, kind, jl, str(inv["no"]), desc)
        for item_id, qty, value, mtype in moves:
            _stock_move(con, item_id, gdate, qty, value, mtype, inv_id, desc)
        con.execute("""UPDATE invoices SET status='confirmed', journal_entry_id=?, cogs_amount=?,
                       stock_amount=?, expense_amount=? WHERE id=?""",
                    (entry_id, cogs_total, stock_amount, expense_amount, inv_id))
        db.audit(con, "confirm_invoice", "invoices", inv_id, f"{KIND_LABEL[kind]} #{inv['no']}")
    return entry_id


def cancel_invoice(con, inv_id: int, reason: str = "", gdate: str | None = None) -> None:
    auth.require("invoice.cancel")
    inv = con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
    if not inv:
        raise AccountingError("فاکتور یافت نشد")
    if inv["status"] == "cancelled":
        raise AccountingError("این فاکتور قبلاً ابطال شده است")
    if inv["status"] == "draft":
        with db.tx(con):
            con.execute("DELETE FROM invoice_lines WHERE invoice_id=?", (inv_id,))
            con.execute("DELETE FROM invoices WHERE id=?", (inv_id,))
            db.audit(con, "delete_draft_invoice", "invoices", inv_id, reason)
        return
    if inv["paid_amount"]:
        raise AccountingError("این فاکتور دریافت/پرداخت ثبت‌شده دارد؛ ابتدا آن‌ها را ابطال کنید")
    gdate = db.validate_gdate(gdate or date.today().isoformat())
    with db.tx(con):
        rev = _reverse_entry_lines(con, inv["journal_entry_id"])
        entry_id = post_entry(con, gdate, "adjustment", rev, str(inv["no"]),
                              f"ابطال {KIND_LABEL[inv['kind']]} شماره {inv['no']} — {reason}", inv["journal_entry_id"])
        for m in con.execute("SELECT * FROM stock_moves WHERE ref_type='invoice' AND ref_id=? AND move_type<>'adjust'", (inv_id,)).fetchall():
            _check_stock_date(con, m["item_id"], gdate)
            _stock_move(con, m["item_id"], gdate, -D(m["qty"]), -int(m["value"]), "adjust", inv_id, f"ابطال فاکتور {inv['no']}")
        con.execute("UPDATE invoices SET status='cancelled' WHERE id=?", (inv_id,))
        db.audit(con, "cancel_invoice", "invoices", inv_id, reason, after={"reversal_entry": entry_id})


def list_invoices(con, kind="sale", date_from="", date_to="", party_id=None, status=""):
    sql = """SELECT i.*, p.name AS party_name, (i.total-i.paid_amount) AS remainder
             FROM invoices i JOIN parties p ON p.id=i.party_id WHERE i.kind=?"""
    args = [kind]
    if date_from:
        sql += " AND i.inv_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND i.inv_date<=?"; args.append(date_to)
    if party_id:
        sql += " AND i.party_id=?"; args.append(party_id)
    if status:
        sql += " AND i.status=?"; args.append(status)
    return con.execute(sql + " ORDER BY i.inv_date DESC,i.no DESC", args).fetchall()


def invoice_lines(con, inv_id):
    return con.execute("""SELECT l.*, i.name AS item_name, i.unit FROM invoice_lines l
        LEFT JOIN items i ON i.id=l.item_id WHERE l.invoice_id=? ORDER BY l.id""", (inv_id,)).fetchall()


# ---------------------------------------------------------------- دریافت/پرداخت
def add_payment(con, direction, party_id, amount, gdate, method="cash", invoice_id=None, description="") -> int:
    auth.require("payment.create")
    if direction not in ("receipt", "payment"):
        raise AccountingError("نوع دریافت/پرداخت نامعتبر است")
    if method not in ("cash", "bank", "pos", "transfer"):
        raise AccountingError("روش پرداخت نامعتبر است")
    amount = money_int(amount)
    if amount <= 0:
        raise AccountingError("مبلغ باید بزرگ‌تر از صفر باشد")
    gdate = db.validate_gdate(gdate)
    party = get_party(con, party_id)
    if not party or not party["is_active"]:
        raise AccountingError("طرف حساب فعال یافت نشد")
    need = "customer" if direction == "receipt" else "supplier"
    if party["kind"] not in (need, "both"):
        raise AccountingError("نوع طرف حساب با نوع تراکنش سازگار نیست")
    with db.tx(con):
        if invoice_id:
            inv = con.execute("SELECT * FROM invoices WHERE id=?", (invoice_id,)).fetchone()
            if not inv or inv["party_id"] != party_id:
                raise AccountingError("فاکتور متعلق به این طرف حساب نیست")
            if inv["status"] != "confirmed":
                raise AccountingError("فقط فاکتور قطعی‌شده قابل تسویه است")
            expected = "sale" if direction == "receipt" else "purchase"
            if inv["kind"] != expected:
                raise AccountingError("نوع فاکتور با دریافت/پرداخت سازگار نیست")
            if amount > inv["total"] - inv["paid_amount"]:
                raise AccountingError("مبلغ پرداخت از ماندهٔ فاکتور بیشتر است")
        jdate = jalali.to_jalali_str(gdate)
        no = db.next_no(con, "payment", jdate[:4])
        cur = con.execute("""INSERT INTO payments (no,direction,method,party_id,amount,pay_date,jalali_date,invoice_id,description)
                             VALUES (?,?,?,?,?,?,?,?,?)""",
                          (no, direction, method, party_id, amount, gdate, jdate, invoice_id, description))
        pay_id = cur.lastrowid
        cash_acc = A_BANK if method in ("bank", "pos", "transfer") else A_CASH
        if direction == "receipt":
            lines = [(cash_acc, amount, 0, None), (A_CUSTOMERS, 0, amount, party_id)]
            desc = f"دریافت وجه شماره {no}"
        else:
            lines = [(A_SUPPLIERS, amount, 0, party_id), (cash_acc, 0, amount, None)]
            desc = f"پرداخت وجه شماره {no}"
        if description:
            desc += f" — {description}"
        entry_id = post_entry(con, gdate, direction, lines, str(no), desc)
        con.execute("UPDATE payments SET journal_entry_id=? WHERE id=?", (entry_id, pay_id))
        if invoice_id:
            con.execute("UPDATE invoices SET paid_amount=paid_amount+? WHERE id=?", (amount, invoice_id))
        db.audit(con, "add_payment", "payments", pay_id, f"{direction} {amount}")
    return pay_id


def cancel_payment(con, pay_id: int, reason: str = "", gdate: str | None = None) -> None:
    auth.require("payment.cancel")
    pay = con.execute("SELECT * FROM payments WHERE id=?", (pay_id,)).fetchone()
    if not pay or pay["is_cancelled"]:
        raise AccountingError("این مورد قابل ابطال نیست")
    gdate = db.validate_gdate(gdate or date.today().isoformat())
    with db.tx(con):
        rev = _reverse_entry_lines(con, pay["journal_entry_id"])
        post_entry(con, gdate, "adjustment", rev, str(pay["no"]),
                   f"ابطال رسید/پرداخت شماره {pay['no']} — {reason}", pay["journal_entry_id"])
        if pay["invoice_id"]:
            con.execute("UPDATE invoices SET paid_amount=MAX(0,paid_amount-?) WHERE id=?", (pay["amount"], pay["invoice_id"]))
        con.execute("UPDATE payments SET is_cancelled=1 WHERE id=?", (pay_id,))
        db.audit(con, "cancel_payment", "payments", pay_id, reason)


def list_payments(con, date_from="", date_to="", party_id=None):
    sql = "SELECT p.*, pt.name AS party_name FROM payments p JOIN parties pt ON pt.id=p.party_id WHERE 1=1"
    args = []
    if date_from:
        sql += " AND p.pay_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND p.pay_date<=?"; args.append(date_to)
    if party_id:
        sql += " AND p.party_id=?"; args.append(party_id)
    return con.execute(sql + " ORDER BY p.pay_date DESC,p.no DESC", args).fetchall()


# ---------------------------------------------------------------- گزارش‌ها
def report_trial_balance(con):
    rows = con.execute("SELECT * FROM v_trial_balance WHERE debit<>0 OR credit<>0").fetchall()
    td = sum(r["debit"] for r in rows); tc = sum(r["credit"] for r in rows)
    return {"rows": rows, "total_debit": td, "total_credit": tc, "balanced": td == tc}


def report_sales(con, date_from, date_to):
    invs = con.execute("""SELECT i.*, p.name AS party_name FROM invoices i JOIN parties p ON p.id=i.party_id
        WHERE i.kind IN ('sale','sale_return') AND i.status='confirmed' AND i.inv_date BETWEEN ? AND ?
        ORDER BY i.inv_date,i.no""", (date_from, date_to)).fetchall()
    total_sale = total_return = total_vat = total_cogs = 0
    detail = []
    for inv in invs:
        cogs = inv["cogs_amount"] or sum(rint(D(r["qty"]) * D(r["unit_cost"])) for r in invoice_lines(con, inv["id"]))
        net = inv["subtotal"] - inv["discount"]
        if inv["kind"] == "sale":
            total_sale += net; total_cogs += cogs; signed_net, signed_cogs = net, cogs
        else:
            total_return += net; total_cogs -= cogs; signed_net, signed_cogs = -net, -cogs
        total_vat += inv["vat_amount"] if inv["kind"] == "sale" else -inv["vat_amount"]
        gp = signed_net - signed_cogs
        detail.append({"inv": inv, "net": net, "cogs": cogs, "gross_profit": gp,
                       "margin": (100.0 * gp / signed_net) if signed_net else 0.0})
    net_sales = total_sale - total_return
    return {"detail": detail, "gross_sales": total_sale, "returns": total_return, "net_sales": net_sales,
            "cogs": total_cogs, "vat": total_vat, "gross_profit": net_sales - total_cogs,
            "margin": (100.0 * (net_sales - total_cogs) / net_sales) if net_sales else 0.0}


def report_stock(con):
    rows, total = [], 0
    for it in con.execute("SELECT * FROM items WHERE track_stock=1 AND is_active=1 ORDER BY name"):
        qty, cost = stock_state(con, it["id"])
        value = stock_value(con, it["id"])
        total += value
        rows.append({"item": it, "qty": qty, "avg_cost": cost, "value": value, "low": qty <= float(it["stock_min"])})
    return {"rows": rows, "total_value": total}


def report_customers(con, kind="customer"):
    rows, total = [], 0
    for p in con.execute("""SELECT p.*, COALESCE(b.balance,0) AS balance FROM parties p
        LEFT JOIN v_party_balance b ON b.party_id=p.id WHERE p.is_active=1 AND (p.kind=? OR p.kind='both')
        ORDER BY balance DESC,p.name""", (kind,)):
        unpaid = con.execute("""SELECT COUNT(*) c, COALESCE(SUM(total-paid_amount),0) s FROM invoices
            WHERE party_id=? AND status='confirmed' AND kind=? AND total-paid_amount>0""",
            (p["id"], "sale" if kind == "customer" else "purchase")).fetchone()
        rows.append({"party": p, "balance": p["balance"], "open_invoices": unpaid["c"], "open_amount": unpaid["s"]})
        total += p["balance"]
    return {"rows": rows, "total": total}


def report_profit_loss(con, date_from, date_to):
    def bal(codes, sign=1):
        tot = 0
        for c in codes:
            row = con.execute("""SELECT COALESCE(SUM(CASE WHEN e.status='posted' THEN l.credit-l.debit END),0) v
                FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
                WHERE a.code=? AND e.entry_date BETWEEN ? AND ?""", (c, date_from, date_to)).fetchone()
            tot += row["v"]
        return tot * sign
    revenue = bal([A_SALES, A_SERVICES]) + bal([A_SALES_RETURN])
    cogs = -bal([A_COGS])
    expenses = -bal([A_EXPENSE_GENERAL, "503", "504", A_STOCK_ADJUST])
    return {"revenue": revenue, "cogs": cogs, "gross_profit": revenue - cogs,
            "expenses": expenses, "net_profit": revenue - cogs - expenses}


def report_balance_sheet(con, as_of=None):
    as_of = as_of or date.today().isoformat()
    rows = con.execute("""SELECT a.code,a.name,a.type,
        COALESCE(SUM(CASE WHEN e.status='posted' AND e.entry_date<=? THEN l.debit-l.credit END),0) bal
        FROM accounts a LEFT JOIN journal_lines l ON l.account_id=a.id LEFT JOIN journal_entries e ON e.id=l.entry_id
        WHERE a.is_postable=1 GROUP BY a.id ORDER BY a.code""", (as_of,)).fetchall()
    assets = sum(r["bal"] for r in rows if r["type"] == "asset")
    liabilities = sum(-r["bal"] for r in rows if r["type"] == "liability")
    equity = sum(-r["bal"] for r in rows if r["type"] == "equity")
    pl = report_profit_loss(con, "0001-01-01", as_of)
    equity += pl["net_profit"]
    return {"as_of": as_of, "rows": rows, "assets": assets, "liabilities": liabilities,
            "equity": equity, "balanced": assets == liabilities + equity}


def report_ledger(con, account_code, date_from="", date_to=""):
    sql = """SELECT e.id AS entry_id, e.jalali_date, e.no, e.entry_type, e.reference_no,
        e.description AS entry_desc, l.debit, l.credit, p.name AS party_name
        FROM journal_lines l JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
        LEFT JOIN parties p ON p.id=l.party_id WHERE a.code=? AND e.status='posted'"""
    args = [account_code]
    if date_from:
        sql += " AND e.entry_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND e.entry_date<=?"; args.append(date_to)
    return con.execute(sql + " ORDER BY e.entry_date,e.no,e.id", args).fetchall()


def report_journal(con, date_from="", date_to=""):
    sql = """SELECT e.id,e.no,e.jalali_date,e.entry_type,e.reference_no,e.description,
        u.username AS posted_by, SUM(l.debit) debit, SUM(l.credit) credit
        FROM journal_entries e JOIN journal_lines l ON l.entry_id=e.id LEFT JOIN users u ON u.id=e.posted_by
        WHERE e.status='posted'"""
    args = []
    if date_from:
        sql += " AND e.entry_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND e.entry_date<=?"; args.append(date_to)
    return con.execute(sql + " GROUP BY e.id ORDER BY e.entry_date,e.no", args).fetchall()


def report_reconciliation(con):
    stock = report_stock(con)["total_value"]
    gl = con.execute("""SELECT COALESCE(SUM(l.debit-l.credit),0) v FROM journal_lines l
        JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
        WHERE a.code=? AND e.status='posted'""", (A_INVENTORY,)).fetchone()["v"]
    bad_payments = con.execute("""SELECT p.id FROM payments p JOIN invoices i ON i.id=p.invoice_id
        WHERE p.is_cancelled=0 AND (i.party_id<>p.party_id OR i.status<>'confirmed'
        OR (p.direction='receipt' AND i.kind<>'sale') OR (p.direction='payment' AND i.kind<>'purchase'))""").fetchall()
    return {"stock_report": stock, "inventory_gl": gl, "stock_difference": stock - gl,
            "invalid_payments": [r["id"] for r in bad_payments],
            "trial": report_trial_balance(con), "balance_sheet": report_balance_sheet(con)}


def dashboard(con):
    today = date.today().isoformat()
    jy = jalali.gregorian_to_jalali(*map(int, today.split("-")))[0]
    y_start = jalali.start_of_jalali_year(jy)
    return {"sales": report_sales(con, y_start, today), "stock": report_stock(con),
            "customers": report_customers(con, "customer"), "suppliers": report_customers(con, "supplier"),
            "cash": con.execute("""SELECT COALESCE(SUM(debit-credit),0) v FROM journal_lines l
                JOIN journal_entries e ON e.id=l.entry_id JOIN accounts a ON a.id=l.account_id
                WHERE a.code IN (?,?) AND e.status='posted'""", (A_CASH, A_BANK)).fetchone()["v"],
            "trial": report_trial_balance(con), "jalali_year": jy, "cheques": cheques_summary(con)}


# ---------------------------------------------------------------- چک‌ها
CHEQUE_STATUS = {"pending": "در جریان وصول", "cleared": "وصول / پرداخت شده",
                 "bounced": "برگشت خورده", "cancelled": "ابطال شده"}


def add_cheque(con, cheque_type, party_id, serial_no, amount, issue_g, due_g, bank_name="", branch="",
               sayad_id="", description="") -> int:
    auth.require("cheque.create")
    if cheque_type not in ("received", "paid"):
        raise AccountingError("نوع چک نامعتبر است")
    amount = money_int(amount)
    if amount <= 0:
        raise AccountingError("مبلغ چک باید بزرگ‌تر از صفر باشد")
    serial_no = (serial_no or "").strip()
    if not serial_no:
        raise AccountingError("شماره سریال چک الزامی است")
    issue_g, due_g = db.validate_gdate(issue_g), db.validate_gdate(due_g)
    if due_g < issue_g:
        raise AccountingError("سررسید چک نمی‌تواند قبل از تاریخ صدور باشد")
    party = get_party(con, party_id)
    if not party or not party["is_active"]:
        raise AccountingError("طرف حساب فعال یافت نشد")
    need = "customer" if cheque_type == "received" else "supplier"
    if party["kind"] not in (need, "both"):
        raise AccountingError("نوع طرف حساب با نوع چک سازگار نیست")
    if con.execute("SELECT 1 FROM cheques WHERE cheque_type=? AND serial_no=?", (cheque_type, serial_no)).fetchone():
        raise AccountingError(f"چک با سریال {serial_no} قبلاً ثبت شده است")
    with db.tx(con):
        if cheque_type == "received":
            lines = [(A_NOTES_RECEIVABLE, amount, 0, party_id), (A_CUSTOMERS, 0, amount, party_id)]
        else:
            lines = [(A_SUPPLIERS, amount, 0, party_id), (A_NOTES_PAYABLE, 0, amount, None)]
        desc = f"چک {'دریافتنی' if cheque_type=='received' else 'پرداختنی'} شماره {serial_no} — {party['name']}"
        entry_id = post_entry(con, issue_g, "general", lines, serial_no, desc)
        cur = con.execute("""INSERT INTO cheques (cheque_type,serial_no,bank_name,branch,amount,issue_date,due_date,
            jalali_issue,jalali_due,party_id,status,sayad_id,description,journal_entry_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,'pending',?,?,?)""",
            (cheque_type, serial_no, bank_name, branch, amount, issue_g, due_g, jalali.to_jalali_str(issue_g),
             jalali.to_jalali_str(due_g), party_id, sayad_id, description, entry_id))
        cid = cur.lastrowid
        db.audit(con, "add_cheque", "cheques", cid, desc)
    return cid


def _reverse_entry_lines(con, entry_id):
    rev = []
    for r in con.execute("SELECT * FROM journal_lines WHERE entry_id=?", (entry_id,)):
        code = con.execute("SELECT code FROM accounts WHERE id=?", (r["account_id"],)).fetchone()["code"]
        rev.append((code, r["credit"], r["debit"], r["party_id"]))
    return rev


def clear_cheque(con, cheque_id: int, method="bank", gdate="") -> int:
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id=?", (cheque_id,)).fetchone()
    if not ch or ch["status"] != "pending":
        raise AccountingError("فقط چک‌های در جریان قابل وصول/پرداخت هستند")
    gdate = db.validate_gdate(gdate or date.today().isoformat())
    cash_acc = A_BANK if method == "bank" else A_CASH
    if ch["cheque_type"] == "received":
        lines = [(cash_acc, ch["amount"], 0, None), (A_NOTES_RECEIVABLE, 0, ch["amount"], ch["party_id"])]
    else:
        lines = [(A_NOTES_PAYABLE, ch["amount"], 0, None), (cash_acc, 0, ch["amount"], None)]
    with db.tx(con):
        entry_id = post_entry(con, gdate, "general", lines, ch["serial_no"], f"وصول/پرداخت چک {ch['serial_no']}")
        con.execute("UPDATE cheques SET status='cleared', cleared_entry_id=? WHERE id=?", (entry_id, cheque_id))
        db.audit(con, "clear_cheque", "cheques", cheque_id)
    return entry_id


def bounce_cheque(con, cheque_id: int, gdate="") -> int:
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id=?", (cheque_id,)).fetchone()
    if not ch or ch["status"] not in ("pending", "cleared"):
        raise AccountingError("این چک قابل برگشت‌زدن نیست")
    gdate = db.validate_gdate(gdate or date.today().isoformat())
    with db.tx(con):
        if ch["status"] == "cleared":
            post_entry(con, gdate, "adjustment", _reverse_entry_lines(con, ch["cleared_entry_id"]),
                       ch["serial_no"], f"برگشت از وصول چک {ch['serial_no']}", ch["cleared_entry_id"])
        if ch["cheque_type"] == "received":
            lines = [(A_CUSTOMERS, ch["amount"], 0, ch["party_id"]), (A_NOTES_RECEIVABLE, 0, ch["amount"], ch["party_id"])]
        else:
            lines = [(A_NOTES_PAYABLE, ch["amount"], 0, None), (A_SUPPLIERS, 0, ch["amount"], ch["party_id"])]
        entry_id = post_entry(con, gdate, "general", lines, ch["serial_no"], f"برگشت خوردن چک {ch['serial_no']}")
        con.execute("UPDATE cheques SET status='bounced' WHERE id=?", (cheque_id,))
        db.audit(con, "bounce_cheque", "cheques", cheque_id)
    return entry_id


def cancel_cheque(con, cheque_id: int, reason="", gdate="") -> int:
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id=?", (cheque_id,)).fetchone()
    if not ch or ch["status"] != "pending":
        raise AccountingError("فقط چک‌های در جریان قابل ابطال هستند")
    gdate = db.validate_gdate(gdate or date.today().isoformat())
    with db.tx(con):
        entry_id = post_entry(con, gdate, "adjustment", _reverse_entry_lines(con, ch["journal_entry_id"]),
                              ch["serial_no"], f"ابطال چک {ch['serial_no']} — {reason}", ch["journal_entry_id"])
        con.execute("UPDATE cheques SET status='cancelled' WHERE id=?", (cheque_id,))
        db.audit(con, "cancel_cheque", "cheques", cheque_id, reason)
    return entry_id


def list_cheques(con, cheque_type="", status="", date_from="", date_to=""):
    sql = "SELECT c.*, p.name AS party_name FROM cheques c JOIN parties p ON p.id=c.party_id WHERE 1=1"
    args = []
    if cheque_type:
        sql += " AND c.cheque_type=?"; args.append(cheque_type)
    if status:
        sql += " AND c.status=?"; args.append(status)
    if date_from:
        sql += " AND c.due_date>=?"; args.append(date_from)
    if date_to:
        sql += " AND c.due_date<=?"; args.append(date_to)
    return con.execute(sql + " ORDER BY c.due_date", args).fetchall()


def cheques_summary(con):
    out = {"received_pending": 0, "received_count": 0, "paid_pending": 0, "paid_count": 0,
           "due_soon": 0, "overdue": 0, "due_soon_list": [], "overdue_list": []}
    today = date.today().isoformat()
    for c in con.execute("SELECT * FROM cheques WHERE status='pending'"):
        if c["cheque_type"] == "received":
            out["received_pending"] += c["amount"]; out["received_count"] += 1
        else:
            out["paid_pending"] += c["amount"]; out["paid_count"] += 1
        if c["due_date"] < today:
            out["overdue"] += 1; out["overdue_list"].append(c)
        elif (date.fromisoformat(c["due_date"]) - date.today()).days <= 7:
            out["due_soon"] += 1; out["due_soon_list"].append(c)
    return out


def report_aging(con, kind="customer"):
    term = int(db.get_setting(con, "default_term_days", "30") or 30)
    inv_kind = "sale" if kind == "customer" else "purchase"
    today = date.today()
    rows = con.execute("""SELECT i.id,i.no,i.jalali_date,i.due_date,i.inv_date,i.total,i.paid_amount,i.party_id,
        p.name AS party_name FROM invoices i JOIN parties p ON p.id=i.party_id
        WHERE i.kind=? AND i.status='confirmed' AND i.total-i.paid_amount>0 ORDER BY i.due_date,i.inv_date""",
        (inv_kind,)).fetchall()
    parties = {}
    for r in rows:
        due = r["due_date"] or (date.fromisoformat(r["inv_date"]) + __import__("datetime").timedelta(days=term)).isoformat()
        days = (today - date.fromisoformat(due)).days
        remain = r["total"] - r["paid_amount"]
        bucket = "current" if days <= 0 else ("d1_30" if days <= 30 else ("d31_60" if days <= 60 else ("d61_90" if days <= 90 else "d90_plus")))
        rec = parties.setdefault(r["party_id"], {"party_id": r["party_id"], "party_name": r["party_name"],
            "current": 0, "d1_30": 0, "d31_60": 0, "d61_90": 0, "d90_plus": 0, "total": 0, "invoices": 0})
        rec[bucket] += remain; rec["total"] += remain; rec["invoices"] += 1
    result = sorted(parties.values(), key=lambda x: -x["total"])
    return {"rows": result, "total": sum(r["total"] for r in result),
            "buckets": {k: sum(r[k] for r in result) for k in ("current", "d1_30", "d31_60", "d61_90", "d90_plus")}}
