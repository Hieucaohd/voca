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


def _batch(client, key, payload):
    return client.post("/api/v1/external/vocabulary/batch", json=payload, headers={"X-API-Key": key})


def test_single_capture_reports_status(client, alice, api_key):
    key = api_key["api_key"]
    assert _capture(client, key, {"word": "pivot"}).get_json()["status"] == "created"
    assert _capture(client, key, {"word": "pivot"}).get_json()["status"] == "unchanged"
    assert _capture(client, key, {"word": "pivot", "translation": "xoay trục"}).get_json()["status"] == "updated"


def test_batch_import_mixed_results(client, alice, api_key):
    key = api_key["api_key"]
    _capture(client, key, {"word": "hedge", "translation": "phòng hộ"})
    res = _batch(client, key, {
        "source": "quant_reader",
        "items": [
            {"word": "leverage", "translation": "đòn bẩy", "tags": ["Quant"], "context": {"sentence": "Banks leverage capital.", "source_title": "Quant book"}},
            "volatility",                                   # bare word shorthand
            {"word": "Hedge", "translation": "phòng hộ"},   # already known, nothing new
            {"word": "hedge", "context": "Funds hedge FX risk."},  # known, new context
            {"word": ""},                                   # invalid
            {"word": "chat", "language": "xx"},             # unsupported language
            42,                                             # not an object
        ],
    })
    assert res.status_code == 200
    body = res.get_json()
    assert body["summary"] == {"created": 2, "updated": 1, "unchanged": 1, "failed": 3, "total": 7}
    statuses = [r["status"] for r in body["results"]]
    assert statuses == ["created", "created", "unchanged", "updated", "failed", "failed", "failed"]
    assert [r["index"] for r in body["results"]] == list(range(7))
    assert body["results"][4]["error"]["code"] == "VALIDATION_ERROR"
    assert body["results"][5]["error"]["code"] == "VALIDATION_ERROR"

    leverage = alice.get(f"/api/v1/words/{body['results'][0]['id']}").get_json()
    assert leverage["tags"] == ["Quant"]
    assert leverage["contexts"][0]["captured_via"] == "quant_reader"
    volatility = alice.get(f"/api/v1/words/{body['results'][1]['id']}").get_json()
    assert volatility["enrichment_status"] == "pending"


def test_batch_limits_and_scope(client, alice, api_key):
    key = api_key["api_key"]
    assert _batch(client, key, {"items": []}).status_code == 422
    assert _batch(client, key, {"items": [f"w{i}" for i in range(101)]}).status_code == 422
    assert _batch(client, key, {"items": ["ok"], "collection_id": "missing"}).get_json()["results"][0]["error"]["code"] == "NOT_FOUND"

    app = alice.get("/api/v1/external/applications").get_json()["items"][0]
    read_only = alice.post(f"/api/v1/external/applications/{app['id']}/keys", {"scopes": ["vocabulary:read"]}).get_json()["api_key"]
    assert _batch(client, read_only, {"items": ["x"]}).status_code == 403


def test_batch_into_collection_and_list_collections(client, alice, bob, api_key):
    key = api_key["api_key"]
    deck = alice.post("/api/v1/collections", {"name": "IELTS"}).get_json()
    bob_deck = bob.post("/api/v1/collections", {"name": "Bob's"}).get_json()
    bob.post(f"/api/v1/collections/{bob_deck['id']}/share", {"email": "alice@example.com", "role": "editor"})

    listed = client.get("/api/v1/external/collections", headers={"X-API-Key": key}).get_json()["items"]
    by_name = {c["name"]: c for c in listed}
    assert by_name["Hộp thư từ mới"]["is_inbox"] is True
    assert by_name["IELTS"]["role"] == "owner"
    assert by_name["Bob's"]["role"] == "editor"

    body = _batch(client, key, {"collection_id": deck["id"], "items": ["abandon", {"word": "cohesion", "collection_id": bob_deck["id"]}]}).get_json()
    assert body["summary"]["created"] == 2
    assert alice.get(f"/api/v1/words?collection_id={deck['id']}").get_json()["total"] == 1
    assert bob.get(f"/api/v1/words?collection_id={bob_deck['id']}").get_json()["total"] == 1


def test_upsert_merges_tags_and_dedupes_sentence_less_contexts(client, alice, api_key):
    key = api_key["api_key"]
    first = _capture(client, key, {"word": "alpha", "tags": ["Quant"], "context": {"source_title": "Paper A", "location": "p.3"}}).get_json()
    again = _capture(client, key, {"word": "alpha", "tags": ["quant"], "context": {"source_title": "paper a", "location": "p.3"}}).get_json()
    assert again["status"] == "unchanged"
    more = _capture(client, key, {"word": "alpha", "tags": ["Finance"], "context": {"source_title": "Paper A", "location": "p.9"}}).get_json()
    assert (more["status"], more["context_added"]) == ("updated", True)
    word = alice.get(f"/api/v1/words/{first['id']}").get_json()
    assert word["tags"] == ["Finance", "Quant"]
    assert len(word["contexts"]) == 2
