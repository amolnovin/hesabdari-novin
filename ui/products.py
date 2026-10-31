# -*- coding: utf-8 -*-
"""برگهٔ کالاها، خدمات و انبار"""

from PySide6.QtCore import Qt
import json

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QVBoxLayout, QWidget,
)

import business_profiles
import repo
import utils
from ui.widgets import (
    DateEdit, FormDialog, MoneyEdit, NumberEdit, add_row, export_csv,
    make_table, msg_error, msg_info, msg_warn, msg_ask, selected_id,
)


class ProductsTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()

    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("جستجوی کالا…")
        self.search.textChanged.connect(self.refresh)
        self.chk_all = QCheckBox("نمایش موارد غیرفعال")
        self.chk_all.stateChanged.connect(self.refresh)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.chk_all)
        lay.addLayout(bar)

        btns = QHBoxLayout()
        for text, slot, primary in [
            ("➕ کالای جدید", self.new_item, True),
            ("✏️ ویرایش کالا", self.edit_item, False),
            ("🗑️ حذف", self.delete_item, False),
            ("📦 اصلاح موجودی", self.adjust_stock, False),
            ("📋 کاردکس کالا", self.cardex, False),
            ("📄 خروجی", self.export, False),
            ("🔄 بروزرسانی", self.refresh, False),
        ]:
            b = QPushButton(text)
            b.clicked.connect(slot)
            if primary:
                b.setStyleSheet("QPushButton{background:#1f5f8b;color:#fff;padding:7px 14px;border-radius:6px;font-weight:bold}")
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addLayout(btns)

        self.table = make_table(
            ["شناسه", "کد", "نام", "واحد", "قیمت فروش", "نرخ مالیات٪",
             "موجودی", "میانگین بهای تمام‌شده", "ارزش موجودی (ریال)", "حداقل موجودی", "ویژگی‌های پروفایل"])
        lay.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:6px")
        lay.addWidget(self.summary)
        self.refresh()

    # ------------------------------------------------------------------
    def refresh(self):
        rows = repo.list_items(self.con, utils.normalize(self.search.text()),
                               only_active=not self.chk_all.isChecked())
        self.table.setRowCount(0)
        total = 0
        low = []
        for r in rows:
            qty = float(r.get("stock") or 0)
            cost = int(r.get("avg_cost") or 0)
            value = int(r.get("stock_value") or 0)
            total += value
            if r["track_stock"] and qty <= float(r["stock_min"] or 0):
                low.append(r["name"])
            try:
                meta = json.loads(r.get("metadata_json") or "{}")
                features = " | ".join(f"{k}: {v}" for k, v in meta.items() if v)
            except Exception:
                features = ""
            add_row(self.table, [
                r["id"], r["code"] or "", r["name"], r["unit"],
                utils.fmt(r["sale_price"]), f"{r['vat_rate']:g}",
                utils.fmt_qty(qty), utils.fmt(cost), utils.fmt(value),
                utils.fmt_qty(r["stock_min"]), features,
            ], data=r["id"])
            if r["track_stock"] and qty <= float(r["stock_min"] or 0):
                for c in range(self.table.columnCount()):
                    item = self.table.item(self.table.rowCount() - 1, c)
                    if item:
                        item.setBackground(Qt.lightGray)
        note = f"  ⚠️ موجودیِ کم: {('، '.join(low))}" if low else ""
        self.summary.setText(f"تعداد: {len(rows)}  |  ارزش کل موجودی انبار: {utils.fmt(total)} ریال{note}")

    # ------------------------------------------------------------------
    def _dialog(self, item=None):
        profile = business_profiles.current(self.con)
        fields = [("name", "نام *", "text"),
             ("code", "کد کالا / SKU", "text"),
             ("unit", "واحد اندازه‌گیری", "text"),
             ("sale_price", "قیمت فروش (ریال)", "money"),
             ("purchase_price", "آخرین قیمت خرید (ریال)", "money"),
             ("vat_rate", "نرخ مالیات (درصد)", "number"),
             ("stock_min", "حداقل موجودی (هشدار)", "number")]
        labels = {"barcode": "بارکد", "expiry": "تاریخ انقضا", "weight": "وزن/مقدار پایه",
                  "variant": "سایز/رنگ/تنوع", "season": "فصل", "brand": "برند",
                  "serial": "شماره سریال/IMEI", "warranty": "گارانتی", "oem": "کد فنی/OEM",
                  "isbn": "شابک/ISBN"}
        try:
            meta = json.loads(item["metadata_json"] or "{}") if item else {}
        except Exception:
            meta = {}
        initial = dict(item) if item else {
            "unit": repo.db.get_setting(self.con, "default_item_unit", profile["unit"]),
            "vat_rate": float(repo.db.get_setting(self.con, "default_vat_rate", "10"))}
        for key in profile["item_fields"]:
            field = "meta_" + key
            fields.append((field, labels.get(key, key), "text"))
            initial[field] = meta.get(key, "")
        d = FormDialog(self, "کالا / خدمت", fields, initial)
        d._profile_metadata = meta
        chk = QCheckBox("این مورد انبار می‌شود (موجودی دارد)")
        chk.setChecked(bool(item["track_stock"]) if item else repo.db.get_setting(self.con, "default_track_stock", "1") == "1")
        d.layout().itemAt(0).layout().insertRow(7, "", chk)
        d.resize(520, 520)
        return d, chk, profile["item_fields"]

    def new_item(self):
        d, chk, profile_fields = self._dialog()
        if d.exec():
            try:
                data = {k: d.get(k) for k in ("name", "code", "unit", "sale_price",
                                              "purchase_price", "vat_rate", "stock_min")}
                if not data["name"]:
                    msg_warn(self, "نام کالا الزامی است")
                    return
                data["track_stock"] = chk.isChecked()
                data["is_active"] = True
                meta = {**d._profile_metadata, **{k: d.get("meta_" + k) for k in profile_fields}}
                data["metadata"] = {k: v for k, v in meta.items() if v}
                repo.save_item(self.con, None, data)
                self.refresh()
                msg_info(self, "کالا ثبت شد")
            except Exception as e:
                msg_error(self, str(e))

    def edit_item(self):
        iid = selected_id(self.table)
        if not iid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        item = repo.get_item(self.con, iid)
        d, chk, profile_fields = self._dialog(item)
        if d.exec():
            data = {k: d.get(k) for k in ("name", "code", "unit", "sale_price",
                                          "purchase_price", "vat_rate", "stock_min")}
            data["track_stock"] = chk.isChecked()
            data["is_active"] = True
            meta = {**d._profile_metadata, **{k: d.get("meta_" + k) for k in profile_fields}}
            data["metadata"] = {k: v for k, v in meta.items() if v}
            try:
                repo.save_item(self.con, iid, data)
                self.refresh()
                msg_info(self, "تغییرات ذخیره شد")
            except Exception as e:
                msg_error(self, str(e))

    def delete_item(self):
        iid = selected_id(self.table)
        if not iid:
            msg_warn(self, "ابتدا یک ردیف را انتخاب کنید")
            return
        item = repo.get_item(self.con, iid)
        if not msg_ask(self, f"آیا «{item['name']}» حذف/غیرفعال شود؟"):
            return
        try:
            repo.delete_item(self.con, iid)
            self.refresh()
        except Exception as e:
            msg_error(self, str(e))

    def adjust_stock(self):
        """انبارگردانی: ثبت موجودی واقعی"""
        iid = selected_id(self.table)
        if not iid:
            msg_warn(self, "ابتدا یک کالا را انتخاب کنید")
            return
        item = repo.get_item(self.con, iid)
        if not item["track_stock"]:
            msg_warn(self, "این مورد انبار نمی‌شود")
            return
        cur_qty, cur_cost = repo.stock_state(self.con, iid)
        d = QDialog(self)
        d.setWindowTitle(f"اصلاح موجودی — {item['name']}")
        d.setLayoutDirection(Qt.RightToLeft)
        lay = QVBoxLayout(d)
        lay.addWidget(QLabel(f"موجودی فعلی: {utils.fmt_qty(cur_qty)} {item['unit']}  •  "
                             f"بهای تمام‌شده: {utils.fmt(cur_cost)} ریال"))
        form = QHBoxLayout()
        form.addWidget(QLabel("موجودی واقعی (جدید):"))
        qty_edit = NumberEdit(value=cur_qty)
        form.addWidget(qty_edit)
        form.addWidget(QLabel("بهای هر واحد (ریال):"))
        cost_edit = MoneyEdit(value=cur_cost)
        form.addWidget(cost_edit)
        lay.addLayout(form)
        form2 = QHBoxLayout()
        form2.addWidget(QLabel("تاریخ:"))
        date_edit = DateEdit()
        form2.addWidget(date_edit)
        form2.addStretch(1)
        lay.addLayout(form2)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec():
            try:
                g = date_edit.gregorian
            except ValueError as e:
                msg_error(self, str(e))
                return
            try:
                repo.adjust_stock(self.con, iid, qty_edit.value, cost_edit.value, g,
                                  "انبارگردانی دستی")
                self.refresh()
                msg_info(self, "موجودی اصلاح شد")
            except Exception as e:
                msg_error(self, str(e))

    def cardex(self):
        iid = selected_id(self.table)
        if not iid:
            msg_warn(self, "ابتدا یک کالا را انتخاب کنید")
            return
        item = repo.get_item(self.con, iid)
        rows = repo.item_cardex(self.con, iid)
        d = QDialog(self)
        d.setWindowTitle(f"کاردکس — {item['name']}")
        d.setLayoutDirection(Qt.RightToLeft)
        d.resize(860, 460)
        lay = QVBoxLayout(d)
        t = make_table(["تاریخ", "نوع حرکت", "ورود", "خروج", "بهای واحد", "مانده", "مرجع", "شرح"])
        qty = 0.0
        labels = {"opening": "افتتاحیه", "purchase": "خرید", "sale": "فروش",
                  "sale_return": "برگشت از فروش", "purchase_return": "برگشت از خرید",
                  "adjust": "اصلاحی"}
        for r in rows:
            before = qty
            qty += r["qty"]
            add_row(t, [
                repo.jalali.to_jalali_str(r["move_date"]),
                labels.get(r["move_type"], r["move_type"]),
                utils.fmt_qty(r["qty"]) if r["qty"] > 0 else "",
                utils.fmt_qty(-r["qty"]) if r["qty"] < 0 else "",
                utils.fmt(r["unit_cost"]), utils.fmt_qty(qty),
                f"{r['ref_type'] or ''} {r['ref_id'] or ''}".strip(),
                r["description"] or "",
            ])
        lay.addWidget(t)
        lay.addWidget(QLabel(f"موجودی نهایی: {utils.fmt_qty(qty)} {item['unit']}"))
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        d.exec()

    def export(self):
        export_csv(self, self.table, "products")
