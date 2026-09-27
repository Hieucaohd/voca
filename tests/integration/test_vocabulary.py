def test_create_full_word(alice):
    res = alice.post(
        "/api/v1/words",
        {
            "word": "  abandon ",
            "phonetic": "/əˈbændən/",
            "difficulty": "B2",
            "senses": [
                {
                    "part_of_speech": "verb",
                    "definition": "to stop doing something",
                    "translation": "từ bỏ",
                    "synonyms": ["quit", "leave", "quit"],
                    "examples": [{"sentence": "He abandoned his car.", "translation": "Anh ấy bỏ lại xe."}],
                }
            ],
            "tags": ["IELTS", "Business"],
            "contexts": [{"sentence": "They abandoned the plan.", "source_title": "IELTS Cambridge 18", "location": "Test 2"}],
        },
    )
    assert res.status_code == 201
    word = res.get_json()
    assert word["word"] == "abandon"
    assert word["meaning"] == "từ bỏ"
    assert word["senses"][0]["synonyms"] == ["quit", "leave"]
    assert word["senses"][0]["translation_language"] == "vi"
    assert word["tags"] == ["Business", "IELTS"]
    assert word["contexts"][0]["source"]["title"] == "IELTS Cambridge 18"
    assert word["progress"]["status"] == "NEW"


def test_duplicate_is_conflict_case_insensitive(alice):
    first = alice.add_word("Leverage")
    res = alice.post("/api/v1/words", {"word": "leverage"})
    assert res.status_code == 409
    assert res.get_json()["error"]["details"]["existing_id"] == first["id"]


def test_same_text_other_language_allowed(alice):
    alice.add_word("chat")
    res = alice.post("/api/v1/words", {"word": "chat", "language": "fr", "senses": [{"translation": "con mèo"}]})
    assert res.status_code == 201


def test_unknown_language_and_empty_sense(alice):
    assert alice.post("/api/v1/words", {"word": "x", "language": "xx"}).status_code == 422
    assert alice.post("/api/v1/words", {"word": "x", "senses": [{"part_of_speech": "noun"}]}).status_code == 422


def test_search_and_filters(alice):
    alice.add_word("abandon", "từ bỏ", tags=["IELTS"])
    alice.add_word("leverage", "đòn bẩy", tags=["Finance"])
    alice.add_word("derivative", "phái sinh", tags=["Finance"])

    def words(query):
        return [w["word"] for w in alice.get(f"/api/v1/words?{query}").get_json()["items"]]

    assert words("q=lev") == ["leverage"]
    assert words("q=đòn") == ["leverage"]  # meaning search
    assert sorted(words("tag=finance")) == ["derivative", "leverage"]
    assert words("sort=alpha") == ["abandon", "derivative", "leverage"]
    assert len(words("status=NEW")) == 3
    body = alice.get("/api/v1/words?per_page=2&page=2").get_json()
    assert body["total"] == 3 and len(body["items"]) == 1


def test_update_replaces_senses_and_tags(alice):
    word = alice.add_word("run", "chạy", tags=["a"])
    res = alice.put(
        f"/api/v1/words/{word['id']}",
        {"senses": [{"translation": "điều hành", "part_of_speech": "verb"}, {"translation": "chạy"}], "tags": ["b"], "notes": "ghi chú"},
    )
    body = res.get_json()
    assert [s["translation"] for s in body["senses"]] == ["điều hành", "chạy"]
    assert body["tags"] == ["b"]
    assert body["notes"] == "ghi chú"


def test_rename_to_existing_conflicts(alice):
    alice.add_word("alpha")
    beta = alice.add_word("beta")
    assert alice.put(f"/api/v1/words/{beta['id']}", {"word": "ALPHA"}).status_code == 409


def test_contexts_add_and_remove(alice):
    word = alice.add_word("hedge", "phòng hộ")
    res = alice.post(f"/api/v1/words/{word['id']}/contexts", {"sentence": "Funds hedge risk.", "source_title": "Quant book"})
    assert res.status_code == 201
    ctx_id = res.get_json()["id"]
    sources = alice.get("/api/v1/sources").get_json()["items"]
    assert [s["title"] for s in sources] == ["Quant book"]
    assert alice.get(f"/api/v1/words?source_id={sources[0]['id']}").get_json()["total"] == 1
    assert alice.delete(f"/api/v1/words/{word['id']}/contexts/{ctx_id}").status_code == 204
    assert alice.post(f"/api/v1/words/{word['id']}/contexts", {}).status_code == 422


def test_private_words_are_invisible_to_others(alice, bob):
    word = alice.add_word("secret")
    assert bob.get(f"/api/v1/words/{word['id']}").status_code == 404
    assert bob.put(f"/api/v1/words/{word['id']}", {"notes": "x"}).status_code == 404
    assert bob.delete(f"/api/v1/words/{word['id']}").status_code == 404
    assert bob.get("/api/v1/words").get_json()["total"] == 0


def test_delete_removes_progress(alice):
    word = alice.add_word("gone")
    alice.post(f"/api/v1/reviews/{word['id']}/result", {"mode": "flashcard", "grade": "good"})
    assert alice.delete(f"/api/v1/words/{word['id']}").status_code == 204
    assert alice.get(f"/api/v1/words/{word['id']}").status_code == 404


def test_web_pages_render(client, alice):
    client.post("/login", data={"email": "alice@example.com", "password": "password123"})
    word = alice.add_word("render", "hiển thị", contexts=[{"sentence": "We render pages.", "source_title": "Docs"}])
    for url in ["/dashboard", "/vocabulary", "/vocabulary?q=ren", "/vocabulary/_list?q=ren", "/vocabulary/new",
                f"/vocabulary/{word['id']}", f"/vocabulary/{word['id']}/edit", "/collections", "/collections?scope=public",
                "/learn", "/statistics", "/settings"]:
        res = client.get(url)
        assert res.status_code == 200, url
    assert "render" in client.get("/vocabulary/_list?q=ren").get_data(as_text=True)


def test_delete_word_with_tags_and_collections(alice):
    deck = alice.post("/api/v1/collections", {"name": "Deck"}).get_json()
    word = alice.add_word("tagged", tags=["x", "y"], collection_ids=[deck["id"]],
                          contexts=[{"sentence": "A tagged word.", "source_title": "Src"}])
    assert alice.delete(f"/api/v1/words/{word['id']}").status_code == 204
    assert alice.get("/api/v1/tags").get_json()["items"] == [{"name": "x", "count": 0}, {"name": "y", "count": 0}]
    assert alice.get(f"/api/v1/collections/{deck['id']}").get_json()["word_count"] == 0
