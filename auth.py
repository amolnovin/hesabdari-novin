# -*- coding: utf-8 -*-
"""کاربران، نقش‌ها، نشست و کنترل دسترسی.

حالت بدون ورود به‌صورت پیش‌فرض هیچ دسترسی ندارد. اسکریپت‌های نگهداری/تست
باید صریحاً از `service_mode()` استفاده کنند.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

import db

ITERATIONS = 120_000
MIN_PASSWORD = 8

ROLES = {"admin": "مدیر سیستم", "accountant": "حسابدار", "operator": "اپراتور", "viewer": "مشاهده‌گر"}

_PERMS = {
    "admin": {"*"},
    "accountant": {
        "invoice.create", "invoice.confirm", "invoice.cancel", "invoice.print",
        "payment.create", "payment.cancel", "cheque.create", "cheque.update",
        "party.edit", "item.edit", "stock.adjust", "report.view", "report.export",
        "backup.create", "settings.edit",
    },
    "operator": {"invoice.create", "payment.create", "cheque.create", "party.edit", "report.view"},
    "viewer": {"report.view"},
}

_current_user: dict | None = None
_service_mode = False


def _hash(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS).hex()


def make_hash(password: str) -> tuple[str, str]:
    salt = os.urandom(16)
    return _hash(password, salt), salt.hex()


def verify(password: str, password_hash: str, salt_hex: str) -> bool:
    try:
        return hmac.compare_digest(_hash(password, bytes.fromhex(salt_hex)), password_hash)
    except Exception:
        return False


def count_users(con: sqlite3.Connection) -> int:
    return con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]


def validate_password(password: str) -> None:
    if len(password or "") < MIN_PASSWORD:
        raise ValueError(f"رمز عبور باید حداقل {MIN_PASSWORD} کاراکتر باشد")


def create_user(con, username: str, password: str, role: str = "operator", full_name: str = "",
                *, bootstrap: bool = False) -> int:
    if not bootstrap and count_users(con) > 0:
        require("user.manage")
    username = (username or "").strip()
    if not username:
        raise ValueError("نام کاربری نمی‌تواند خالی باشد")
    validate_password(password)
    if role not in ROLES:
        raise ValueError("نقش نامعتبر است")
    h, salt = make_hash(password)
    with db.tx(con):
        cur = con.execute("INSERT INTO users (username,password_hash,salt,full_name,role) VALUES (?,?,?,?,?)",
                          (username, h, salt, (full_name or "").strip(), role))
        uid = cur.lastrowid
        db.audit(con, "create_user", "users", uid, f"{username} ({role})")
    return uid


def authenticate(con, username: str, password: str) -> dict | None:
    row = con.execute("SELECT * FROM users WHERE username = ? AND is_active = 1", ((username or "").strip(),)).fetchone()
    if not row or not verify(password, row["password_hash"], row["salt"]):
        db.audit(con, "login_failed", "users", row["id"] if row else None, (username or "").strip())
        con.commit()
        return None
    con.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (datetime.now().isoformat(timespec="seconds"), row["id"]))
    user = dict(row)
    set_current(user)
    db.audit(con, "login", "users", row["id"], row["username"])
    con.commit()
    return user


def list_users(con) -> list[sqlite3.Row]:
    require("user.manage")
    return con.execute("SELECT id,username,full_name,role,is_active,last_login_at,created_at FROM users ORDER BY username").fetchall()


def _active_admins(con, exclude_id=None):
    q = "SELECT COUNT(*) c FROM users WHERE role='admin' AND is_active=1"
    args = []
    if exclude_id is not None:
        q += " AND id<>?"; args.append(exclude_id)
    return con.execute(q, args).fetchone()["c"]


def update_user(con, user_id: int, role: str | None = None, is_active: int | None = None,
                full_name: str | None = None) -> None:
    require("user.manage")
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not row:
        raise ValueError("کاربر یافت نشد")
    if role is not None and role not in ROLES:
        raise ValueError("نقش نامعتبر است")
    new_role = role if role is not None else row["role"]
    new_active = int(is_active) if is_active is not None else row["is_active"]
    if row["role"] == "admin" and row["is_active"] and (new_role != "admin" or not new_active):
        if _active_admins(con, user_id) == 0:
            raise ValueError("حداقل یک مدیر فعال باید باقی بماند")
    before = {k: row[k] for k in ("role", "is_active", "full_name")}
    with db.tx(con):
        if role is not None:
            con.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
        if is_active is not None:
            con.execute("UPDATE users SET is_active=? WHERE id=?", (int(is_active), user_id))
        if full_name is not None:
            con.execute("UPDATE users SET full_name=? WHERE id=?", (full_name, user_id))
        db.audit(con, "update_user", "users", user_id, before=before,
                 after={"role": new_role, "is_active": new_active, "full_name": full_name if full_name is not None else row["full_name"]})


def change_password(con, user_id: int, new_password: str, *, old_password: str | None = None) -> None:
    u = current()
    if not (u and u.get("id") == user_id):
        require("user.manage")
    elif old_password is not None:
        row = con.execute("SELECT password_hash,salt FROM users WHERE id=?", (user_id,)).fetchone()
        if not row or not verify(old_password, row["password_hash"], row["salt"]):
            raise ValueError("رمز عبور فعلی اشتباه است")
    validate_password(new_password)
    h, salt = make_hash(new_password)
    with db.tx(con):
        con.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (h, salt, user_id))
        db.audit(con, "change_password", "users", user_id)


def set_current(user: dict | None) -> None:
    global _current_user
    _current_user = dict(user) if user else None


def current() -> dict | None:
    return _current_user


class service_mode:
    """Context manager قابل استفادهٔ مجدد برای اسکریپت‌های نگهداری/تست."""
    def __init__(self):
        self._stack = []

    def __enter__(self):
        global _service_mode
        self._stack.append(_service_mode)
        _service_mode = True
        return self

    def __exit__(self, *exc):
        global _service_mode
        _service_mode = self._stack.pop() if self._stack else False
        return False


def current_role() -> str:
    if _service_mode:
        return "service"
    return (_current_user or {}).get("role", "anonymous")


def has(perm: str) -> bool:
    if _service_mode:
        return True
    if _current_user is None:
        return False
    perms = _PERMS.get(_current_user.get("role", ""), set())
    return "*" in perms or perm in perms


def require(perm: str) -> None:
    if not has(perm):
        raise PermissionError(f"شما مجوز «{perm}» را ندارید (نقش فعلی: {ROLES.get(current_role(), current_role())})")


def role_label(role: str) -> str:
    return ROLES.get(role, role)
