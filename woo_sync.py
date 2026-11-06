# -*- coding: utf-8 -*-
"""همگام‌سازی عملیاتی WooCommerce ↔ حسابداری.

- REST API از wc/v3 و HTTPS استفاده می‌کند.
- تغییرات خروجی در صف محلی هستند؛ خطای شبکه باعث گم‌شدن تراکنش محلی نمی‌شود.
- سفارش فروش آنلاین بعد از import با repo ثبت می‌شود تا سند دوبلری ساخته شود.
- قاعدهٔ موجودی: دفتر حسابداری مرجع است؛ موجودی سایت از دفتر به‌روزرسانی می‌شود.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import auth
import db
import repo
import sync_outbox
from woocommerce import WooClient, WooError


def client_from_settings(con) -> WooClient:
    url = db.get_setting(con, "woo_url", "").strip()
    if not url.lower().startswith("https://"):
        raise WooError(
            "اتصال واقعی فروشگاه فقط با HTTPS مجاز است؛ کلید API را روی HTTP ارسال نکنید."
        )
    key = db.get_setting(con, "woo_consumer_key", "").strip()
    secret = db.get_setting(con, "woo_consumer_secret", "")
    return WooClient(
        url,
        key,
        secret,
        query_auth=db.get_setting(con, "woo_query_auth", "0") == "1",
        timeout=15,
        retries=1,
    )


def price_factor(con) -> int:
    try:
        factor = int(db.get_setting(con, "woo_price_factor", "10"))
    except ValueError:
        factor = 10
    if factor not in (1, 10, 100):
        raise WooError("ضریب تبدیل قیمت باید ۱، ۱۰ یا ۱۰۰ باشد")
    return factor


def _money(value) -> Decimal:
    try:
        n = Decimal(str(value or "0"))
    except InvalidOperation as e:
        raise WooError(f"مبلغ ووکامرس نامعتبر است: {value}") from e
    if not n.is_finite():
        raise WooError("مبلغ ووکامرس نامعتبر است")
    return n


def _hash(data: dict) -> str:
    packed = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(packed.encode()).hexdigest()


def _map_by_sku(con, sku):
    if not sku:
        return None
    return con.execute("SELECT * FROM items WHERE code=?", (str(sku),)).fetchone()


def _ensure_product(con, client, product: dict, factor: int, *, pull_fields=True):
    remote_id = int(product["id"])
    mapping = sync_outbox.map_remote(con, "product", remote_id)
    item = (
        con.execute("SELECT * FROM items WHERE id=?", (mapping["local_id"],)).fetchone()
        if mapping
        else None
    )
    sku = str(product.get("sku") or "").strip()
    if item is None:
        item = _map_by_sku(con, sku)
    if item is None:
        name = str(product.get("name") or f"کالای ووکامرس {remote_id}").strip()
        price = int((_money(product.get("price")) * factor).quantize(Decimal("1")))
        item_id = repo.save_item(
            con,
            None,
            {
                "code": sku or f"WC-{remote_id}",
                "name": name,
                "sale_price": max(0, price),
                "purchase_price": 0,
                "vat_rate": 0,
                "track_stock": True,
                "stock_min": 0,
                "is_active": product.get("status", "publish") != "trash",
            },
        )
        item = con.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    elif pull_fields:
        # Woo product metadata (name/price/active) is synchronized; stock remains ledger-owned.
        name = str(product.get("name") or item["name"]).strip()
        price = int((_money(product.get("price")) * factor).quantize(Decimal("1")))
        # SKU becomes the canonical code only if unique/valid; don't overwrite user code.
        repo.save_item(
            con,
            item["id"],
            {
                "code": item["code"],
                "name": name,
                "sale_price": max(0, price),
                "purchase_price": item["purchase_price"],
                "vat_rate": item["vat_rate"],
                "track_stock": bool(item["track_stock"]),
                "stock_min": item["stock_min"],
                "is_active": product.get("status", "publish") != "trash",
            },
        )
        item = con.execute("SELECT * FROM items WHERE id=?", (item["id"],)).fetchone()
    sync_outbox.put_map(
        con,
        "product",
        item["id"],
        remote_id,
        remote_parent_id=product.get("parent_id") or None,
        remote_updated=product.get("date_modified_gmt") or "",
        local_hash=_hash(dict(item)),
        remote_hash=_hash(product),
    )
    return item


def _product_body(con, item):
    mapping = sync_outbox.map_local(con, "product", item["id"])
    data = {
        "sku": item["code"] or f"ACC-{item['id']}",
        "regular_price": str(
            Decimal(int(item["sale_price"])) / Decimal(price_factor(con))
        ),
    }
    if not mapping or not mapping["remote_parent_id"]:
        data.update(
            {
                "name": item["name"],
                "type": "simple",
                "status": "publish" if item["is_active"] else "draft",
            }
        )
    if db.get_setting(con, "woo_sync_stock", "1") == "1":
        data["manage_stock"] = bool(item["track_stock"])
        if item["track_stock"]:
            qty = Decimal(str(repo.stock_state(con, item["id"])[0]))
            if qty != qty.to_integral_value():
                raise WooError(
                    "ووکامرس موجودی را عدد صحیح می‌خواهد؛ موجودی اعشاری را پیش از sync بررسی کنید."
                )
            data["stock_quantity"] = int(qty)
    if mapping:
        data.pop("type", None)
    return data


def _customer_for_order(con, order: dict):
    cid = int(order.get("customer_id") or 0)
    if cid:
        mapping = sync_outbox.map_remote(con, "customer", cid)
        if mapping:
            party = repo.get_party(con, mapping["local_id"])
            if party:
                return party["id"]
    billing = order.get("billing") or {}
    name = " ".join(
        x for x in (billing.get("first_name"), billing.get("last_name")) if x
    ).strip()
    name = (
        name
        or billing.get("company")
        or billing.get("email")
        or f"مشتری ووکامرس {cid or order['id']}"
    )
    phone = str(billing.get("phone") or "").strip()
    email = str(billing.get("email") or "").strip().lower()
    party = (
        con.execute(
            """SELECT p.id FROM parties p WHERE p.phone=? AND p.is_active=1
               AND NOT EXISTS (SELECT 1 FROM woo_map m WHERE m.entity='customer' AND m.local_id=p.id)
               LIMIT 1""",
            (phone,),
        ).fetchone()
        if phone
        else None
    )
    if party:
        party_id = party["id"]
        old_party = repo.get_party(con, party_id)
        repo.save_party(
            con,
            party_id,
            {
                "code": old_party["code"],
                "name": name,
                "kind": old_party["kind"],
                "phone": phone or old_party["phone"],
                "email": email or old_party["email"],
                "address": old_party["address"],
                "national_id": old_party["national_id"],
                "economic_code": old_party["economic_code"],
                "postal_code": old_party["postal_code"],
                "credit_limit": old_party["credit_limit"],
                "note": old_party["note"],
            },
        )
    else:
        addr = billing
        party_id = repo.save_party(
            con,
            None,
            {
                "name": name,
                "kind": "customer",
                "phone": phone,
                "email": email,
                "address": "، ".join(
                    x
                    for x in (
                        addr.get("address_1"),
                        addr.get("address_2"),
                        addr.get("city"),
                        addr.get("state"),
                        addr.get("postcode"),
                    )
                    if x
                ),
            },
        )
    if cid:
        sync_outbox.put_map(
            con,
            "customer",
            party_id,
            cid,
            remote_updated=order.get("date_modified_gmt") or "",
        )
    return party_id


def _order_lines(con, order: dict, client, factor: int):
    lines = []
    rows = order.get("line_items") or []
    for line in rows:
        qty = Decimal(str(line.get("quantity") or 0))
        if qty <= 0:
            continue
        parent_pid = int(line.get("product_id") or 0)
        variation_id = int(line.get("variation_id") or 0)
        pid = variation_id or parent_pid
        product = sync_outbox.map_remote(con, "product", pid) if pid else None
        item = (
            con.execute(
                "SELECT * FROM items WHERE id=?", (product["local_id"],)
            ).fetchone()
            if product
            else None
        )
        if item is None and pid:
            try:
                remote_product = (
                    client.get(f"products/{parent_pid}/variations/{variation_id}")
                    if variation_id
                    else client.get(f"products/{pid}")
                )
                if variation_id:
                    remote_product["parent_id"] = parent_pid
                    parent = client.get(f"products/{parent_pid}")
                    attrs = " / ".join(
                        str(a.get("option") or "")
                        for a in remote_product.get("attributes", [])
                        if a.get("option")
                    )
                    remote_product["name"] = str(parent.get("name") or "محصول") + (
                        f" — {attrs}" if attrs else f" — تنوع {variation_id}"
                    )
                item = _ensure_product(con, client, remote_product, factor)
            except WooError:
                item = None
        if item is None:
            sku = str(line.get("sku") or "")
            item = _map_by_sku(con, sku)
        if item is None and pid:
            raise WooError(
                f"محصول ووکامرس {pid} به کالای محلی تطبیق داده نشد؛ SKU را بررسی و موجودی افتتاحیه/بهای کالا را ثبت کنید."
            )
        gross = _money(line.get("subtotal"))
        net = _money(line.get("total"))
        tax = _money(line.get("total_tax"))
        # Woo’s decimal price is converted to integer rials; line discount is pre-tax.
        unit = int((gross * factor / qty).quantize(Decimal("1")))
        discount = int(((gross - net) * factor).quantize(Decimal("1")))
        rate = (tax / net * Decimal(100)) if net else Decimal(0)
        rate = min(Decimal(100), max(Decimal(0), rate))
        lines.append(
            {
                "item_id": item["id"] if item else None,
                "description": str(
                    line.get("name") or (item["name"] if item else "قلم سفارشی")
                ),
                "qty": str(qty),
                "unit_price": max(0, unit),
                "discount": max(0, discount),
                "vat_rate": float(rate),
            }
        )
    for extra in order.get("shipping_lines", []) + order.get("fee_lines", []):
        amount = _money(extra.get("total"))
        tax = _money(extra.get("total_tax"))
        if amount or tax:
            name = str(extra.get("method_title") or extra.get("name") or "هزینه سفارش")
            lines.append(
                {
                    "item_id": None,
                    "description": name,
                    "qty": "1",
                    "unit_price": int(amount * factor),
                    "discount": 0,
                    "vat_rate": float(tax / amount * 100) if amount else 0,
                }
            )
    if not lines:
        raise WooError("سفارش هیچ قلم قابل ثبت ندارد")
    return lines


def import_order(con, client, order: dict, factor: int) -> int:
    remote_id = int(order["id"])
    mapped = sync_outbox.map_remote(con, "order", remote_id)
    status = str(order.get("status") or "")
    if mapped:
        invoice_id = int(mapped["local_id"])
        invoice = con.execute(
            "SELECT * FROM invoices WHERE id=?", (invoice_id,)
        ).fetchone()
        if not invoice:
            raise WooError(f"نقشهٔ سفارش {remote_id} به فاکتور ناموجود اشاره می‌کند")
        if status in ("cancelled", "failed", "refunded", "trash", "deleted"):
            sync_outbox.log(
                con,
                "in",
                "order",
                "review",
                f"سفارش {status} شده؛ برای حفظ سند قطعی، ابطال/برگشت خودکار انجام نشد",
                remote_id,
                invoice_id,
            )
            return invoice_id
        if (
            status in ("processing", "completed")
            and invoice["paid_amount"] < invoice["total"]
        ):
            amount = int((_money(order.get("total")) * factor).quantize(Decimal("1")))
            if amount != int(invoice["total"]):
                raise WooError(
                    f"سفارش تغییر کرده است: جمع سایت {amount} و فاکتور {invoice['total']}؛ اصلاح دستی لازم است"
                )
            with auth.service_mode():
                repo.add_payment(
                    con,
                    "receipt",
                    invoice["party_id"],
                    int(invoice["total"]) - int(invoice["paid_amount"]),
                    datetime.now().date().isoformat(),
                    "bank",
                    invoice_id,
                    f"تسویهٔ سفارش ووکامرس #{remote_id}",
                )
            sync_outbox.log(
                con,
                "in",
                "order",
                "done",
                "وصول وجه برای سفارش موجود ثبت شد",
                remote_id,
                invoice_id,
            )
        sync_outbox.put_map(
            con,
            "order",
            invoice_id,
            remote_id,
            remote_updated=order.get("date_modified_gmt") or "",
        )
        return invoice_id
    if status in ("cancelled", "failed", "refunded", "trash"):
        sync_outbox.log(
            con,
            "in",
            "order",
            "skipped",
            f"وضعیت سفارش {status} است",
            remote_id=remote_id,
        )
        return 0
    party = _customer_for_order(con, order)
    lines = _order_lines(con, order, client, factor)
    date_src = str(order.get("date_created_gmt") or order.get("date_created") or "")
    try:
        gdate = (
            datetime.fromisoformat(date_src.replace("Z", "+00:00")).date().isoformat()
        )
        db.validate_gdate(gdate)
    except Exception:
        gdate = datetime.now().date().isoformat()
    inv_id = repo.save_invoice(
        con,
        None,
        {
            "kind": "sale",
            "party_id": party,
            "gregorian_date": gdate,
            "description": f"سفارش ووکامرس #{remote_id}",
        },
        lines,
    )
    repo.confirm_invoice(con, inv_id)
    amount = int((_money(order.get("total")) * factor).quantize(Decimal("1")))
    invoice = con.execute("SELECT total FROM invoices WHERE id=?", (inv_id,)).fetchone()
    if status in ("processing", "completed") and amount > 0:
        # Prefer source invoice totals; tax/rounding discrepancies are surfaced, not silently hidden.
        if abs(amount - int(invoice["total"])) > max(2, factor):
            raise WooError(
                f"جمع سفارش ({amount}) با فاکتور محاسبه‌شده ({invoice['total']}) تطبیق ندارد؛ فاکتور ثبت نشد"
            )
        repo.add_payment(
            con,
            "receipt",
            party,
            min(amount, int(invoice["total"])),
            gdate,
            "bank",
            inv_id,
            f"ووکامرس #{remote_id}",
        )
    sync_outbox.put_map(
        con,
        "order",
        inv_id,
        remote_id,
        remote_updated=order.get("date_modified_gmt") or "",
    )
    sync_outbox.log(
        con, "in", "order", "done", f"فاکتور داخلی {inv_id}", remote_id, inv_id
    )
    return inv_id


def import_customer(con, remote: dict) -> int:
    rid = int(remote["id"])
    mapped = sync_outbox.map_remote(con, "customer", rid)
    billing = remote.get("billing") or {}
    name = " ".join(
        x for x in (remote.get("first_name"), remote.get("last_name")) if x
    ).strip()
    if mapped:
        party = repo.get_party(con, mapped["local_id"])
        if party:
            repo.save_party(
                con,
                party["id"],
                {
                    "code": party["code"],
                    "name": name or party["name"],
                    "kind": party["kind"],
                    "phone": billing.get("phone") or party["phone"],
                    "email": remote.get("email") or party["email"],
                    "address": billing.get("address_1") or party["address"],
                    "national_id": party["national_id"],
                    "economic_code": party["economic_code"],
                    "postal_code": party["postal_code"],
                    "credit_limit": party["credit_limit"],
                    "note": party["note"],
                },
            )
            return party["id"]
    phone = str(billing.get("phone") or "").strip()
    existing = (
        con.execute(
            """SELECT p.id FROM parties p WHERE p.phone=? AND p.is_active=1
               AND NOT EXISTS (SELECT 1 FROM woo_map m WHERE m.entity='customer' AND m.local_id=p.id)
               LIMIT 1""",
            (phone,),
        ).fetchone()
        if phone
        else None
    )
    if existing:
        pid = existing["id"]
        party = repo.get_party(con, pid)
        repo.save_party(
            con,
            pid,
            {
                "code": party["code"],
                "name": name or party["name"],
                "kind": party["kind"],
                "phone": phone or party["phone"],
                "email": remote.get("email") or party["email"],
                "address": billing.get("address_1") or party["address"],
                "national_id": party["national_id"],
                "economic_code": party["economic_code"],
                "postal_code": party["postal_code"],
                "credit_limit": party["credit_limit"],
                "note": party["note"],
            },
        )
    else:
        pid = repo.save_party(
            con,
            None,
            {
                "name": name or f"مشتری ووکامرس {rid}",
                "kind": "customer",
                "phone": phone,
                "email": remote.get("email"),
                "address": billing.get("address_1"),
            },
        )
    sync_outbox.put_map(
        con, "customer", pid, rid, remote_updated=remote.get("date_modified_gmt") or ""
    )
    return pid


def _pull_customers(con, client):
    if db.get_setting(con, "woo_sync_customers", "1") != "1":
        return 0
    state = sync_outbox.get_state(con, "customers_modified_after", "")
    params = {"orderby": "registered_date", "order": "asc"}
    if state:
        params["modified_after"] = state
    customers = client.list_all("customers", per_page=100, **params)
    latest = state
    for customer in customers:
        with db.tx(con):
            import_customer(con, customer)
        latest = max(latest, str(customer.get("date_modified_gmt") or ""))
    if latest:
        sync_outbox.set_state(con, "customers_modified_after", latest)
    return len(customers)


def _pull_products(con, client, factor):
    if db.get_setting(con, "woo_sync_products", "1") != "1":
        return 0
    state = sync_outbox.get_state(con, "products_modified_after", "")
    params = {"orderby": "modified", "order": "asc"}
    if state:
        params["modified_after"] = state
    products = client.list_all("products", per_page=100, **params)
    count = 0
    latest = state
    expanded = []
    for product in products:
        if product.get("type") == "variable":
            parent_name = str(product.get("name") or "")
            for variation in client.list_all(
                f"products/{int(product['id'])}/variations", per_page=100
            ):
                variation["parent_id"] = int(product["id"])
                attrs = " / ".join(
                    str(a.get("option") or "")
                    for a in variation.get("attributes", [])
                    if a.get("option")
                )
                variation["name"] = parent_name + (
                    f" — {attrs}" if attrs else f" — تنوع {variation['id']}"
                )
                expanded.append(variation)
        else:
            expanded.append(product)
    for product in expanded:
        with db.tx(con):
            _ensure_product(con, client, product, factor)
            sync_outbox.log(
                con,
                "in",
                "product",
                "done",
                str(product.get("name", "")),
                int(product["id"]),
            )
        count += 1
        latest = max(latest, str(product.get("date_modified_gmt") or ""))
    if latest:
        sync_outbox.set_state(con, "products_modified_after", latest)
    return count


def _pull_orders(con, client, factor):
    if db.get_setting(con, "woo_sync_orders", "1") != "1":
        return 0
    state = sync_outbox.get_state(con, "orders_modified_after", "")
    params = {"orderby": "date", "order": "asc", "status": "any"}
    if not state:
        # First run is forward-only by default, to avoid importing an entire historical store unexpectedly.
        state = db.get_setting(con, "woo_sync_from", "").strip()
        if not state:
            state = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        sync_outbox.set_state(con, "orders_modified_after", state)
    if state:
        params["modified_after"] = state
    orders = client.list_all("orders", per_page=100, **params)
    count, latest = 0, state
    for order in orders:
        try:
            with auth.service_mode():
                with db.tx(con):
                    import_order(con, client, order, factor)
            count += 1
        except Exception as e:
            sync_outbox.log(
                con, "in", "order", "error", str(e), int(order.get("id") or 0)
            )
        latest = max(latest, str(order.get("date_modified_gmt") or ""))
    if latest:
        # Woo modified_after is exclusive/second-resolution; subtract one second to avoid misses.
        try:
            dt = datetime.fromisoformat(latest.replace("Z", "+00:00"))
            sync_outbox.set_state(
                con,
                "orders_modified_after",
                (
                    dt.replace(tzinfo=timezone.utc)
                    - __import__("datetime").timedelta(seconds=1)
                )
                .isoformat()
                .replace("+00:00", ""),
            )
        except Exception:
            sync_outbox.set_state(con, "orders_modified_after", latest)
    return count


def _push_queue(con, client, factor):
    rows = con.execute(
        "SELECT * FROM woo_queue WHERE status IN ('pending','error') AND attempts<8 ORDER BY id LIMIT 50"
    ).fetchall()
    count = 0
    for row in rows:
        try:
            if row["entity"] in ("party", "customer"):
                if db.get_setting(con, "woo_sync_customers", "1") != "1":
                    con.execute(
                        "UPDATE woo_queue SET status='skipped',last_error='همگام‌سازی مشتریان غیرفعال است',updated_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    continue
                party = repo.get_party(con, row["local_id"])
                if not party or party["kind"] not in ("customer", "both"):
                    con.execute(
                        "UPDATE woo_queue SET status='skipped',last_error='طرف حساب مشتری فعال نیست',updated_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    continue
                if not party["email"]:
                    con.execute(
                        "UPDATE woo_queue SET status='skipped',last_error='ایمیل مشتری برای WooCommerce الزامی است',updated_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    sync_outbox.log(
                        con,
                        "out",
                        "customer",
                        "skipped",
                        "برای ارسال مشتری به سایت، ایمیل را در طرف‌حساب وارد کنید",
                        local_id=party["id"],
                    )
                    continue
                mapping = sync_outbox.map_local(con, "customer", party["id"])
                words = str(party["name"]).split(" ", 1)
                billing = {
                    "first_name": words[0],
                    "last_name": words[1] if len(words) > 1 else "",
                    "phone": party["phone"] or "",
                    "email": party["email"],
                    "address_1": party["address"] or "",
                }
                body = {
                    "email": party["email"],
                    "first_name": words[0],
                    "last_name": words[1] if len(words) > 1 else "",
                    "billing": billing,
                    "shipping": billing,
                }
                result = (
                    client.put(f"customers/{mapping['remote_id']}", body)
                    if mapping
                    else client.post("customers", body)
                )
                with db.tx(con):
                    sync_outbox.put_map(
                        con,
                        "customer",
                        party["id"],
                        int(result["id"]),
                        remote_updated=result.get("date_modified_gmt") or "",
                    )
                    con.execute(
                        "UPDATE woo_queue SET status='done',last_error=NULL,updated_at=datetime('now') WHERE id=?",
                        (row["id"],),
                    )
                    sync_outbox.log(
                        con,
                        "out",
                        "customer",
                        "done",
                        "به‌روزرسانی مشتری",
                        int(result["id"]),
                        party["id"],
                    )
                count += 1
                continue
            if row["entity"] != "product":
                con.execute(
                    "UPDATE woo_queue SET status='skipped',last_error='نوع خروجی پشتیبانی نمی‌شود',updated_at=datetime('now') WHERE id=?",
                    (row["id"],),
                )
                continue
            if db.get_setting(con, "woo_sync_products", "1") != "1":
                con.execute(
                    "UPDATE woo_queue SET status='skipped',last_error='همگام‌سازی کالاها غیرفعال است',updated_at=datetime('now') WHERE id=?",
                    (row["id"],),
                )
                continue
            item = con.execute(
                "SELECT * FROM items WHERE id=?", (row["local_id"],)
            ).fetchone()
            if not item:
                raise WooError("کالای محلی پیدا نشد")
            mapping = sync_outbox.map_local(con, "product", item["id"])
            body = _product_body(con, item)
            if mapping:
                if mapping["remote_parent_id"]:
                    body.pop("type", None)
                    result = client.put(
                        f"products/{mapping['remote_parent_id']}/variations/{mapping['remote_id']}",
                        body,
                    )
                else:
                    result = client.put(f"products/{mapping['remote_id']}", body)
            else:
                result = client.post("products", body)
            with db.tx(con):
                sync_outbox.put_map(
                    con,
                    "product",
                    item["id"],
                    int(result["id"]),
                    remote_parent_id=result.get("parent_id") or None,
                    remote_updated=result.get("date_modified_gmt") or "",
                    local_hash=_hash(dict(item)),
                    remote_hash=_hash(result),
                )
                con.execute(
                    "UPDATE woo_queue SET status='done',last_error=NULL,updated_at=datetime('now') WHERE id=?",
                    (row["id"],),
                )
                sync_outbox.log(
                    con,
                    "out",
                    "product",
                    "done",
                    "به‌روزرسانی کالا",
                    int(result["id"]),
                    item["id"],
                )
            count += 1
        except Exception as e:
            with db.tx(con):
                con.execute(
                    "UPDATE woo_queue SET status='error',attempts=attempts+1,last_error=?,updated_at=datetime('now') WHERE id=?",
                    (str(e)[:2000], row["id"]),
                )
                sync_outbox.log(
                    con, "out", row["entity"], "error", str(e), local_id=row["local_id"]
                )
    return count


def _pull_events(con, client, factor):
    rows = con.execute(
        "SELECT * FROM woo_events WHERE status IN ('pending','error') ORDER BY id LIMIT 50"
    ).fetchall()
    count = 0
    for row in rows:
        try:
            entity = row["topic"].split(".")[0]
            rid = int(row["remote_id"] or 0)
            if entity == "order" and db.get_setting(con, "woo_sync_orders", "1") == "1":
                if row["topic"].endswith("deleted"):
                    sync_outbox.log(
                        con,
                        "in",
                        row["topic"],
                        "review",
                        "حذف سفارش، سند قطعی محلی را حذف نمی‌کند",
                        rid,
                    )
                else:
                    obj = client.get(f"orders/{rid}")
                    with auth.service_mode():
                        with db.tx(con):
                            import_order(con, client, obj, factor)
            elif (
                entity == "product"
                and db.get_setting(con, "woo_sync_products", "1") == "1"
            ):
                if row["topic"].endswith("deleted"):
                    sync_outbox.log(
                        con,
                        "in",
                        row["topic"],
                        "skipped",
                        "حذف از سایت باعث حذف کالا در دفتر نمی‌شود",
                        rid,
                    )
                else:
                    obj = client.get(f"products/{rid}")
                    with auth.service_mode():
                        with db.tx(con):
                            _ensure_product(con, client, obj, factor)
            elif (
                entity == "customer"
                and db.get_setting(con, "woo_sync_customers", "1") == "1"
            ):
                if row["topic"].endswith("deleted"):
                    sync_outbox.log(
                        con,
                        "in",
                        row["topic"],
                        "skipped",
                        "حذف مشتری در سایت، طرف حساب محلی را حذف نمی‌کند",
                        rid,
                    )
                else:
                    obj = client.get(f"customers/{rid}")
                    with auth.service_mode():
                        with db.tx(con):
                            import_customer(con, obj)
            con.execute("UPDATE woo_events SET status='done' WHERE id=?", (row["id"],))
            count += 1
        except Exception as e:
            con.execute("UPDATE woo_events SET status='error' WHERE id=?", (row["id"],))
            sync_outbox.log(con, "in", row["topic"], "error", str(e), row["remote_id"])
    return count


def sync_once(con, client: WooClient | None = None) -> dict:
    client = client or client_from_settings(con)
    factor = price_factor(con)
    result = {"products": 0, "customers": 0, "orders": 0, "events": 0, "outbox": 0}
    with auth.service_mode():
        # Prevent a stale/edit conflict: remote product changes update metadata only,
        # while stock levels are always sourced from the accounting ledger.
        with sync_outbox.suppress_outbound():
            result["products"] = _pull_products(con, client, factor)
            result["customers"] = _pull_customers(con, client)
            result["events"] = _pull_events(con, client, factor)
            result["orders"] = _pull_orders(con, client, factor)
        # One-time bootstrap per direction: after matching the remote catalog by SKU/phone,
        # publish local records and the ledger-owned stock. Disabled sync remains pending until enabled.
        with db.tx(con):
            if (
                db.get_setting(con, "woo_sync_products", "1") == "1"
                and sync_outbox.get_state(con, "bootstrap_products_done", "") != "1"
            ):
                for row in con.execute(
                    "SELECT id FROM items WHERE is_active=1"
                ).fetchall():
                    sync_outbox.enqueue(con, "product", row["id"], "upsert")
                sync_outbox.set_state(con, "bootstrap_products_done", "1")
            if (
                db.get_setting(con, "woo_sync_customers", "1") == "1"
                and sync_outbox.get_state(con, "bootstrap_customers_done", "") != "1"
            ):
                for row in con.execute(
                    "SELECT id FROM parties WHERE is_active=1 AND kind IN ('customer','both')"
                ).fetchall():
                    sync_outbox.enqueue(con, "customer", row["id"], "upsert")
                sync_outbox.set_state(con, "bootstrap_customers_done", "1")
        result["outbox"] = _push_queue(con, client, factor)
    return result


class WooSyncWorker(threading.Thread):
    def __init__(self, interval: int = 20, on_status=None):
        super().__init__(name="WooCommerceSync", daemon=True)
        self.interval = max(10, min(int(interval), 3600))
        self.on_status = on_status
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()

    def request_sync(self):
        self.wake_event.set()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()

    def run(self):
        con = None
        webhook = None
        try:
            con = db.connect()
            if db.get_setting(con, "woo_webhook_enabled", "0") == "1":
                from woo_webhook import WooWebhookServer

                webhook = WooWebhookServer(
                    "127.0.0.1", int(db.get_setting(con, "woo_webhook_port", "8765"))
                ).start()
            while not self.stop_event.is_set():
                try:
                    result = sync_once(con)
                    if self.on_status:
                        self.on_status("ok", result)
                except Exception as e:
                    try:
                        sync_outbox.log(con, "system", "worker", "error", str(e))
                    except Exception:
                        pass
                    if self.on_status:
                        self.on_status("error", str(e))
                self.wake_event.wait(self.interval)
                self.wake_event.clear()
        except Exception as e:
            if con:
                try:
                    sync_outbox.log(con, "system", "worker", "error", str(e))
                except Exception:
                    pass
            if self.on_status:
                self.on_status("error", str(e))
        finally:
            if webhook:
                webhook.stop()
            if con:
                con.close()
