# -*- coding: utf-8 -*-
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@pytest.fixture()
def con(tmp_path, monkeypatch):
    monkeypatch.setenv("ACC_DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setenv("ACC_DATA_DIR", str(tmp_path))
    import auth
    import db
    with auth.service_mode():
        c = db.connect()
        db.init_db(c)
        yield c
        c.close()


# `tests/test_ui.py` یک **اسکریپت سناریویی** است، نه ماژول pytest: به‌محض import
# QApplication می‌سازد، `ACC_DB_PATH` را عوض می‌کند و `auth.service_mode()` را برای
# همیشه روشن می‌گذارد. جمع‌آوری آن توسط pytest این وضعیت را به بقیهٔ تست‌ها نشت
# می‌دهد و در محیطی که Qt کامل نصب است اجرای `pytest` را می‌شکند. اجرای آن همچنان
# از راه `QT_QPA_PLATFORM=offscreen python tests/test_ui.py` و گام جداگانهٔ CI است.
collect_ignore = ["test_ui.py"]
