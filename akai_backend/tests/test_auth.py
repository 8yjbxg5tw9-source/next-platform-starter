"""License API behaviour: credentials, HWID lock, expiry, tokens."""

from __future__ import annotations

import datetime as dt

from server.security import sha256_hex

HWID_A = "AKAI-98F2-41A7-B800"
HWID_B = "AKAI-1111-2222-3333"


def _login(client, username, password, hwid=HWID_A):
    return client.post("/api/v1/login", json={
        "username": username,
        "password_hash": sha256_hex(password),
        "hwid": hwid,
    })


def test_health(client):
    body = client.get("/api/v1/health")
    assert body.status_code == 200
    assert body.json()["status"] == "ok"


def test_login_success_and_token_verify(client, env):
    env._store.add_user("ahmed", "pin1234", hwid=HWID_A, days=30)
    resp = _login(client, "ahmed", "pin1234")
    assert resp.status_code == 200, resp.text
    token = resp.json()["token"]
    assert token and "." in token

    verified = client.get("/api/v1/verify",
                          headers={"Authorization": f"Bearer {token}"})
    assert verified.status_code == 200
    assert verified.json()["username"] == "ahmed"


def test_wrong_password_is_401(client, env):
    env._store.add_user("leyla", "secret1", hwid=HWID_A)
    resp = _login(client, "leyla", "wrong-pass")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "İstifadəçi adı və ya şifrə yanlışdır."


def test_unknown_user_is_401(client):
    resp = _login(client, "ghost", "whatever")
    assert resp.status_code == 401


def test_hwid_lock_blocks_second_device(client, env):
    env._store.add_user("rufat", "pin999", hwid=HWID_A)
    assert _login(client, "rufat", "pin999", HWID_A).status_code == 200
    blocked = _login(client, "rufat", "pin999", HWID_B)
    assert blocked.status_code == 403
    assert blocked.json()["detail"] == "Bu abunəlik başqa cihazda aktivdir!"


def test_first_login_binds_empty_hwid(client, env):
    env._store.add_user("nigar", "pin555")  # hwid empty
    assert _login(client, "nigar", "pin555", HWID_A).status_code == 200
    # same credentials from another machine must now be rejected
    stolen = _login(client, "nigar", "pin555", HWID_B)
    assert stolen.status_code == 403


def test_expired_subscription_is_403(client, env):
    env._store.add_user("kamran", "pin000", hwid=HWID_A)
    record = env._store.get("kamran")
    record["expires_at"] = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    resp = _login(client, "kamran", "pin000")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Abunəlik müddəti bitmişdir."


def test_disabled_account_is_403(client, env):
    env._store.add_user("sabir", "pin111", hwid=HWID_A, status="disabled")
    assert _login(client, "sabir", "pin111").status_code == 403


def test_garbage_token_is_401(client):
    resp = client.get("/api/v1/verify", headers={"Authorization": "Bearer abc.def"})
    assert resp.status_code == 401


def test_passwords_are_stored_as_digests_only(env, tmp_path):
    env._store.add_user("test_hash", "my-plain-secret", hwid=HWID_A)
    raw = env._store._path.read_text(encoding="utf-8")
    assert "my-plain-secret" not in raw
    assert sha256_hex("my-plain-secret") in raw
