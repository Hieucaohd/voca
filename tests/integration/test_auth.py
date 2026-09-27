from datetime import timedelta

from app.core.clock import utcnow
from app.extensions import db
from app.modules.auth.models import RefreshToken


def test_register_login_me(client, alice):
    assert alice.get("/api/v1/me").get_json()["email"] == "alice@example.com"
    res = client.post("/api/v1/auth/login", json={"email": "ALICE@example.com", "password": "password123"})
    assert res.status_code == 200
    assert res.get_json()["token_type"] == "Bearer"


def test_register_creates_inbox(alice):
    items = alice.get("/api/v1/collections").get_json()["items"]
    assert [c["system_key"] for c in items] == ["inbox"]


def test_duplicate_email_and_validation(client, alice):
    res = client.post("/api/v1/auth/register", json={"email": "alice@example.com", "password": "password123", "display_name": "A"})
    assert res.status_code == 409
    res = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": "short", "display_name": ""})
    assert res.status_code == 422
    fields = {d["field"] for d in res.get_json()["error"]["details"]}
    assert {"email", "password", "display_name"} <= fields


def test_wrong_password(client, alice):
    res = client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "nope-nope"})
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] == "UNAUTHORIZED"


def test_requires_auth(client):
    res = client.get("/api/v1/me")
    assert res.status_code == 401
    assert "request_id" in res.get_json()


def test_refresh_rotation_and_reuse_detection(client, alice):
    first = alice.refresh_token
    res = client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {first}"})
    assert res.status_code == 200
    second = res.get_json()["refresh_token"]

    # Reusing the rotated token inside the grace window is tolerated (parallel tabs)...
    assert client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {first}"}).status_code == 200

    # ...but outside it, the whole family is revoked.
    for token in db.session.query(RefreshToken).filter(RefreshToken.revoked_at.isnot(None)):
        token.revoked_at = utcnow() - timedelta(minutes=5)
    db.session.commit()
    assert client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {first}"}).status_code == 401
    assert client.post("/api/v1/auth/refresh", headers={"Authorization": f"Bearer {second}"}).status_code == 401


def test_logout_revokes_refresh(client, alice):
    headers = {"Authorization": f"Bearer {alice.refresh_token}"}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.post("/api/v1/auth/refresh", headers=headers).status_code == 401


def test_update_profile_and_password(client, alice):
    res = alice.patch("/api/v1/me", {"daily_goal": 30, "timezone": "Asia/Tokyo"})
    assert res.get_json()["daily_goal"] == 30
    assert alice.patch("/api/v1/me", {"timezone": "Mars/Base"}).status_code == 422
    assert alice.post("/api/v1/me/password", {"current_password": "wrong", "new_password": "newpassword1"}).status_code == 422
    assert alice.post("/api/v1/me/password", {"current_password": "password123", "new_password": "newpassword1"}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"email": "alice@example.com", "password": "newpassword1"}).status_code == 200


# ---------------------------------------------------------------- web (cookie) flow

def _cookie(client, name):
    cookie = client.get_cookie(name)
    return cookie.value if cookie else None


def test_web_login_sets_cookies_and_csrf_is_enforced(client, alice):
    res = client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    assert res.status_code == 302
    assert _cookie(client, "access_token_cookie")

    assert client.get("/dashboard").status_code == 200
    # Cookie-authenticated mutation without the CSRF header is rejected.
    res = client.patch("/api/v1/me", json={"daily_goal": 5})
    assert res.status_code == 401
    res = client.patch("/api/v1/me", json={"daily_goal": 5}, headers={"X-CSRF-TOKEN": _cookie(client, "csrf_access_token")})
    assert res.status_code == 200


def test_web_pages_redirect_when_logged_out(client):
    res = client.get("/vocabulary")
    assert res.status_code == 302
    assert "/login" in res.headers["Location"]


def test_web_silently_refreshes_expired_access_cookie(client, alice):
    client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    client.delete_cookie("access_token_cookie")
    res = client.get("/dashboard")
    assert res.status_code == 200
    assert _cookie(client, "access_token_cookie")  # re-issued


def test_web_logout(client, alice):
    client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    client.get("/dashboard")
    res = client.post("/logout", data={"csrf_token": _cookie(client, "csrf_refresh_token")})
    assert res.status_code == 302
    assert client.get("/dashboard").status_code == 302


def test_login_rejects_open_redirect(client, alice):
    res = client.post("/login", data={"email": "alice@example.com", "password": "password123", "next": "//evil.com"})
    assert res.headers["Location"].endswith("/dashboard")


def test_static_assets_served(client):
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/api.js").status_code == 200
    assert client.get("/static/openapi.yaml").status_code == 200
    assert client.get("/favicon.ico").status_code == 302
