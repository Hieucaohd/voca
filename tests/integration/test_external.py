import pytest


@pytest.fixture()
def api_key(alice):
    app = alice.post("/api/v1/external/applications", {"name": "Realtime Caption"}).get_json()
    res = alice.post(f"/api/v1/external/applications/{app['id']}/keys")
    assert res.status_code == 201
    return res.get_json()


def _capture(client, key, payload):
    return client.post("/api/v1/external/vocabulary", json=payload, headers={"X-API-Key": key})


def test_capture_creates_word_in_inbox(client, alice, api_key):
    res = _capture(client, api_key["api_key"], {
        "word": "leverage", "language": "en", "meaning": "use something effectively", "translation": "tận dụng",
        "context": {"sentence": "Financial institutions leverage derivatives.", "source_title": "Quant book", "location": "ch.3"},
        "source": "browser_extension",
    })
    assert res.status_code == 201
    body = res.get_json()
    assert body["created"] is True

    word = alice.get(f"/api/v1/words/{body['id']}").get_json()
    assert word["source_type"] == "external"
    assert word["meaning"] == "tận dụng"
    assert word["contexts"][0]["captured_via"] == "browser_extension"
    assert [c["name"] for c in word["collections"]] == ["Hộp thư từ mới"]


def test_capture_is_upsert(client, alice, api_key):
    key = api_key["api_key"]
    first = _capture(client, key, {"word": "hedge"}).get_json()
    assert alice.get(f"/api/v1/words/{first['id']}").get_json()["enrichment_status"] == "pending"

    again = _capture(client, key, {"word": "Hedge", "translation": "phòng hộ", "context": "Funds hedge currency risk."})
    assert again.status_code == 200
    body = again.get_json()
    assert (body["id"], body["created"], body["sense_added"], body["context_added"]) == (first["id"], False, True, True)

    dup = _capture(client, key, {"word": "hedge", "translation": "phòng hộ", "context": "Funds hedge currency risk."}).get_json()
    assert (dup["sense_added"], dup["context_added"]) == (False, False)
    word = alice.get(f"/api/v1/words/{first['id']}").get_json()
    assert word["enrichment_status"] == "done"
    assert len(word["senses"]) == 1 and len(word["contexts"]) == 1


def test_capture_into_default_collection(client, alice):
    deck = alice.post("/api/v1/collections", {"name": "Captions"}).get_json()
    app = alice.post("/api/v1/external/applications", {"name": "Caption", "default_collection_id": deck["id"]}).get_json()
    key = alice.post(f"/api/v1/external/applications/{app['id']}/keys").get_json()["api_key"]
    body = _capture(client, key, {"word": "subtitle"}).get_json()
    names = [c["name"] for c in alice.get(f"/api/v1/words/{body['id']}").get_json()["collections"]]
    assert names == ["Captions"]


def test_lookup(client, alice, api_key):
    key = api_key["api_key"]
    assert client.get("/api/v1/external/vocabulary/lookup?word=nope", headers={"X-API-Key": key}).get_json() == {"found": False}
    _capture(client, key, {"word": "yield", "translation": "lợi suất"})
    found = client.get("/api/v1/external/vocabulary/lookup?word=YIELD", headers={"X-API-Key": key}).get_json()
    assert found["found"] is True and found["meaning"] == "lợi suất"


def test_invalid_and_revoked_keys(client, alice, api_key):
    assert _capture(client, "", {"word": "x"}).status_code == 401
    assert _capture(client, "voca_bad_key", {"word": "x"}).status_code == 401
    raw = api_key["api_key"]
    tampered = raw[:-2] + ("AA" if not raw.endswith("AA") else "BB")
    assert _capture(client, tampered, {"word": "x"}).status_code == 401

    assert alice.delete(f"/api/v1/external/keys/{api_key['id']}").status_code == 204
    res = _capture(client, raw, {"word": "x"})
    assert res.status_code == 401
    assert res.headers["Access-Control-Allow-Origin"] == "*"  # errors stay readable cross-origin


def test_cors_preflight(client):
    res = client.options("/api/v1/external/vocabulary", headers={"Origin": "chrome-extension://abc", "Access-Control-Request-Method": "POST"})
    assert res.status_code == 200
    assert "X-API-Key" in res.headers["Access-Control-Allow-Headers"]


def test_keys_are_private_to_owner(alice, bob, api_key):
    assert bob.delete(f"/api/v1/external/keys/{api_key['id']}").status_code == 404
    assert bob.get("/api/v1/external/applications").get_json()["items"] == []
    listed = alice.get("/api/v1/external/applications").get_json()["items"][0]["keys"][0]
    assert "api_key" not in listed and listed["is_active"] is True
