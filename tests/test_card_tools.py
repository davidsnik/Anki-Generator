"""Large lists stay bounded; selection changes and restoration preserve identities."""

import json

from sqlalchemy import select

from anki_generator.database.entities import Card, Revision


def make_card(client, course_id, question="Question"):
    response = client.post(
        f"/api/courses/{course_id}/cards", json={"question": question, "answer": "Answer"}
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_pagination_search_sort_and_facets_do_not_transfer_entire_deck(api_client, course):
    with api_client.app.state.runtime.sessions.begin() as session:
        session.add_all(
            [
                Card(
                    course_id=course["id"],
                    question=f"Question {index:05}",
                    answer="Answer",
                    tags=["tag"],
                )
                for index in range(2500)
            ]
        )
    page = api_client.get(f"/api/courses/{course['id']}/cards-page?limit=24&sort=question").json()
    assert page["total"] == 2500 and len(page["items"]) == 24
    assert page["items"][0]["question"] == "Question 00000"
    assert page["has_more"]
    assert len(json.dumps(page).encode()) < 60000
    next_page = api_client.get(
        f"/api/courses/{course['id']}/cards-page?offset=24&limit=24&sort=question"
    ).json()
    assert not (
        {card["id"] for card in page["items"]} & {card["id"] for card in next_page["items"]}
    )
    filtered = api_client.get(
        f"/api/courses/{course['id']}/cards-page", params={"q": "Question 02499"}
    ).json()
    assert filtered["total"] == 1
    assert filtered["items"][0]["question"] == "Question 02499"
    assert api_client.get(f"/api/courses/{course['id']}/cards-page?limit=1000").status_code == 422
    assert api_client.get(f"/api/courses/{course['id']}/cards-page?offset=-1").status_code == 422
    assert page["facets"]["card_types"] == ["basic"]
    stats = api_client.get(f"/api/courses/{course['id']}").json()["stats"]
    assert stats["cards"] == stats["pending_review"] == 2500


def test_literal_wildcards_and_source_filter_are_bound_parameters(
    api_client, course, extracted_source
):
    source = extracted_source["document"]
    first = api_client.post(
        f"/api/courses/{course['id']}/cards",
        json={
            "question": "Probability is 50%",
            "answer": "One half",
            "sources": [{"document_id": source["id"], "page_number": 1, "quote": "continuous"}],
        },
    ).json()
    make_card(api_client, course["id"], "Another question")
    for params in [{"q": "%"}, {"document_id": source["id"]}]:
        response = api_client.get(f"/api/courses/{course['id']}/cards-page", params=params)
        assert response.status_code == 200, response.text
        assert [card["id"] for card in response.json()["items"]] == [first["id"]]


def test_bulk_updates_exact_selection_and_stale_revisions_are_atomic(api_client, course):
    cards = [make_card(api_client, course["id"], f"Q {i}") for i in range(3)]
    selected = cards[:2]
    payload = {
        "card_ids": [card["id"] for card in selected],
        "expected_revisions": {card["id"]: 1 for card in selected},
        "action": "tags",
        "tags_add": ["reviewed-together"],
    }
    changed = api_client.post(f"/api/courses/{course['id']}/cards/bulk", json=payload)
    assert changed.status_code == 200, changed.text
    assert changed.json()["affected"] == 2
    assert all(card["revision_number"] == 2 for card in changed.json()["items"])
    assert api_client.get(f"/api/cards/{cards[2]['id']}").json()["tags"] == []
    assert (
        api_client.post(
            f"/api/courses/{course['id']}/cards/bulk", json={**payload, "tags_add": ["stale"]}
        ).status_code
        == 400
    )
    assert "stale" not in api_client.get(f"/api/cards/{cards[0]['id']}").json()["tags"]
    assert (
        api_client.post(
            f"/api/courses/{course['id']}/cards/bulk",
            json={**payload, "card_ids": [cards[0]["id"]]},
        ).status_code
        == 422
    )


def test_failed_bulk_approval_does_not_approve_earlier_cards(api_client, course):
    cards = [make_card(api_client, course["id"], f"Q {i}") for i in range(2)]
    with api_client.app.state.runtime.sessions.begin() as session:
        session.get(Card, cards[0]["id"]).verification_status = "verified"
        session.get(Card, cards[1]["id"]).verification_status = "failed"
    payload = {
        "card_ids": [card["id"] for card in cards],
        "expected_revisions": {card["id"]: 1 for card in cards},
        "action": "approve",
        "reason": "Synthetic selection test",
    }
    assert (
        api_client.post(f"/api/courses/{course['id']}/cards/bulk", json=payload).status_code == 400
    )
    assert all(
        api_client.get(f"/api/cards/{card['id']}").json()["review_status"] == "pending"
        for card in cards
    )
    payload.update(action="reject")
    assert (
        api_client.post(f"/api/courses/{course['id']}/cards/bulk", json=payload).status_code == 400
    )
    payload["confirm"] = True
    assert (
        api_client.post(f"/api/courses/{course['id']}/cards/bulk", json=payload).status_code == 200
    )


def test_revision_restore_appends_history_preserves_guid_and_resets_checks(api_client, course):
    card = make_card(api_client, course["id"], "Original question")
    edited = api_client.patch(
        f"/api/cards/{card['id']}",
        json={"question": "New question", "tags": ["changed"], "expected_revision": 1},
    ).json()
    assert edited["revision_number"] == 2
    diff = api_client.get(f"/api/cards/{card['id']}/revision-diff?before=1").json()
    assert {item["field"] for item in diff["fields"] if item["changed"]} == {"question", "tags"}
    payload = {"revision_number": 1, "expected_revision": 2, "confirm": True}
    restored = api_client.post(f"/api/cards/{card['id']}/restore", json=payload)
    assert restored.status_code == 200, restored.text
    result = restored.json()
    assert result["question"] == "Original question" and result["tags"] == []
    assert result["note_guid"] == card["note_guid"] and result["id"] == card["id"]
    assert result["revision_number"] == 3 and result["verification_status"] == "unverified"
    assert result["review_status"] == "pending"
    with api_client.app.state.runtime.sessions() as session:
        revision = session.scalar(
            select(Revision).where(Revision.card_id == card["id"], Revision.revision_number == 3)
        )
        assert revision.origin == "human_restore"
    assert api_client.post(f"/api/cards/{card['id']}/restore", json=payload).status_code == 400
