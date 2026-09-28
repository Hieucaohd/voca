def _create(api, name, **extra):
    res = api.post("/api/v1/collections", {"name": name, **extra})
    assert res.status_code == 201, res.get_json()
    return res.get_json()


def test_nested_collections_and_words(alice):
    ielts = _create(alice, "My IELTS")
    academic = _create(alice, "Academic words", parent_id=ielts["id"])
    word = alice.add_word("hypothesis", "giả thuyết", collection_ids=[academic["id"]])

    items = alice.get("/api/v1/collections").get_json()["items"]
    names = [c["name"] for c in items]
    assert names.index("My IELTS") < names.index("Academic words")
    assert {c["name"]: c["word_count"] for c in items}["Academic words"] == 1

    assert alice.get(f"/api/v1/words?collection_id={academic['id']}").get_json()["total"] == 1
    assert alice.delete(f"/api/v1/collections/{academic['id']}/words/{word['id']}").status_code == 204
    assert alice.get(f"/api/v1/words?collection_id={academic['id']}").get_json()["total"] == 0


def test_cycle_prevention(alice):
    a = _create(alice, "A")
    b = _create(alice, "B", parent_id=a["id"])
    res = alice.patch(f"/api/v1/collections/{a['id']}", {"parent_id": b["id"]})
    assert res.status_code == 422


def test_delete_collection_keeps_words_and_lifts_children(alice):
    parent = _create(alice, "Parent")
    child = _create(alice, "Child", parent_id=parent["id"])
    word = alice.add_word("keep", collection_ids=[parent["id"]])
    assert alice.delete(f"/api/v1/collections/{parent['id']}").status_code == 204
    assert alice.get(f"/api/v1/words/{word['id']}").status_code == 200
    assert alice.get(f"/api/v1/collections/{child['id']}").get_json()["parent_id"] is None


def test_inbox_is_protected(alice):
    inbox = alice.get("/api/v1/collections").get_json()["items"][0]
    assert alice.delete(f"/api/v1/collections/{inbox['id']}").status_code == 422
    assert alice.patch(f"/api/v1/collections/{inbox['id']}", {"visibility": "public"}).status_code == 422


def test_private_collection_hidden(alice, bob):
    c = _create(alice, "Private")
    assert bob.get(f"/api/v1/collections/{c['id']}").status_code == 404
    assert bob.post(f"/api/v1/collections/{c['id']}/join").status_code == 404


def test_share_viewer_and_editor(alice, bob, client):
    from tests.conftest import Api

    carol = Api(client, "carol@example.com", "Carol")
    c = _create(alice, "IELTS 5000 words")
    word = alice.add_word("abandon", "từ bỏ", collection_ids=[c["id"]])

    assert alice.post(f"/api/v1/collections/{c['id']}/share", {"email": "bob@example.com", "role": "viewer"}).status_code == 201
    assert alice.post(f"/api/v1/collections/{c['id']}/share", {"email": "carol@example.com", "role": "editor"}).status_code == 201
    assert alice.post(f"/api/v1/collections/{c['id']}/share", {"email": "nobody@example.com"}).status_code == 404
    assert alice.get(f"/api/v1/collections/{c['id']}").get_json()["visibility"] == "shared"

    # viewer: read yes, write no
    assert bob.get(f"/api/v1/words/{word['id']}").status_code == 200
    assert bob.put(f"/api/v1/words/{word['id']}", {"notes": "x"}).status_code == 403
    bob_word = bob.add_word("mine")
    assert bob.post(f"/api/v1/collections/{c['id']}/words", {"vocabulary_ids": [bob_word["id"]]}).status_code == 403

    # editor: can edit words in it and add their own
    assert carol.put(f"/api/v1/words/{word['id']}", {"notes": "edited"}).status_code == 200
    carol_word = carol.add_word("curriculum", "chương trình học")
    assert carol.post(f"/api/v1/collections/{c['id']}/words", {"vocabulary_ids": [carol_word["id"]]}).status_code == 200
    assert carol.delete(f"/api/v1/words/{word['id']}").status_code == 403  # only the owner deletes

    shared = [x["name"] for x in bob.get("/api/v1/collections?scope=shared").get_json()["items"]]
    assert shared == ["IELTS 5000 words"]
    members = alice.get(f"/api/v1/collections/{c['id']}/members").get_json()["items"]
    assert {m["email"]: m["role"] for m in members} == {"bob@example.com": "viewer", "carol@example.com": "editor"}

    # owner can downgrade/remove; members can leave
    assert alice.patch(f"/api/v1/collections/{c['id']}/members/{carol.user['id']}", {"role": "viewer"}).status_code == 200
    assert carol.put(f"/api/v1/words/{word['id']}", {"notes": "again"}).status_code == 403
    assert bob.post(f"/api/v1/collections/{c['id']}/leave").status_code == 204
    assert bob.get(f"/api/v1/collections/{c['id']}").status_code == 404


def test_public_collection_is_only_learned_after_starting(alice, bob):
    c = _create(alice, "Public deck", visibility="public")
    alice.add_word("serendipity", "tình cờ may mắn", collection_ids=[c["id"]])

    listed = [x["name"] for x in bob.get("/api/v1/collections?scope=public").get_json()["items"]]
    assert listed == ["Public deck"]
    assert bob.get(f"/api/v1/collections/{c['id']}").get_json()["role"] == "public"

    # Joining alone does not schedule anything.
    assert bob.post(f"/api/v1/collections/{c['id']}/join").status_code == 200
    assert bob.get("/api/v1/reviews/today").get_json()["items"] == []

    bob.start(c["id"])
    assert [i["word"] for i in bob.get("/api/v1/reviews/today").get_json()["items"]] == ["serendipity"]

    # Leaving a public collection keeps the plan readable; leaving a private one drops it.
    assert bob.post(f"/api/v1/collections/{c['id']}/leave").status_code == 204
    assert [p["collection_id"] for p in bob.get("/api/v1/study/plans").get_json()["items"]] == [c["id"]]


def test_losing_access_removes_the_plan(alice, bob):
    c = _create(alice, "Private deck")
    alice.add_word("secretive", collection_ids=[c["id"]])
    alice.post(f"/api/v1/collections/{c['id']}/share", {"email": "bob@example.com"})
    bob.start(c["id"])
    assert len(bob.get("/api/v1/reviews/today").get_json()["items"]) == 1
    alice.delete(f"/api/v1/collections/{c['id']}/members/{bob.user['id']}")
    assert bob.get("/api/v1/study/plans").get_json()["items"] == []
    assert bob.get("/api/v1/reviews/today").get_json()["items"] == []


def test_share_link_join(client, alice, bob):
    c = _create(alice, "Link deck")
    token = alice.post(f"/api/v1/collections/{c['id']}/share-link", {"enabled": True}).get_json()["share_token"]
    assert token
    assert bob.post(f"/api/v1/collections/{c['id']}/join", {"token": "wrong"}).status_code == 404
    assert bob.post(f"/api/v1/collections/{c['id']}/join", {"token": token}).status_code == 200
    # the owner-only token is not exposed to members
    assert "share_token" not in bob.get(f"/api/v1/collections/{c['id']}").get_json()


def test_collection_web_pages(client, alice):
    client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    c = _create(alice, "Web deck", visibility="public")
    alice.add_word("page", collection_ids=[c["id"]])
    assert client.get(f"/collections/{c['id']}").status_code == 200
    assert client.get(f"/collections/{c['id']}/_candidates?q=pa").status_code == 200
    assert client.get(f"/learn?collection_id={c['id']}").status_code == 200
