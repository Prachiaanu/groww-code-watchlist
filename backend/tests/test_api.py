"""End-to-end API tests through the real ASGI app (TestClient runs the lifespan)."""

from __future__ import annotations

import itertools

_counter = itertools.count()


def _login(client, email=None):
    email = email or f"user{next(_counter)}@example.com"
    r = client.post("/api/auth/login", json={"email": email, "display_name": "Reshu"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_login_returns_token(client):
    r = client.post("/api/auth/login", json={"email": "a@b.com"})
    assert r.status_code == 200
    body = r.json()
    assert body["token"] and body["email"] == "a@b.com"


def test_login_rejects_bad_email(client):
    r = client.post("/api/auth/login", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_watchlist_requires_auth(client):
    assert client.get("/api/watchlist").status_code == 401
    assert client.get("/api/watchlist", headers={"Authorization": "Bearer garbage"}).status_code == 401


def test_instruments_are_public(client):
    r = client.get("/api/instruments")
    assert r.status_code == 200
    symbols = {i["symbol"] for i in r.json()}
    assert "RELIANCE" in symbols and "ZOMATO" in symbols


def test_add_list_remove_flow(client):
    h = _login(client)
    assert client.get("/api/watchlist", headers=h).json()["items"] == []

    r = client.post("/api/watchlist/items", json={"symbol": "RELIANCE"}, headers=h)
    assert r.status_code == 201
    view = r.json()
    assert [i["symbol"] for i in view["items"]] == ["RELIANCE"]
    assert view["items"][0]["price"] > 0
    assert "attention" in view["items"][0]

    r = client.delete("/api/watchlist/items/RELIANCE", headers=h)
    assert r.status_code == 200 and r.json()["items"] == []


def test_add_unknown_symbol_404(client):
    h = _login(client)
    r = client.post("/api/watchlist/items", json={"symbol": "FAKE"}, headers=h)
    assert r.status_code == 404


def test_add_duplicate_409(client):
    h = _login(client)
    client.post("/api/watchlist/items", json={"symbol": "TCS"}, headers=h)
    r = client.post("/api/watchlist/items", json={"symbol": "TCS"}, headers=h)
    assert r.status_code == 409


def test_symbol_is_case_insensitive(client):
    h = _login(client)
    r = client.post("/api/watchlist/items", json={"symbol": "infy"}, headers=h)
    assert r.status_code == 201
    assert "INFY" in [i["symbol"] for i in r.json()["items"]]


def test_alerts_add_and_clear(client):
    h = _login(client)
    r = client.post("/api/watchlist/items", json={"symbol": "SBIN", "alert_above": 900}, headers=h)
    assert r.json()["items"][0]["alert_above"] == 900
    r = client.patch("/api/watchlist/items/SBIN", json={"clear_alerts": True}, headers=h)
    assert r.json()["items"][0]["alert_above"] is None


def test_mark_seen_sets_baseline(client):
    h = _login(client)
    client.post("/api/watchlist/items", json={"symbol": "HDFCBANK"}, headers=h)
    assert client.get("/api/watchlist", headers=h).json()["items"][0]["seen"] is None
    r = client.post("/api/watchlist/seen", json={}, headers=h)
    assert r.json()["marked_seen"] == 1
    assert r.json()["items"][0]["seen"] is not None


def test_health_is_public_and_log_verify_requires_auth(client):
    assert client.get("/api/health").json()["status"] == "ok"
    assert client.get("/api/log/verify").status_code == 401  # now authenticated
    h = _login(client)
    v = client.get("/api/log/verify", headers=h).json()
    assert v["ok"] is True


def test_stream_token_scoping(client):
    h = _login(client)
    session_token = h["Authorization"].split()[1]

    # must be authenticated to mint a stream token
    assert client.post("/api/auth/stream-token").status_code == 401
    st = client.post("/api/auth/stream-token", headers=h).json()["stream_token"]
    assert st and st != session_token

    # a stream token is read-only: it cannot authenticate a normal (session) endpoint
    assert client.get("/api/watchlist", headers={"Authorization": f"Bearer {st}"}).status_code == 401
    # and the long-lived session token must NOT be accepted in the stream URL
    assert client.get(f"/api/stream?token={session_token}").status_code == 401


def test_users_are_isolated(client):
    h1, h2 = _login(client), _login(client)
    client.post("/api/watchlist/items", json={"symbol": "ITC"}, headers=h1)
    assert [i["symbol"] for i in client.get("/api/watchlist", headers=h1).json()["items"]] == ["ITC"]
    assert client.get("/api/watchlist", headers=h2).json()["items"] == []
