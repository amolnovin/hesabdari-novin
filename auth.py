# -*- coding: utf-8 -*-
"""
کاربران، نقش‌ها و سطح دسترسی
=============================
نکتهٔ امنیتی: رمز عبور هرگز به صورت متن ساده ذخیره نمی‌شود.
از PBKDF2-HMAC-SHA256 با «نمک» تصادفی و ۱۲۰٬۰۰۰ تکرار استفاده شده است
(کتابخانهٔ استاندارد پایتون؛ نیازی به نصب bcrypt نیست).
"""

import hashlib
import hmac
import os
import sqlite3
from datetime import datetime

import db

ITERATIONS = 120_000

ROLES = {
    "admin": "مدیر سیستم",
    "accountant": "حسابدار",
    "operator": "اپراتور",
    "viewer": "مشاهده‌گر",
}

# هر نقش چه کارهایی مجاز است
_PERMS = {
    "admin": {"*"},
    "accountant": {
        "invoice.create", "invoice.confirm", "invoice.cancel", "invoice.print",
        "payment.create", "payment.cancel",
        "cheque.create", "cheque.update",
        "party.edit", "item.edit",
        "report.view", "report.export",
        "backup.create",
    },
    "operator": {
        "invoice.create", "payment.create", "cheque.create",
        "party.edit", "report.view",
    },
    "viewer": {"report.view"},
}

# کاربرِ واردشدهٔ فعلی (None یعنی حالت بدون ورود — مخصوص اسکریپت‌ها و تست‌ها)
_current_user: dict | None = None


# ---------------------------------------------------------------------------
# رمز عبور
# ---------------------------------------------------------------------------
def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def make_hash(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    return _hash(password, salt), salt.hex()


def verify(password: str, password_hash: str, salt_hex: str) -> bool:
    return hmac.compare_digest(_hash(password, bytes.fromhex(salt_hex)), password_hash)


# ---------------------------------------------------------------------------
# مدیریت کاربران
# ---------------------------------------------------------------------------
def count_users(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def create_user(con, username: str, password: str, role: str = "operator",
                full_name: str = "") -> int:
    username = (username or "").strip()
    if not username:
        raise ValueError("نام کاربری نمی‌تواند خالی باشد")
    if len(password or "") < 4:
        raise ValueError("رمز عبور باید حداقل ۴ کاراکتر باشد")
    if role not in ROLES:
        raise ValueError("نقش نامعتبر است")
    h, salt = make_hash(password)
    cur = con.execute(
        "INSERT INTO users (username, password_hash, salt, full_name, role) VALUES (?,?,?,?,?)",
        (username, h, salt, full_name.strip(), role))
    con.commit()
    db.audit(con, "create_user", "users", cur.lastrowid, f"{username} ({role})")
    return cur.lastrowid


def authenticate(con, username: str, password: str) -> dict | None:
    row = con.execute("SELECT * FROM users WHERE username = ? AND is_active = 1",
                      ((username or "").strip(),)).fetchone()
    if not row:
        return None
    if not verify(password, row["password_hash"], row["salt"]):
        return None
    con.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), row["id"]))
    con.commit()
    db.audit(con, "login", "users", row["id"], row["username"])
    return dict(row)


def list_users(con) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM users ORDER BY username").fetchall()


def update_user(con, user_id: int, role: str | None = None, is_active: int | None = None,
                full_name: str | None = None) -> None:
    if role:
        con.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    if is_active is not None:
        con.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
    if full_name is not None:
        con.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
    con.commit()
    db.audit(con, "update_user", "users", user_id, f"role={role} active={is_active}")


def change_password(con, user_id: int, new_password: str) -> None:
    if len(new_password) < 4:
        raise ValueError("رمز عبور باید حداقل ۴ کاراکتر باشد")
    h, salt = make_hash(new_password)
    con.execute("UPDATE users SET password_hash = ?, salt = ? WHERE id = ?", (h, salt, user_id))
    con.commit()
    db.audit(con, "change_password", "users", user_id)


# ---------------------------------------------------------------------------
# نشست فعلی و کنترل دسترسی
# ---------------------------------------------------------------------------
def set_current(user: dict | None) -> None:
    global _current_user
    _current_user = user


def current() -> dict | None:
    return _current_user


def current_role() -> str:
    return (_current_user or {}).get("role", "admin")


def has(perm: str) -> bool:
    """آیا کاربر فعلی این دسترسی را دارد؟ (بدون ورود = دسترسی کامل)"""
    if _current_user is None:
        return True
    perms = _PERMS.get(_current_user.get("role", "viewer"), set())
    return "*" in perms or perm in perms


def require(perm: str) -> None:
    if not has(perm):
        raise PermissionError(
            f"شما مجوز «{perm}» را ندارید (نقش فعلی: {ROLES.get(current_role(), current_role())})")


def role_label(role: str) -> str:
    return ROLES.get(role, role)
