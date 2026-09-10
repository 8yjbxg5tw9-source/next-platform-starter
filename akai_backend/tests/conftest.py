"""Shared fixtures: an isolated users.json + a live TestClient."""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(scope="module")
def env(tmp_path_factory):
    db_dir = tmp_path_factory.mktemp("db")
    users = db_dir / "users.json"
    users.write_text('{"users": []}', encoding="utf-8")
    os.environ["AKAI_USERS_FILE"] = str(users)
    os.environ["AKAI_SECRET_FILE"] = str(db_dir / "secret.key")
    from server import main as main_mod

    importlib.reload(main_mod)
    return main_mod


@pytest.fixture(scope="module")
def client(env):
    from fastapi.testclient import TestClient

    with TestClient(env.app) as handle:
        yield handle
