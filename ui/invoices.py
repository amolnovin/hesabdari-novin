# -*- coding: utf-8 -*-
"""برگهٔ فاکتورها (فروش، خرید، برگشت‌ها)"""

from functools import partial

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

import jalali
import repo
import utils
from ui.widgets import (
    DateEdit, MoneyEdit, add_row, export_csv, make_table, msg_error, msg_info,
    msg_warn, msg_ask, print_html, selected_id,
)

STATUS_LABEL = {"draft": "پیش‌نویس", "confirmed": "قطعی", "cancelled": "ابطال‌شده"}


class InvoiceDialog(QDialog):
    """
    دیالوگ صدور/ویرایش فاکتور.

    نکتهٔ طراحی: ردیف‌های فاکتور در یک لیستِ پایتونی (self.rows) نگهداری می‌شوند
    و جدول فقط «نمایش» آن است. این کار از باگ‌های رایجِ جابه‌جاییِ شماره ردیف
    پس از حذف یک سطر جلوگیری می‌کند.
    """

    def __init__(self, con, parent=None, kind: str = "sale", invoice_id: int | None = None):
        super().__init__(parent)
        self.con = con
        self.kind = kind
        self.invoice_id = invoice_id
        self.rows: list[dict] = []
        self.saved_id = None
        self.setLayoutDirection(Qt.RightToLeft)
        self.setWindowTitle(f"{repo.KIND_LABEL[kind]}" + (f" شماره {self._no()}" if invoice_id else " — جدید"))
        self.resize(960, 580)
        self._build()
        if invoice_id:
            self._load()
        else:
            self._add_line()

    def _no(self):
        r = self.con.execute("SELECT no FROM invoices WHERE id=?", (self.invoice_id,)).fetchone()
        return r["no"] if r else ""

    # ------------------------------------------------------------------
    def _build(self):
        lay = QVBoxLayout(self)

        head = QHBoxLayout()
        head.addWidget(QLabel("طرف حساب:"))
        self.party = QComboBox()
        self.party.setMinimumWidth(220)
        self._fill_parties()
        head.addWidget(self.party)
        head.addWidget(QLabel("تاریخ:"))
        self.date = DateEdit()
        head.addWidget(self.date)
        head.addWidget(QLabel("سررسید:"))
        self.due = DateEdit()
        self.due.edit.clear()
        head.addWidget(self.due)
        head.addStretch(1)
        lay.addLayout(head)

        head2 = QHBoxLayout()
        head2.addWidget(QLabel("شرح:"))
        self.desc = QLineEdit()
        head2.addWidget(self.desc, 1)
        lay.addLayout(head2)

        self.lines = make_table(["کالا / خدمت", "تعداد", "قیمت واحد (ریال)",
                                 "تخفیف (ریال)", "مالیات٪", "خالص (ریال)", ""])
        self.lines.setEditTriggers(QAbstractItemView.DoubleClicked |
                                   QAbstractItemView.EditKeyPressed |
                                   QAbstractItemView.AnyKeyPressed)
        self.lines.itemChanged.connect(self._on_cell_changed)
        lay.addWidget(self.lines, 1)

        row_btns = QHBoxLayout()
        b_add = QPushButton("➕ افزودن ردیف")
        b_add.clicked.connect(lambda: self._add_line())
        row_btns.addWidget(b_add)
        row_btns.addStretch(1)
        lay.addLayout(row_btns)

        tot = QHBoxLayout()
        tot.addWidget(QLabel("تخفیف کل (ریال):"))
        self.discount = MoneyEdit(value=0)
        self.discount.textChanged.connect(self._recalc)
        tot.addWidget(self.discount)
        self.lbl_subtotal = QLabel("۰")
        self.lbl_vat = QLabel("۰")
        self.lbl_total = QLabel("۰")
        for label, w in [("جمع خالص:", self.lbl_subtotal), ("مالیات:", self.lbl_vat),
                         ("قابل پرداخت:", self.lbl_total)]:
            tot.addStretch(1)
            tot.addWidget(QLabel(label))
            tot.addWidget(w)
        for w in (self.lbl_subtotal, self.lbl_vat, self.lbl_total):
            w.setStyleSheet("font-weight:bold;color:#123c5a;font-size:14px")
        lay.addLayout(tot)

        bb = QDialogButtonBox()
        self.btn_draft = bb.addButton("💾 ذخیره پیش‌نویس", QDialogButtonBox.AcceptRole)
        self.btn_confirm = bb.addButton("✅ ثبت و قطعی کردن", QDialogButtonBox.ActionRole)
        bb.addButton("انصراف", QDialogButtonBox.RejectRole)
        self.btn_draft.clicked.connect(lambda: self._save(confirm=False))
        self.btn_confirm.clicked.connect(lambda: self._save(confirm=True))
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

        if self.invoice_id:
            inv = self.con.execute("SELECT status FROM invoices WHERE id=?", (self.invoice_id,)).fetchone()
            if inv and inv["status"] != "draft":
                self.btn_draft.setEnabled(False)
                self.btn_confirm.setEnabled(False)
                self.lines.setEditTriggers(QAbstractItemView.NoEditTriggers)
                self.setWindowTitle(self.windowTitle() + " (فقط مشاهده)")

    # ------------------------------------------------------------------
    def _fill_parties(self):
        kind = "customer" if self.kind in ("sale", "sale_return") else "supplier"
        for p in repo.list_parties(self.con, kind):
            self.party.addItem(p["name"], p["id"])

    def _items(self):
        return [i for i in repo.list_items(self.con) if i["is_active"]]

    # ---- مدیریت ردیف‌ها (مبتنی بر لیست داده) -----------------------------
    def _add_line(self, item_id=None, qty=1, price=0, discount=0, vat=None, desc=""):
        vat_rate = vat if vat is not None else float(repo.db.get_setting(self.con, "default_vat_rate", "10"))
        self.rows.append({"item_id": item_id, "desc": desc, "qty": qty, "price": price,
                          "discount": discount, "vat": vat_rate})
        self._rebuild_table()

    def _remove_line(self, index: int):
        if 0 <= index < len(self.rows):
            self.rows.pop(index)
            self._rebuild_table()

    def _rebuild_table(self):
        """ساخت مجدد جدول از روی لیست داده‌ها (همیشه سازگار)"""
        self.lines.blockSignals(True)
        self.lines.setRowCount(0)
        for i, rd in enumerate(self.rows):
            self.lines.insertRow(i)
            combo = QComboBox()
            combo.addItem("— انتخاب کنید —", None)
            for it in self._items():
                combo.addItem(it["name"], it["id"])
            if rd["item_id"]:
                idx = combo.findData(rd["item_id"])
                combo.setCurrentIndex(max(0, idx))
            elif rd["desc"]:
                combo.addItem(rd["desc"], None)
                combo.setCurrentIndex(combo.count() - 1)
            combo.currentIndexChanged.connect(partial(self._on_item_selected, i))
            self.lines.setCellWidget(i, 0, combo)

            for c, text in ((1, f"{rd['qty']:g}"), (2, utils.fmt(rd["price"])),
                            (3, utils.fmt(rd["discount"])), (4, f"{rd['vat']:g}"),
                            (5, utils.fmt(self._line_net(rd)))):
                it = QTableWidgetItem(text)
                it.setTextAlignment(Qt.AlignCenter)
                if c == 5:
                    it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                self.lines.setItem(i, c, it)

            btn = QPushButton("🗑")
            btn.setMaximumWidth(34)
            btn.clicked.connect(partial(self._remove_line, i))
            self.lines.setCellWidget(i, 6, btn)
        self.lines.blockSignals(False)
        self._recalc()

    def _on_item_selected(self, index: int, _i):
        if index >= len(self.rows):
            return
        combo = self.lines.cellWidget(index, 0)
        if combo is None:
            return
        item_id = combo.currentData()
        rd = self.rows[index]
        rd["item_id"] = item_id
        rd["desc"] = "" if item_id else (combo.currentText() if combo.currentIndex() > 0 else "")
        if item_id:
            item = repo.get_item(self.con, item_id)
            if item:
                rd["price"] = item["sale_price"] if self.kind in ("sale", "sale_return") else item["purchase_price"]
                rd["vat"] = item["vat_rate"]
                self._rebuild_table()

    def _on_cell_changed(self, item):
        r, c = item.row(), item.column()
        if r >= len(self.rows) or c not in (1, 2, 3, 4):
            return
        rd = self.rows[r]
        try:
            if c == 1:
                rd["qty"] = utils.parse_float(item.text())
            elif c == 2:
                rd["price"] = utils.parse_money(item.text())
            elif c == 3:
                rd["discount"] = utils.parse_money(item.text())
            elif c == 4:
                rd["vat"] = utils.parse_float(item.text())
        except ValueError:
            return
        self._recalc()

    def _line_net(self, rd):
        return repo.calc_line(rd["qty"], rd["price"], rd["discount"], rd["vat"])["net"]

    def _recalc(self):
        """به‌روزرسانی ستون خالص + جمع‌های پایین فرم"""
        self.lines.blockSignals(True)
        for i, rd in enumerate(self.rows):
            cell = self.lines.item(i, 5)
            if cell is not None:
                cell.setText(utils.fmt(self._line_net(rd)))
        self.lines.blockSignals(False)
        totals = repo.calc_invoice([self._line_dict(rd) for rd in self.rows], self.discount.value)
        self.lbl_subtotal.setText(utils.fmt(totals["subtotal"]))
        self.lbl_vat.setText(utils.fmt(totals["vat_amount"]))
        self.lbl_total.setText(utils.fmt(totals["total"]))

    def _line_dict(self, rd):
        return {"item_id": rd["item_id"], "description": rd["desc"] or None,
                "qty": rd["qty"], "unit_price": rd["price"], "discount": rd["discount"],
                "vat_rate": rd["vat"], **repo.calc_line(rd["qty"], rd["price"],
                                                        rd["discount"], rd["vat"])}

    def _collect_lines(self):
        out = []
        for rd in self.rows:
            if not rd["item_id"] and not rd["desc"]:
                continue
            if rd["qty"] == 0 and rd["price"] == 0:
                continue
            out.append(self._line_dict(rd))
        return out

    # ------------------------------------------------------------------
    def _load(self):
        inv = self.con.execute("SELECT * FROM invoices WHERE id=?", (self.invoice_id,)).fetchone()
        idx = self.party.findData(inv["party_id"])
        if idx >= 0:
            self.party.setCurrentIndex(idx)
        self.date.set_jalali(inv["jalali_date"])
        if inv["due_date"]:
            self.due.set_jalali(jalali.to_jalali_str(inv["due_date"]))
        else:
            self.due.edit.clear()
        self.desc.setText(inv["description"] or "")
        self.discount.set_value(inv["discount"])
        for ln in repo.invoice_lines(self.con, self.invoice_id):
            self.rows.append({"item_id": ln["item_id"],
                              "desc": (ln["description"] or "") if not ln["item_id"] else "",
                              "qty": ln["qty"], "price": ln["unit_price"],
                              "discount": ln["discount"], "vat": ln["vat_rate"]})
        self._rebuild_table()

    def _save(self, confirm: bool):
        try:
            g = self.date.gregorian
            due = self.due.gregorian if self.due.jalali else ""
        except ValueError as e:
            msg_error(self, str(e))
            return
        if not self.party.currentData():
            msg_warn(self, "انتخاب طرف حساب الزامی است")
            return
        lines = self._collect_lines()
        if not lines:
            msg_warn(self, "حداقل یک ردیف کالا یا خدمت اضافه کنید")
            return
        try:
            header = {"kind": self.kind, "party_id": self.party.currentData(),
                      "gregorian_date": g, "gregorian_due_date": due,
                      "description": utils.normalize(self.desc.text()),
                      "discount": self.discount.value}
            inv_id = repo.save_invoice(self.con, self.invoice_id, header, lines)
            if confirm:
                repo.confirm_invoice(self.con, inv_id)
        except Exception as e:
            msg_error(self, str(e))
            return
        self.saved_id = inv_id
        msg_info(self, "فاکتور ثبت و قطعی شد" if confirm else "پیش‌نویس ذخیره شد")
        self.accept()


# ===========================================================================
class InvoicesTab(QWidget):
    def __init__(self, con, parent=None):
        super().__init__(parent)
        self.con = con
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        bar = QHBoxLayout()
        self.kind = QComboBox()
        for k, label in repo.KIND_LABEL.items():
            self.kind.addItem(label, k)
        self.kind.currentIndexChanged.connect(self.refresh)
        self.from_date = DateEdit(with_today_button=False)
        self.from_date.edit.clear()
        self.to_date = DateEdit(with_today_button=False)
        self.to_date.edit.clear()
        self.status = QComboBox()
        self.status.addItem("همه", "")
        self.status.addItem("پیش‌نویس", "draft")
        self.status.addItem("قطعی", "confirmed")
        self.status.addItem("ابطال‌شده", "cancelled")
        self.status.currentIndexChanged.connect(self.refresh)
        bar.addWidget(QLabel("نوع:"))
        bar.addWidget(self.kind)
        bar.addWidget(QLabel("از تاریخ:"))
        bar.addWidget(self.from_date)
        bar.addWidget(QLabel("تا تاریخ:"))
        bar.addWidget(self.to_date)
        bar.addWidget(QLabel("وضعیت:"))
        bar.addWidget(self.status)
        bar.addStretch(1)
        lay.addLayout(bar)

        btns = QHBoxLayout()
        for text, slot, primary in [
            ("➕ فاکتور جدید", self.new_invoice, True),
            ("👁 مشاهده / ویرایش", self.view_invoice, False),
            ("✅ قطعی کردن", self.confirm_invoice, False),
            ("🖨 چاپ PDF", self.print_invoice, False),
            ("🚫 ابطال", self.cancel_invoice, False),
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
            ["شناسه", "شماره", "تاریخ", "طرف حساب", "خالص", "مالیات",
             "جمع کل", "پرداخت‌شده", "مانده", "وضعیت", "شرح"])
        lay.addWidget(self.table)

        self.summary = QLabel("")
        self.summary.setStyleSheet("color:#1f5f8b;font-weight:bold;padding:6px")
        lay.addWidget(self.summary)
        self.refresh()

    # ------------------------------------------------------------------
    def _date_range(self):
        try:
            d1 = jalali.from_jalali_str(self.from_date.jalali) if self.from_date.jalali else ""
        except ValueError:
            d1 = ""
        try:
            d2 = jalali.from_jalali_str(self.to_date.jalali) if self.to_date.jalali else ""
        except ValueError:
            d2 = ""
        return d1, d2

    def refresh(self):
        d1, d2 = self._date_range()
        rows = repo.list_invoices(self.con, self.kind.currentData(), d1, d2,
                                  status=self.status.currentData())
        self.table.setRowCount(0)
        tot = paid = 0
        for r in rows:
            add_row(self.table, [
                r["id"], r["no"], r["jalali_date"], r["party_name"],
                utils.fmt(r["subtotal"] - r["discount"]), utils.fmt(r["vat_amount"]),
                utils.fmt(r["total"]), utils.fmt(r["paid_amount"]),
                utils.fmt(r["remainder"]), STATUS_LABEL.get(r["status"], r["status"]),
                r["description"] or "",
            ], data=r["id"])
            if r["status"] == "confirmed":
                tot += r["total"]
                paid += r["paid_amount"]
        self.summary.setText(
            f"تعداد: {len(rows)}  |  جمع مبالغ قطعی: {utils.fmt(tot)} ریال  |  "
            f"دریافت/پرداخت‌شده: {utils.fmt(paid)} ریال  |  مانده: {utils.fmt(tot - paid)} ریال")

    # ------------------------------------------------------------------
    def new_invoice(self):
        d = InvoiceDialog(self.con, self, self.kind.currentData())
        if d.exec():
            self.refresh()

    def view_invoice(self):
        inv_id = selected_id(self.table)
        if not inv_id:
            msg_warn(self, "ابتدا یک فاکتور را انتخاب کنید")
            return
        inv = self.con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
        InvoiceDialog(self.con, self, inv["kind"], inv_id).exec()
        self.refresh()

    def confirm_invoice(self):
        inv_id = selected_id(self.table)
        if not inv_id:
            msg_warn(self, "ابتدا یک فاکتور را انتخاب کنید")
            return
        try:
            repo.confirm_invoice(self.con, inv_id)
            self.refresh()
            msg_info(self, "فاکتور قطعی شد و سند حسابداری آن به‌طور خودکار صادر گردید")
        except Exception as e:
            msg_error(self, str(e))

    def cancel_invoice(self):
        inv_id = selected_id(self.table)
        if not inv_id:
            msg_warn(self, "ابتدا یک فاکتور را انتخاب کنید")
            return
        inv = self.con.execute("SELECT * FROM invoices WHERE id=?", (inv_id,)).fetchone()
        if inv["status"] == "cancelled":
            msg_warn(self, "این فاکتور قبلاً ابطال شده است")
            return
        reason = ""
        if inv["status"] == "confirmed":
            from PySide6.QtWidgets import QInputDialog
            reason, ok = QInputDialog.getText(self, "ابطال فاکتور", "دلیل ابطال:")
            if not ok:
                return
        if not msg_ask(self, f"آیا فاکتور شماره {inv['no']} ابطال شود؟"):
            return
        try:
            repo.cancel_invoice(self.con, inv_id, reason)
            self.refresh()
            msg_info(self, "فاکتور با ثبت سند معکوس ابطال شد")
        except Exception as e:
            msg_error(self, str(e))

    # ------------------------------------------------------------------
    def _invoice_html(self, inv_id: int) -> str:
        inv = self.con.execute(
            """SELECT i.*, p.name AS party_name, p.phone, p.address, p.national_id,
                      p.economic_code, p.postal_code
               FROM invoices i JOIN parties p ON p.id = i.party_id WHERE i.id = ?""",
            (inv_id,)).fetchone()
        lines = repo.invoice_lines(self.con, inv_id)
        company = {r["key"]: r["value"] for r in self.con.execute("SELECT key, value FROM settings")}
        rows = ""
        for i, l in enumerate(lines, 1):
            nm = l["item_name"] or l["description"] or ""
            rows += (f"<tr><td>{i}</td><td>{nm}</td>"
                     f"<td>{utils.fmt_qty(l['qty'])} {l['unit'] or ''}</td>"
                     f"<td>{utils.fmt(l['unit_price'])}</td><td>{utils.fmt(l['discount'])}</td>"
                     f"<td>{utils.fmt(l['line_total'])}</td></tr>")
        return f"""
        <html><body dir="rtl" style="font-family:Tahoma;font-size:12px">
        <h2 style="text-align:center;margin:0">{company.get('company_name','')}</h2>
        <h3 style="text-align:center;margin:4px 0">{repo.KIND_LABEL[inv['kind']]} شماره {inv['no']}</h3>
        <p style="text-align:center;color:#666;margin:2px">تاریخ: {inv['jalali_date']}</p>
        <hr>
        <table width="100%" style="font-size:12px">
          <tr><td><b>طرف حساب:</b> {inv['party_name']}</td>
              <td><b>تلفن:</b> {inv['phone'] or '-'}</td></tr>
          <tr><td><b>شناسه ملی / کد ملی:</b> {inv['national_id'] or '-'}</td>
              <td><b>کد اقتصادی:</b> {inv['economic_code'] or '-'}</td></tr>
          <tr><td colspan="2"><b>آدرس:</b> {inv['address'] or '-'} — کد پستی: {inv['postal_code'] or '-'}</td></tr>
        </table>
        <hr>
        <table width="100%" border="1" cellspacing="0" cellpadding="5"
               style="border-collapse:collapse;font-size:12px">
          <tr style="background:#eef3f7">
            <th>ردیف</th><th>شرح کالا/خدمت</th><th>تعداد</th><th>قیمت واحد</th>
            <th>تخفیف</th><th>مبلغ (ریال)</th></tr>
          {rows}
        </table><br>
        <table width="100%" style="font-size:13px">
          <tr><td>جمع خالص:</td><td><b>{utils.fmt(inv['subtotal'])}</b></td></tr>
          <tr><td>تخفیف:</td><td><b>{utils.fmt(inv['discount'])}</b></td></tr>
          <tr><td>مالیات بر ارزش افزوده:</td><td><b>{utils.fmt(inv['vat_amount'])}</b></td></tr>
          <tr><td>قابل پرداخت:</td><td><b>{utils.fmt(inv['total'])}</b> ریال</td></tr>
        </table>
        <hr>
        <p style="text-align:center;color:#666;font-size:11px">{company.get('invoice_footer','')}</p>
        </body></html>"""

    def print_invoice(self):
        inv_id = selected_id(self.table)
        if not inv_id:
            msg_warn(self, "ابتدا یک فاکتور را انتخاب کنید")
            return
        inv = self.con.execute("SELECT no FROM invoices WHERE id=?", (inv_id,)).fetchone()
        print_html(self, self._invoice_html(inv_id), f"فاکتور-{inv['no']}")

    def export(self):
        export_csv(self, self.table, "invoices")
