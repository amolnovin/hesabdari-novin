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
