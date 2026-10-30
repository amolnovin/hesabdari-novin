# -*- coding: utf-8 -*-
"""
مرحله ۴) منطق کسب‌وکار (Business Logic)
========================================
این ماژول تمام قوانین حسابداری را در خود دارد. رابط کاربری فقط آن را صدا می‌زند.

مهم‌ترین قانون: هر عملیات مالی (فاکتور، دریافت، پرداخت) به‌طور خودکار
یک «سند حسابداری تراز» تولید می‌کند. کاربر هرگز مجبور نیست به صورت دستی
بدهکار/بستانکار وارد کند — و سندها همیشه ترازند، چون پایگاه داده اجازهٔ
خلاف آن را نمی‌دهد.
"""

import math
import sqlite3
from datetime import date

import auth
import db
import jalali

# ---------------------------------------------------------------------------
# کدهای حساب‌های سیستمی (ستون‌های برنامه)
# ---------------------------------------------------------------------------
A_CASH = "10101"            # صندوق
A_BANK = "10102"            # بانک
A_CUSTOMERS = "10103"       # مشتریان
A_NOTES_RECEIVABLE = "10104"   # اسناد دریافتنی (چک‌های دریافتنی)
A_NOTES_PAYABLE = "20102"      # اسناد پرداختنی (چک‌های پرداختنی)
A_INVENTORY = "10105"       # موجودی کالا
A_VAT_PURCHASE = "10106"    # اعتبار مالیاتی خرید
A_SUPPLIERS = "20101"       # تامین‌کنندگان
A_VAT_SALE = "20103"        # مالیات بر ارزش افزوده پرداختنی
A_RETAINED = "302"          # سود و زیان انباشته (طرفِ مانده‌های اولیه)
A_SALES = "401"             # فروش کالا
A_SERVICES = "402"          # درآمد خدمات
A_SALES_RETURN = "403"      # برگشت از فروش و تخفیفات
A_COGS = "501"              # بهای تمام‌شده کالای فروخته‌شده
A_EXPENSE_GENERAL = "502"   # هزینه‌های اداری و عمومی


class AccountingError(Exception):
    """خطای قابل نمایش به کاربر (برخلاف خطاهای فنی)"""


def rint(x: float) -> int:
    """گرد کردن به نزدیک‌ترین ریال (بدون خطای ممیز شناور)"""
    return int(math.floor(x + 0.5)) if x >= 0 else -int(math.floor(-x + 0.5))


def acc_id(con: sqlite3.Connection, code: str) -> int:
    row = con.execute("SELECT id FROM accounts WHERE code = ?", (code,)).fetchone()
    if not row:
        raise AccountingError(f"حساب با کد {code} در کدینگ وجود ندارد")
    return row["id"]


def money_unit(con: sqlite3.Connection) -> tuple[str, int]:
    """('ریال' یا 'تومان', تقسیم‌کننده)"""
    return ("تومان", 10) if db.get_setting(con, "money_unit", "rial") == "toman" else ("ریال", 1)


def fmt_money(con, rials: int, with_unit: bool = False) -> str:
    unit, div = money_unit(con)
    val = rials / div
    s = f"{val:,.0f}" if abs(val) >= 1 else f"{val:,.2f}"
    return f"{s} {unit}" if with_unit else s


# ===========================================================================
#  قفل دوره مالی
# ===========================================================================
def period_locked(con, fiscal_year_id: int, period_no: int) -> bool:
    row = con.execute(
        "SELECT is_locked FROM period_lock WHERE fiscal_year_id = ? AND period_no = ?",
        (fiscal_year_id, period_no)).fetchone()
    return bool(row and row["is_locked"])


def set_period_lock(con, fiscal_year_id: int, period_no: int, locked: bool) -> None:
    auth.require("period.lock")
    con.execute(
        """INSERT INTO period_lock (fiscal_year_id, period_no, is_locked, locked_at)
           VALUES (?,?,?, datetime('now'))
           ON CONFLICT(fiscal_year_id, period_no)
           DO UPDATE SET is_locked = excluded.is_locked,
                         locked_at = CASE WHEN excluded.is_locked = 1 THEN datetime('now') ELSE NULL END""",
        (fiscal_year_id, period_no, 1 if locked else 0))
    con.commit()
    db.audit(con, "period_lock", "period_lock", fiscal_year_id,
             f"ماه {period_no} -> {'قفل' if locked else 'باز'}")


def _check_period_lock(con, fy, jdate: str) -> None:
    """جلوگیری از ثبت سند در دورهٔ قفل‌شده (ماه شمسی)"""
    try:
        month = int(str(jdate).split("/")[1])
    except (IndexError, ValueError):
        return
    if period_locked(con, fy["id"], month):
        raise AccountingError(
            f"ماه {month} از «{fy['title']}» قفل شده است؛ ثبت سند در این دوره ممکن نیست."
        )


# ===========================================================================
#  اسناد حسابداری
# ===========================================================================
def post_entry(con, gdate: str, entry_type: str, lines: list[tuple],
               reference_no: str = "", description: str = "") -> int:
    """
    ثبت و قطعی کردن یک سند حسابداری.

    lines: لیستی از (account_code, debit, credit, party_id)
    اگر جمع بدهکار با بستانکار برابر نباشد، پایگاه داده خطا می‌دهد
    و هیچ تغییری ذخیره نمی‌شود (اتمی بودن تضمین‌شده است).
    """
    fy = db.current_fiscal_year(con, gdate)
    if not fy:
        raise AccountingError("هیچ سال مالی‌ای تعریف نشده است")
    if fy["is_closed"]:
        raise AccountingError(f"سال مالی «{fy['title']}» بسته شده است")

    jdate = jalali.to_jalali_str(gdate)
    _check_period_lock(con, fy, jdate)
    year = jdate[:4]
    cur = con.cursor()
    with db.tx(con):
        no = db.next_no(con, "journal", year)
        cur.execute(
            """INSERT INTO journal_entries
               (no, fiscal_year_id, entry_date, jalali_date, entry_type,
                reference_no, description, status, posted_at)
               VALUES (?,?,?,?,?,?,?,'draft', datetime('now'))""",
            (no, fy["id"], gdate, jdate, entry_type, reference_no or None, description or None),
        )
        entry_id = cur.lastrowid
        for i, (code, debit, credit, party_id) in enumerate(lines, start=1):
            if not debit and not credit:
                continue
            cur.execute(
                """INSERT INTO journal_lines
                   (entry_id, line_no, account_id, debit, credit, party_id)
                   VALUES (?,?,?,?,?,?)""",
                (entry_id, i, acc_id(con, code), int(debit or 0), int(credit or 0), party_id),
            )
        # این UPDATE تریگرِ کنترلِ تراز را فعال می‌کند
        cur.execute("UPDATE journal_entries SET status='posted' WHERE id=?", (entry_id,))
        db.audit(con, "post_entry", "journal_entries", entry_id,
                 f"{entry_type} {reference_no} - {description}")
    return entry_id


# ===========================================================================
#  اشخاص (مشتریان و تامین‌کنندگان)
# ===========================================================================
def list_parties(con, kind: str | None = None, search: str = "") -> list[sqlite3.Row]:
    sql = """SELECT p.*, COALESCE(b.balance,0) AS balance
             FROM parties p
             LEFT JOIN v_party_balance b ON b.party_id = p.id
             WHERE p.is_active = 1"""
    args: list = []
    if kind and kind != "all":
        sql += " AND (p.kind = ? OR p.kind = 'both')"
        args.append(kind)
    if search:
        sql += " AND (p.name LIKE ? OR IFNULL(p.code,'') LIKE ? OR IFNULL(p.phone,'') LIKE ?)"
        args += [f"%{search}%"] * 3
    sql += " ORDER BY p.name"
    return con.execute(sql, args).fetchall()


def get_party(con, party_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM parties WHERE id = ?", (party_id,)).fetchone()


def save_party(con, party_id: int | None, data: dict) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise AccountingError("نام شخص نمی‌تواند خالی باشد")

    opening = int(data.get("opening_balance") or 0)
    if party_id:
        con.execute(
            """UPDATE parties SET code=?, name=?, kind=?, phone=?, address=?,
               national_id=?, economic_code=?, postal_code=?, credit_limit=?, note=?
               WHERE id=?""",
            (data.get("code") or None, name, data.get("kind", "customer"),
             data.get("phone"), data.get("address"), data.get("national_id"),
             data.get("economic_code"), data.get("postal_code"),
             int(data.get("credit_limit") or 0), data.get("note"), party_id),
        )
        new_id = party_id
        db.audit(con, "update_party", "parties", party_id, name)
    else:
        code = data.get("code") or str(db.next_no(con, "party"))
        cur = con.execute(
            """INSERT INTO parties (code, name, kind, phone, address, national_id,
               economic_code, postal_code, credit_limit, note)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (code, name, data.get("kind", "customer"), data.get("phone"),
             data.get("address"), data.get("national_id"), data.get("economic_code"),
             data.get("postal_code"), int(data.get("credit_limit") or 0), data.get("note")),
        )
        new_id = cur.lastrowid
        db.audit(con, "create_party", "parties", new_id, name)

    if opening and not party_id:      # ماندهٔ اولیه فقط هنگام ایجاد ثبت می‌شود
        set_party_opening(con, new_id, opening)
    con.commit()
    return new_id


def set_party_opening(con, party_id: int, amount: int) -> None:
    """ثبت ماندهٔ اولیهٔ شخص به عنوان سند افتتاحیه"""
    if not amount:
        return
    party = get_party(con, party_id)
    is_customer = party["kind"] in ("customer", "both")
    recv = A_CUSTOMERS if is_customer else A_SUPPLIERS
    if amount > 0:
        lines = [(recv, amount, 0, party_id), (A_RETAINED, 0, amount, None)]
    else:
        lines = [(A_RETAINED, -amount, 0, None), (recv, 0, -amount, party_id)]
    post_entry(con, date.today().isoformat(), "opening", lines,
               f"P-{party_id}", f"ماندهٔ اولیهٔ «{party['name']}»")


def delete_party(con, party_id: int) -> None:
    auth.require("party.edit")
    used = con.execute(
        "SELECT COUNT(*) c FROM journal_lines WHERE party_id = ?", (party_id,)
    ).fetchone()["c"]
    if used:
        raise AccountingError(
            "این شخص دارای سند حسابداری است و حذف نمی‌شود. "
            "می‌توانید از گزینهٔ «غیرفعال کردن» استفاده کنید."
        )
    con.execute("UPDATE parties SET is_active = 0 WHERE id = ?", (party_id,))
    db.audit(con, "deactivate_party", "parties", party_id)
    con.commit()


def party_ledger(con, party_id: int) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT e.jalali_date, e.no, e.entry_type, e.reference_no,
                  e.description AS entry_desc, a.code, a.name AS account_name,
                  l.debit, l.credit
           FROM journal_lines l
           JOIN journal_entries e ON e.id = l.entry_id
           JOIN accounts a ON a.id = l.account_id
           WHERE l.party_id = ? AND e.status = 'posted'
           ORDER BY e.entry_date, e.no""",
        (party_id,),
    ).fetchall()


# ===========================================================================
#  کالاها و انبار
# ===========================================================================
def list_items(con, search: str = "", only_active: bool = True) -> list[sqlite3.Row]:
    sql = """SELECT i.*, COALESCE(s.qty,0) AS stock
             FROM items i
             LEFT JOIN v_stock_balance s ON s.item_id = i.id"""
    args: list = []
    conds = []
    if only_active:
        conds.append("i.is_active = 1")
    if search:
        conds.append("(i.name LIKE ? OR IFNULL(i.code,'') LIKE ?)")
        args += [f"%{search}%"] * 2
    if conds:
        sql += " WHERE " + " AND ".join(conds)
    sql += " ORDER BY i.name"
    rows = con.execute(sql, args).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["avg_cost"] = avg_cost(con, r["id"])[1] if r["track_stock"] else 0
        out.append(d)
    return out


def get_item(con, item_id: int) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def save_item(con, item_id: int | None, data: dict) -> int:
    name = (data.get("name") or "").strip()
    if not name:
        raise AccountingError("نام کالا نمی‌تواند خالی باشد")
    fields = (
        data.get("code") or None, name, data.get("unit") or "عدد",
        int(data.get("sale_price") or 0), int(data.get("purchase_price") or 0),
        float(data.get("vat_rate") or 0),
        1 if data.get("track_stock") else 0,
        float(data.get("stock_min") or 0),
        1 if data.get("is_active", True) else 0,
    )
    if item_id:
        con.execute(
            """UPDATE items SET code=?, name=?, unit=?, sale_price=?, purchase_price=?,
               vat_rate=?, track_stock=?, stock_min=?, is_active=? WHERE id=?""",
            fields + (item_id,),
        )
        new_id = item_id
    else:
        cur = con.execute(
            """INSERT INTO items (code, name, unit, sale_price, purchase_price,
               vat_rate, track_stock, stock_min, is_active)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            fields,
        )
        new_id = cur.lastrowid
    con.commit()
    db.audit(con, "save_item", "items", new_id, name)
    return new_id


def delete_item(con, item_id: int) -> None:
    used = con.execute(
        "SELECT COUNT(*) c FROM stock_moves WHERE item_id = ?", (item_id,)
    ).fetchone()["c"]
    if used:
        con.execute("UPDATE items SET is_active = 0 WHERE id = ?", (item_id,))
    else:
        con.execute("DELETE FROM items WHERE id = ?", (item_id,))
    con.commit()


def stock_state(con, item_id: int, upto_date: str | None = None,
                upto_id: int | None = None) -> tuple[float, int]:
    """
    بازسازی وضعیت انبار با پخشِ تمام حرکت‌ها (روش میانگین موزون).
    خروجی: (موجودی, بهای تمام‌شدهٔ هر واحد به ریال)
    """
    sql = "SELECT id, move_date, qty, unit_cost FROM stock_moves WHERE item_id = ?"
    args: list = [item_id]
    if upto_date:
        sql += " AND (move_date < ? OR (move_date = ? AND id < ?))"
        args += [upto_date, upto_date, upto_id if upto_id is not None else 10 ** 12]
    sql += " ORDER BY move_date, id"

    qty = 0.0
    avg = 0.0
    for m in con.execute(sql, args):
        q = float(m["qty"])
        if q > 0:                                   # ورود به انبار
            total = qty * avg + q * float(m["unit_cost"])
            qty += q
            avg = total / qty if qty else 0.0
        else:                                       # خروج از انبار
            out = -q
            if qty - out < -1e-9 and out > qty + 1e-9:
                pass                                # اجازهٔ موجودی منفی (کنترل در لایهٔ UI)
            qty -= out
    return round(qty, 4), int(round(avg))


def avg_cost(con, item_id: int) -> tuple[float, int]:
    return stock_state(con, item_id)


def item_cardex(con, item_id: int, date_from: str = "", date_to: str = "") -> list[sqlite3.Row]:
    sql = """SELECT m.*, i.name AS item_name, i.unit
             FROM stock_moves m JOIN items i ON i.id = m.item_id
             WHERE m.item_id = ?"""
    args: list = [item_id]
    if date_from:
        sql += " AND m.move_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND m.move_date <= ?"
        args.append(date_to)
    sql += " ORDER BY m.move_date, m.id"
    return con.execute(sql, args).fetchall()


def adjust_stock(con, item_id: int, new_qty: float, unit_cost: int,
                 gdate: str, description: str = "") -> None:
    """اصلاح دستی موجودی (مثلاً پس از انبارگردانی)"""
    cur_qty, cur_avg = stock_state(con, item_id)
    diff = round(float(new_qty) - cur_qty, 4)
    if abs(diff) < 1e-9:
        return
    with db.tx(con):
        con.execute(
            """INSERT INTO stock_moves (item_id, move_date, qty, unit_cost, move_type, description)
               VALUES (?,?,?,?, 'adjust', ?)""",
            (item_id, gdate, diff, unit_cost or cur_avg, description or "اصلاح موجودی"),
        )
    db.audit(con, "adjust_stock", "items", item_id, f"{cur_qty} → {new_qty}")


# ===========================================================================
#  فاکتورها
# ===========================================================================
KIND_LABEL = {
    "sale": "فاکتور فروش",
    "sale_return": "برگشت از فروش",
    "purchase": "فاکتور خرید (ورود به انبار)",
    "purchase_return": "برگشت از خرید",
}


def calc_line(qty: float, unit_price: int, discount: int, vat_rate: float) -> dict:
    """محاسبهٔ یک سطر فاکتور (همه چیز به ریال و عدد صحیح)"""
    gross = rint(float(qty) * float(unit_price))
    net = max(0, gross - int(discount or 0))
    vat = rint(net * float(vat_rate or 0) / 100.0)
    return {"gross": gross, "net": net, "vat": vat, "total": net + vat}


def calc_invoice(lines: list[dict], invoice_discount: int = 0) -> dict:
    subtotal = sum(int(l["net"]) for l in lines)
    vat = sum(int(l["vat"]) for l in lines)
    discount = min(int(invoice_discount or 0), subtotal)
    return {"subtotal": subtotal, "discount": discount, "vat_amount": vat,
            "total": subtotal - discount + vat}


def save_invoice(con, inv_id: int | None, header: dict, lines: list[dict]) -> int:
    """
    ذخیرهٔ فاکتور. فقط فاکتورهای پیش‌نویس قابل ویرایش هستند؛
    فاکتورِ قطعی‌شده تغییرناپذیر است و اصلاح آن فقط با «برگشت» یا «ابطال» ممکن است.
    """
    auth.require("invoice.create")
    if inv_id:
        cur = con.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,))
        inv = cur.fetchone()
        if not inv:
            raise AccountingError("فاکتور یافت نشد")
        if inv["status"] != "draft":
            raise AccountingError("فاکتور قطعی‌شده قابل ویرایش نیست")

    gdate = header["gregorian_date"]
    jdate = jalali.to_jalali_str(gdate)
    fy = db.current_fiscal_year(con, gdate)
    totals = calc_invoice(lines, header.get("discount", 0))

    cur = con.cursor()
    with db.tx(con):
        if inv_id:
            cur.execute(
                """UPDATE invoices SET party_id=?, inv_date=?, jalali_date=?, due_date=?,
                   subtotal=?, discount=?, vat_amount=?, total=?, description=?
                   WHERE id=?""",
                (header["party_id"], gdate, jdate, header.get("gregorian_due_date") or None,
                 totals["subtotal"], totals["discount"], totals["vat_amount"],
                 totals["total"], header.get("description"), inv_id),
            )
            cur.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (inv_id,))
        else:
            no = db.next_no(con, "invoice_" + header["kind"], jdate[:4])
            cur.execute(
                """INSERT INTO invoices
                   (no, kind, party_id, fiscal_year_id, inv_date, jalali_date, due_date,
                    subtotal, discount, vat_amount, total, status, description)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?, 'draft',?)""",
                (no, header["kind"], header["party_id"], fy["id"], gdate, jdate,
                 header.get("gregorian_due_date") or None, totals["subtotal"],
                 totals["discount"], totals["vat_amount"], totals["total"],
                 header.get("description")),
            )
            inv_id = cur.lastrowid

        for l in lines:
            cur.execute(
                """INSERT INTO invoice_lines
                   (invoice_id, item_id, description, qty, unit_price, discount,
                    vat_rate, line_total, unit_cost)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (inv_id, l.get("item_id"), l.get("description"),
                 float(l.get("qty") or 0), int(l.get("unit_price") or 0),
                 int(l.get("discount") or 0), float(l.get("vat_rate") or 0),
                 int(l["net"]), int(l.get("unit_cost") or 0)),
            )
        db.audit(con, "save_invoice", "invoices", inv_id, f"{header['kind']} #{inv_id}")
    return inv_id


def confirm_invoice(con, inv_id: int) -> int:
    """
    قطعی کردن فاکتور:
      * تولید سند حسابداریِ تراز
      * ثبت حرکت انبار (خروج در فروش / ورود در خرید)
      * محاسبه و ذخیرهٔ بهای تمام‌شده برای گزارش سود ناخالص
    """
    inv = con.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    if not inv:
        raise AccountingError("فاکتور یافت نشد")
    auth.require("invoice.confirm")
    if inv["status"] == "confirmed":
        return inv["journal_entry_id"] or 0
    if inv["status"] == "cancelled":
        raise AccountingError("این فاکتور ابطال شده است")

    lines = con.execute("SELECT * FROM invoice_lines WHERE invoice_id = ?", (inv_id,)).fetchall()
    if not lines:
        raise AccountingError("فاکتور بدون قلم است؛ ابتدا کالا یا خدمت اضافه کنید")

    gdate = inv["inv_date"]
    kind = inv["kind"]
    party = inv["party_id"]
    is_sale = kind in ("sale", "sale_return")
    is_return = kind in ("sale_return", "purchase_return")

    with db.tx(con):
        # --- محاسبهٔ بهای تمام‌شده و حرکت‌های انبار ---------------------------
        moves: list[tuple] = []     # (item_id, qty, unit_cost, move_type)
        cogs_total = 0
        for ln in lines:
            item = get_item(con, ln["item_id"]) if ln["item_id"] else None
            if not item or not item["track_stock"]:
                continue
            qty = float(ln["qty"])
            if kind == "sale":
                _q, cost = stock_state(con, item["id"], upto_date=gdate)
                moves.append((item["id"], -qty, cost, "sale"))
                cogs_total += rint(qty * cost)
                con.execute("UPDATE invoice_lines SET unit_cost = ? WHERE id = ?", (cost, ln["id"]))
            elif kind == "purchase":
                unit_cost = rint((float(ln["qty"]) * ln["unit_price"] - (ln["discount"] or 0))
                                 / float(ln["qty"])) if ln["qty"] else 0
                moves.append((item["id"], qty, unit_cost, "purchase"))
                con.execute("UPDATE invoice_lines SET unit_cost = ? WHERE id = ?", (unit_cost, ln["id"]))
            elif kind == "sale_return":
                _q, cost = stock_state(con, item["id"], upto_date=gdate)
                moves.append((item["id"], qty, cost, "sale_return"))
                cogs_total += rint(qty * cost)
                con.execute("UPDATE invoice_lines SET unit_cost = ? WHERE id = ?", (cost, ln["id"]))
            else:                                        # purchase_return
                _q, cost = stock_state(con, item["id"], upto_date=gdate)
                moves.append((item["id"], -qty, cost, "purchase_return"))
                cogs_total += rint(qty * cost)

        # --- ساخت سند حسابداری -------------------------------------------------
        net_sales = inv["subtotal"] - inv["discount"]
        jl: list[tuple] = []

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
            jl.append((A_SALES_RETURN, inv["subtotal"] - inv["discount"], 0, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_SALE, inv["vat_amount"], 0, None))
            if cogs_total:
                jl += [(A_INVENTORY, cogs_total, 0, None), (A_COGS, 0, cogs_total, None)]
            desc = f"برگشت از فروش شماره {inv['no']}"

        elif kind == "purchase":
            stock_part = 0
            expense_part = 0
            for ln in lines:
                item = get_item(con, ln["item_id"]) if ln["item_id"] else None
                if item and item["track_stock"]:
                    stock_part += ln["line_total"]
                else:
                    expense_part += ln["line_total"]
            if inv["discount"] and stock_part:
                stock_part -= inv["discount"]
            if stock_part:
                jl.append((A_INVENTORY, stock_part, 0, None))
            if expense_part:
                jl.append((A_EXPENSE_GENERAL, expense_part, 0, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_PURCHASE, inv["vat_amount"], 0, None))
            jl.append((A_SUPPLIERS, 0, inv["total"], party))
            desc = f"فاکتور خرید شماره {inv['no']}"

        else:                                            # purchase_return
            stock_part = 0
            expense_part = 0
            for ln in lines:
                item = get_item(con, ln["item_id"]) if ln["item_id"] else None
                if item and item["track_stock"]:
                    stock_part += ln["line_total"]
                else:
                    expense_part += ln["line_total"]
            if inv["discount"] and stock_part:
                stock_part -= inv["discount"]
            jl.append((A_SUPPLIERS, inv["total"], 0, party))
            if stock_part:
                jl.append((A_INVENTORY, 0, stock_part, None))
            if expense_part:
                jl.append((A_EXPENSE_GENERAL, 0, expense_part, None))
            if inv["vat_amount"]:
                jl.append((A_VAT_PURCHASE, 0, inv["vat_amount"], None))
            desc = f"برگشت از خرید شماره {inv['no']}"

        entry_id = post_entry(con, gdate, kind, jl, str(inv["no"]), desc)

        # --- ثبت حرکت‌های انبار ------------------------------------------------
        for item_id, qty, cost, mtype in moves:
            con.execute(
                """INSERT INTO stock_moves (item_id, move_date, qty, unit_cost, move_type,
                   ref_type, ref_id, description)
                   VALUES (?,?,?,?,?, 'invoice', ?, ?)""",
                (item_id, gdate, qty, cost, mtype, inv_id, desc),
            )

        con.execute(
            "UPDATE invoices SET status='confirmed', journal_entry_id=? WHERE id=?",
            (entry_id, inv_id),
        )
    db.audit(con, "confirm_invoice", "invoices", inv_id, f"{KIND_LABEL[kind]} #{inv['no']}")
    return entry_id


def cancel_invoice(con, inv_id: int, reason: str = "") -> None:
    """ابطال یک فاکتورِ قطعی‌شده با ثبت سند معکوس (حذف نمی‌کنیم!)"""
    inv = con.execute("SELECT * FROM invoices WHERE id = ?", (inv_id,)).fetchone()
    if not inv:
        raise AccountingError("فاکتور یافت نشد")
    if inv["status"] == "draft":
        con.execute("DELETE FROM invoice_lines WHERE invoice_id = ?", (inv_id,))
        con.execute("DELETE FROM invoices WHERE id = ?", (inv_id,))
        con.commit()
        return
    auth.require("invoice.cancel")
    if inv["status"] == "cancelled":
        raise AccountingError("این فاکتور قبلاً ابطال شده است")
    if inv["paid_amount"]:
        raise AccountingError(
            "این فاکتور دارای دریافت/پرداخت ثبت‌شده است؛ ابتدا آن‌ها را ابطال کنید"
        )

    with db.tx(con):
        entry = con.execute(
            "SELECT * FROM journal_lines WHERE entry_id = ?", (inv["journal_entry_id"],)
        ).fetchall()
        code_of = {r["account_id"]: r for r in entry}
        rev = []
        for r in entry:
            code = con.execute("SELECT code FROM accounts WHERE id = ?", (r["account_id"],)).fetchone()["code"]
            rev.append((code, r["credit"], r["debit"], r["party_id"]))

        entry_id = post_entry(con, inv["inv_date"], "adjustment", rev, str(inv["no"]),
                              f"ابطال {KIND_LABEL[inv['kind']]} شماره {inv['no']} — {reason}")

        for m in con.execute("SELECT * FROM stock_moves WHERE ref_type='invoice' AND ref_id=?", (inv_id,)):
            con.execute(
                """INSERT INTO stock_moves (item_id, move_date, qty, unit_cost, move_type,
                   ref_type, ref_id, description)
                   VALUES (?,?,?,?,?, 'invoice', ?, ?)""",
                (m["item_id"], inv["inv_date"], -m["qty"], m["unit_cost"], "adjust",
                 inv_id, f"ابطال فاکتور {inv['no']}"),
            )
        con.execute("UPDATE invoices SET status='cancelled' WHERE id=?", (inv_id,))
    db.audit(con, "cancel_invoice", "invoices", inv_id, reason)
    _ = code_of


def list_invoices(con, kind: str = "sale", date_from: str = "", date_to: str = "",
                  party_id: int | None = None, status: str = "") -> list[sqlite3.Row]:
    sql = """SELECT i.*, p.name AS party_name,
                    (i.total - i.paid_amount) AS remainder
             FROM invoices i JOIN parties p ON p.id = i.party_id
             WHERE i.kind = ?"""
    args: list = [kind]
    if date_from:
        sql += " AND i.inv_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND i.inv_date <= ?"
        args.append(date_to)
    if party_id:
        sql += " AND i.party_id = ?"
        args.append(party_id)
    if status:
        sql += " AND i.status = ?"
        args.append(status)
    sql += " ORDER BY i.inv_date DESC, i.no DESC"
    return con.execute(sql, args).fetchall()


def invoice_lines(con, inv_id: int) -> list[sqlite3.Row]:
    return con.execute(
        """SELECT l.*, i.name AS item_name, i.unit
           FROM invoice_lines l LEFT JOIN items i ON i.id = l.item_id
           WHERE l.invoice_id = ? ORDER BY l.id""",
        (inv_id,),
    ).fetchall()


# ===========================================================================
#  دریافت و پرداخت
# ===========================================================================
def add_payment(con, direction: str, party_id: int, amount: int, gdate: str,
                method: str = "cash", invoice_id: int | None = None,
                description: str = "") -> int:
    auth.require("payment.create")
    amount = int(amount)
    if amount <= 0:
        raise AccountingError("مبلغ باید بزرگ‌تر از صفر باشد")

    jdate = jalali.to_jalali_str(gdate)
    cur = con.cursor()
    with db.tx(con):
        no = db.next_no(con, "payment", jdate[:4])
        cur.execute(
            """INSERT INTO payments (no, direction, method, party_id, amount, pay_date,
               jalali_date, invoice_id, description)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (no, direction, method, party_id, amount, gdate, jdate, invoice_id, description),
        )
        pay_id = cur.lastrowid

        cash_acc = A_BANK if method in ("bank", "pos", "transfer") else A_CASH
        if direction == "receipt":                    # دریافت از مشتری
            lines = [(cash_acc, amount, 0, None), (A_CUSTOMERS, 0, amount, party_id)]
            desc = f"دریافت وجه شماره {no}"
        else:                                         # پرداخت به تامین‌کننده
            lines = [(A_SUPPLIERS, amount, 0, party_id), (cash_acc, 0, amount, None)]
            desc = f"پرداخت وجه شماره {no}"
        if description:
            desc += f" — {description}"

        entry_id = post_entry(con, gdate, direction, lines, str(no), desc)
        con.execute("UPDATE payments SET journal_entry_id = ? WHERE id = ?", (entry_id, pay_id))

        if invoice_id:
            con.execute(
                "UPDATE invoices SET paid_amount = paid_amount + ? WHERE id = ?",
                (amount, invoice_id),
            )
        db.audit(con, "add_payment", "payments", pay_id, f"{direction} {amount}")
    return pay_id


def cancel_payment(con, pay_id: int, reason: str = "") -> None:
    """ابطال دریافت/پرداخت با سند معکوس"""
    auth.require("payment.cancel")
    pay = con.execute("SELECT * FROM payments WHERE id = ?", (pay_id,)).fetchone()
    if not pay or pay["is_cancelled"]:
        raise AccountingError("این مورد قابل ابطال نیست")

    with db.tx(con):
        entry = con.execute(
            "SELECT * FROM journal_lines WHERE entry_id = ?", (pay["journal_entry_id"],)
        ).fetchall()
        rev = []
        for r in entry:
            code = con.execute("SELECT code FROM accounts WHERE id = ?", (r["account_id"],)).fetchone()["code"]
            rev.append((code, r["credit"], r["debit"], r["party_id"]))

        post_entry(con, pay["pay_date"], "adjustment", rev, str(pay["no"]),
                   f"ابطال رسید/پرداخت شماره {pay['no']} — {reason}")
        if pay["invoice_id"]:
            con.execute(
                "UPDATE invoices SET paid_amount = MAX(0, paid_amount - ?) WHERE id = ?",
                (pay["amount"], pay["invoice_id"]),
            )
        con.execute("UPDATE payments SET is_cancelled = 1 WHERE id = ?", (pay_id,))
    db.audit(con, "cancel_payment", "payments", pay_id, reason)


def list_payments(con, date_from: str = "", date_to: str = "",
                  party_id: int | None = None) -> list[sqlite3.Row]:
    sql = """SELECT p.*, pt.name AS party_name
             FROM payments p JOIN parties pt ON pt.id = p.party_id
             WHERE 1=1"""
    args: list = []
    if date_from:
        sql += " AND p.pay_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND p.pay_date <= ?"
        args.append(date_to)
    if party_id:
        sql += " AND p.party_id = ?"
        args.append(party_id)
    sql += " ORDER BY p.pay_date DESC, p.no DESC"
    return con.execute(sql, args).fetchall()


# ===========================================================================
#  گزارش‌ها
# ===========================================================================
def report_trial_balance(con) -> dict:
    rows = con.execute(
        "SELECT * FROM v_trial_balance WHERE debit <> 0 OR credit <> 0"
    ).fetchall()
    total_d = sum(r["debit"] for r in rows)
    total_c = sum(r["credit"] for r in rows)
    return {"rows": rows, "total_debit": total_d, "total_credit": total_c,
            "balanced": total_d == total_c}


def report_sales(con, date_from: str, date_to: str) -> dict:
    invs = con.execute(
        """SELECT i.*, p.name AS party_name
           FROM invoices i JOIN parties p ON p.id = i.party_id
           WHERE i.kind IN ('sale','sale_return') AND i.status='confirmed'
             AND i.inv_date BETWEEN ? AND ?
           ORDER BY i.inv_date, i.no""",
        (date_from, date_to),
    ).fetchall()
    total_sale = total_return = total_vat = total_cogs = 0
    detail = []
    for inv in invs:
        cogs = sum(rint(r["qty"] * r["unit_cost"])
                   for r in con.execute(
                       "SELECT qty, unit_cost FROM invoice_lines WHERE invoice_id = ?",
                       (inv["id"],)))
        net = inv["subtotal"] - inv["discount"]
        if inv["kind"] == "sale":
            total_sale += net
            total_cogs += cogs
        else:
            total_return += net
            total_cogs -= cogs
        total_vat += inv["vat_amount"] if inv["kind"] == "sale" else -inv["vat_amount"]
        detail.append({"inv": inv, "net": net, "cogs": cogs,
                       "gross_profit": (net if inv["kind"] == "sale" else -net) - cogs})
    net_sales = total_sale - total_return
    return {"detail": detail, "gross_sales": total_sale, "returns": total_return,
            "net_sales": net_sales, "cogs": total_cogs, "vat": total_vat,
            "gross_profit": net_sales - total_cogs,
            "margin": (100.0 * (net_sales - total_cogs) / net_sales) if net_sales else 0.0}


def report_stock(con) -> dict:
    rows = []
    total_value = 0
    for it in con.execute(
        "SELECT * FROM items WHERE track_stock = 1 AND is_active = 1 ORDER BY name"
    ):
        qty, cost = stock_state(con, it["id"])
        value = rint(qty * cost)
        total_value += value
        rows.append({"item": it, "qty": qty, "avg_cost": cost, "value": value,
                     "low": qty <= float(it["stock_min"])})
    return {"rows": rows, "total_value": total_value}


def report_customers(con, kind: str = "customer") -> dict:
    rows = []
    total = 0
    for p in con.execute(
        """SELECT p.*, COALESCE(b.balance,0) AS balance
           FROM parties p LEFT JOIN v_party_balance b ON b.party_id = p.id
           WHERE p.is_active = 1 AND (p.kind = ? OR p.kind = 'both')
           ORDER BY balance DESC, p.name""",
        (kind,),
    ):
        unpaid = con.execute(
            """SELECT COUNT(*) c, COALESCE(SUM(total - paid_amount),0) s
               FROM invoices WHERE party_id = ? AND status='confirmed'
               AND kind = ? AND (total - paid_amount) > 0""",
            (p["id"], "sale" if kind == "customer" else "purchase"),
        ).fetchone()
        rows.append({"party": p, "balance": p["balance"],
                     "open_invoices": unpaid["c"], "open_amount": unpaid["s"]})
        total += p["balance"]
    return {"rows": rows, "total": total}


def report_profit_loss(con, date_from: str, date_to: str) -> dict:
    def bal(codes, sign=1):
        tot = 0
        for c in codes:
            row = con.execute(
                """SELECT COALESCE(SUM(CASE WHEN e.status='posted' THEN l.credit - l.debit END),0) v
                   FROM journal_lines l
                   JOIN journal_entries e ON e.id = l.entry_id
                   JOIN accounts a ON a.id = l.account_id
                   WHERE a.code = ? AND e.entry_date BETWEEN ? AND ?""",
                (c, date_from, date_to),
            ).fetchone()
            tot += row["v"]
        return tot * sign

    # ۴۰۳ (برگشت از فروش و تخفیفات) ماهیتِ معکوسِ درآمد دارد:
    # چون bal بر اساس «بستانکار منهای بدهکار» است، اثرِ آن با جمع (+) لحاظ می‌شود
    revenue = bal([A_SALES, A_SERVICES]) + bal([A_SALES_RETURN])
    cogs = -bal([A_COGS])          # هزینه‌ها ماندهٔ بدهکار دارند
    expenses = -bal([A_EXPENSE_GENERAL, "503", "504"])
    return {"revenue": revenue, "cogs": cogs, "gross_profit": revenue - cogs,
            "expenses": expenses, "net_profit": revenue - cogs - expenses}


def report_ledger(con, account_code: str, date_from: str = "", date_to: str = "") -> list[sqlite3.Row]:
    sql = """SELECT e.jalali_date, e.no, e.entry_type, e.reference_no,
                    e.description AS entry_desc, l.debit, l.credit,
                    p.name AS party_name
             FROM journal_lines l
             JOIN journal_entries e ON e.id = l.entry_id
             JOIN accounts a ON a.id = l.account_id
             LEFT JOIN parties p ON p.id = l.party_id
             WHERE a.code = ? AND e.status='posted'"""
    args: list = [account_code]
    if date_from:
        sql += " AND e.entry_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND e.entry_date <= ?"
        args.append(date_to)
    sql += " ORDER BY e.entry_date, e.no"
    return con.execute(sql, args).fetchall()


def dashboard(con) -> dict:
    """اعداد کلیدی برای صفحهٔ اصلی"""
    today = date.today().isoformat()
    jy = jalali.gregorian_to_jalali(date.today().year, date.today().month, date.today().day)[0]
    y_start = jalali.start_of_jalali_year(jy)
    sales = report_sales(con, y_start, today)
    stock = report_stock(con)
    cust = report_customers(con, "customer")
    sup = report_customers(con, "supplier")
    tb = report_trial_balance(con)
    cash = con.execute(
        """SELECT COALESCE(SUM(debit - credit),0) v FROM journal_lines l
           JOIN journal_entries e ON e.id = l.entry_id
           JOIN accounts a ON a.id = l.account_id
           WHERE a.code IN (?,?) AND e.status='posted'""",
        (A_CASH, A_BANK),
    ).fetchone()["v"]
    return {"sales": sales, "stock": stock, "customers": cust, "suppliers": sup,
            "cash": cash, "trial": tb, "jalali_year": jy, "cheques": cheques_summary(con)}


# ===========================================================================
#  چک‌های دریافتنی و پرداختنی
# ===========================================================================
CHEQUE_STATUS = {
    "pending": "در جریان وصول",
    "cleared": "وصول / پرداخت شده",
    "bounced": "برگشت خورده",
    "cancelled": "ابطال شده",
}


def add_cheque(con, cheque_type: str, party_id: int, serial_no: str, amount: int,
               issue_g: str, due_g: str, bank_name: str = "", branch: str = "",
               sayad_id: str = "", description: str = "") -> int:
    """
    ثبت چکِ جدید.
      چک دریافتنی:  بدهکار «اسناد دریافتنی»  /  بستانکار «مشتریان»
      چک پرداختنی:  بدهکار «تامین‌کنندگان»  /  بستانکار «اسناد پرداختنی»
    """
    auth.require("cheque.create")
    amount = int(amount)
    if amount <= 0:
        raise AccountingError("مبلغ چک باید بزرگ‌تر از صفر باشد")
    serial_no = (serial_no or "").strip()
    if not serial_no:
        raise AccountingError("شماره سریال چک الزامی است")
    if con.execute("SELECT 1 FROM cheques WHERE cheque_type=? AND serial_no=?",
                   (cheque_type, serial_no)).fetchone():
        raise AccountingError(f"چک با سریال {serial_no} قبلاً ثبت شده است")

    party = get_party(con, party_id)
    with db.tx(con):
        if cheque_type == "received":
            lines = [(A_NOTES_RECEIVABLE, amount, 0, party_id),
                     (A_CUSTOMERS, 0, amount, party_id)]
            desc = f"چک دریافتنی شماره {serial_no} — {party['name']}"
        else:
            lines = [(A_SUPPLIERS, amount, 0, party_id),
                     (A_NOTES_PAYABLE, 0, amount, None)]
            desc = f"چک پرداختنی شماره {serial_no} — {party['name']}"
        entry_id = post_entry(con, issue_g, "general", lines, serial_no, desc)
        cur = con.execute(
            """INSERT INTO cheques (cheque_type, serial_no, bank_name, branch, amount,
               issue_date, due_date, jalali_issue, jalali_due, party_id, status,
               sayad_id, description, journal_entry_id)
               VALUES (?,?,?,?,?,?,?,?,?,?, 'pending',?,?,?)""",
            (cheque_type, serial_no, bank_name, branch, amount, issue_g, due_g,
             jalali.to_jalali_str(issue_g), jalali.to_jalali_str(due_g), party_id,
             sayad_id, description, entry_id))
        cheque_id = cur.lastrowid
        db.audit(con, "add_cheque", "cheques", cheque_id, desc)
    return cheque_id


def _reverse_entry_lines(con, entry_id: int) -> list[tuple]:
    """ساخت سطرهای سندِ معکوس برای یک سند موجود"""
    rev = []
    for r in con.execute("SELECT * FROM journal_lines WHERE entry_id = ?", (entry_id,)):
        code = con.execute("SELECT code FROM accounts WHERE id = ?",
                           (r["account_id"],)).fetchone()["code"]
        rev.append((code, r["credit"], r["debit"], r["party_id"]))
    return rev


def clear_cheque(con, cheque_id: int, method: str = "bank", gdate: str = "") -> int:
    """وصول چک دریافتنی (یا پرداختِ چک پرداختنی توسط بانک)"""
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id = ?", (cheque_id,)).fetchone()
    if not ch:
        raise AccountingError("چک یافت نشد")
    if ch["status"] != "pending":
        raise AccountingError("فقط چک‌های «در جریان وصول» قابل وصول/پرداخت هستند")

    gdate = gdate or ch["due_date"]
    cash_acc = A_BANK if method == "bank" else A_CASH
    if ch["cheque_type"] == "received":
        lines = [(cash_acc, ch["amount"], 0, None),
                 (A_NOTES_RECEIVABLE, 0, ch["amount"], ch["party_id"])]
        desc = f"وصول چک دریافتنی شماره {ch['serial_no']}"
    else:
        lines = [(A_NOTES_PAYABLE, ch["amount"], 0, None),
                 (cash_acc, 0, ch["amount"], None)]
        desc = f"پرداخت چک شماره {ch['serial_no']}"

    with db.tx(con):
        entry_id = post_entry(con, gdate, "general", lines, ch["serial_no"], desc)
        con.execute("UPDATE cheques SET status='cleared', cleared_entry_id=? WHERE id=?",
                    (entry_id, cheque_id))
        db.audit(con, "clear_cheque", "cheques", cheque_id, desc)
    return entry_id


def bounce_cheque(con, cheque_id: int, gdate: str = "") -> int:
    """
    برگشت خوردن چک:
      چک دریافتنی → مبلغ دوباره به بدهی مشتری برمی‌گردد
      چک پرداختنی → وصولِ آن از حساب بانک برگشت می‌خورد و چک همچنان بدهی باقی می‌ماند
    """
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id = ?", (cheque_id,)).fetchone()
    if not ch:
        raise AccountingError("چک یافت نشد")
    if ch["status"] not in ("pending", "cleared"):
        raise AccountingError("این چک قابل برگشت‌زدن نیست")
    gdate = gdate or date.today().isoformat()

    with db.tx(con):
        if ch["status"] == "cleared":            # ابتدا اثرِ وصول را برمی‌گردانیم
            rev = _reverse_entry_lines(con, ch["cleared_entry_id"])
            post_entry(con, gdate, "adjustment", rev, ch["serial_no"],
                       f"برگشت از وصول چک شماره {ch['serial_no']}")

        if ch["cheque_type"] == "received":
            lines = [(A_CUSTOMERS, ch["amount"], 0, ch["party_id"]),
                     (A_NOTES_RECEIVABLE, 0, ch["amount"], ch["party_id"])]
        else:
            lines = [(A_BANK, ch["amount"], 0, None),
                     (A_NOTES_PAYABLE, 0, ch["amount"], None)]
        entry_id = post_entry(con, gdate, "general", lines, ch["serial_no"],
                              f"برگشت خوردن چک شماره {ch['serial_no']}")
        con.execute("UPDATE cheques SET status='bounced' WHERE id=?", (cheque_id,))
        db.audit(con, "bounce_cheque", "cheques", cheque_id)
    return entry_id


def cancel_cheque(con, cheque_id: int, reason: str = "") -> int:
    """ابطال چکِ در جریان با سند معکوس"""
    auth.require("cheque.update")
    ch = con.execute("SELECT * FROM cheques WHERE id = ?", (cheque_id,)).fetchone()
    if not ch:
        raise AccountingError("چک یافت نشد")
    if ch["status"] != "pending":
        raise AccountingError("فقط چک‌های «در جریان وصول» قابل ابطال هستند")
    rev = _reverse_entry_lines(con, ch["journal_entry_id"])
    with db.tx(con):
        entry_id = post_entry(con, ch["issue_date"], "adjustment", rev, ch["serial_no"],
                              f"ابطال چک شماره {ch['serial_no']} — {reason}")
        con.execute("UPDATE cheques SET status='cancelled' WHERE id=?", (cheque_id,))
        db.audit(con, "cancel_cheque", "cheques", cheque_id, reason)
    return entry_id


def list_cheques(con, cheque_type: str = "", status: str = "",
                 date_from: str = "", date_to: str = "") -> list[sqlite3.Row]:
    sql = """SELECT c.*, p.name AS party_name FROM cheques c
             JOIN parties p ON p.id = c.party_id WHERE 1=1"""
    args: list = []
    if cheque_type:
        sql += " AND c.cheque_type = ?"
        args.append(cheque_type)
    if status:
        sql += " AND c.status = ?"
        args.append(status)
    if date_from:
        sql += " AND c.due_date >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND c.due_date <= ?"
        args.append(date_to)
    sql += " ORDER BY c.due_date"
    return con.execute(sql, args).fetchall()


def cheques_summary(con) -> dict:
    """خلاصهٔ وضعیت چک‌ها برای داشبورد"""
    out = {"received_pending": 0, "received_count": 0, "paid_pending": 0, "paid_count": 0,
           "due_soon": 0, "overdue": 0, "due_soon_list": [], "overdue_list": []}
    today = date.today().isoformat()
    for c in con.execute("SELECT * FROM cheques WHERE status = 'pending'"):
        if c["cheque_type"] == "received":
            out["received_pending"] += c["amount"]
            out["received_count"] += 1
        else:
            out["paid_pending"] += c["amount"]
            out["paid_count"] += 1
        if c["due_date"] < today:
            out["overdue"] += 1
            out["overdue_list"].append(c)
        elif (date.fromisoformat(c["due_date"]) - date.today()).days <= 7:
            out["due_soon"] += 1
            out["due_soon_list"].append(c)
    return out


# ===========================================================================
#  سنوات بدهی (Aging)
# ===========================================================================
def report_aging(con, kind: str = "customer") -> dict:
    """
    تفکیک مطالبات/بدهی‌های باز در بازه‌های ۳۰/۶۰/۹۰/+۹۰ روز.
    ملاکِ سررسید: تاریخ سررسید فاکتور و در صورت نبود، تاریخ فاکتور + مهلت پیش‌فرض.
    """
    term = int(db.get_setting(con, "default_term_days", "30") or 30)
    inv_kind = "sale" if kind == "customer" else "purchase"
    today = date.today()
    rows = con.execute(
        """SELECT i.id, i.no, i.jalali_date, i.due_date, i.inv_date, i.total,
                  i.paid_amount, i.party_id, p.name AS party_name
           FROM invoices i JOIN parties p ON p.id = i.party_id
           WHERE i.kind = ? AND i.status = 'confirmed'
             AND (i.total - i.paid_amount) > 0
           ORDER BY i.due_date, i.inv_date""", (inv_kind,)).fetchall()

    parties: dict[int, dict] = {}
    for r in rows:
        due = r["due_date"] or (
            date.fromisoformat(r["inv_date"]) + __import__("datetime").timedelta(days=term)
        ).isoformat()
        days = (today - date.fromisoformat(due)).days
        remain = r["total"] - r["paid_amount"]
        bucket = "current" if days <= 0 else ("d1_30" if days <= 30 else
                                              ("d31_60" if days <= 60 else
                                               ("d61_90" if days <= 90 else "d90_plus")))
        rec = parties.setdefault(r["party_id"], {
            "party_id": r["party_id"], "party_name": r["party_name"],
            "current": 0, "d1_30": 0, "d31_60": 0, "d61_90": 0, "d90_plus": 0,
            "total": 0, "invoices": 0})
        rec[bucket] += remain
        rec["total"] += remain
        rec["invoices"] += 1

    result = sorted(parties.values(), key=lambda x: -x["total"])
    return {"rows": result, "total": sum(r["total"] for r in result),
            "buckets": {k: sum(r[k] for r in result)
                        for k in ("current", "d1_30", "d31_60", "d61_90", "d90_plus")}}
