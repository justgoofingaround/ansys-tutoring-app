"""Editing an already-uploaded quiz from the instructor UI.

Quizzes are unversioned: saving replaces the questions in place. The one trap
is boot-time seeding from mock_server/data/quizzes/, which would otherwise undo
an edit on the next restart — see the edited_in_app tests at the end.
"""

import copy

from fastapi.testclient import TestClient

from server import db as dbmod
from server.app import create_app
from server.services import quiz_store

from .conftest import login, register_student

QUIZ = "quiz_tut1_3d_bar"


def _load(client, quiz_id=QUIZ):
    r = client.get(f"/api/instructor/quizzes/{quiz_id}/content")
    assert r.status_code == 200, r.text
    return r.json()


def _save(client, quiz, quiz_id=QUIZ):
    return client.post(f"/api/instructor/quizzes/{quiz_id}/content", json=quiz)


def _as_payload(quiz):
    """The editor posts the authoring shape (no question_id/position)."""
    return {
        "quiz_id": quiz["quiz_id"],
        "tutorial_id": quiz["tutorial_id"],
        "title": quiz["title"],
        "questions": [
            {
                "text": q["text"],
                "options": q["options"],
                "correct_index": q["correct_index"],
                "concept_tag": q.get("concept_tag", ""),
                "explanation": q.get("explanation", ""),
            }
            for q in quiz["questions"]
        ],
    }


# --- loading ----------------------------------------------------------------


def test_editor_sees_answers_and_explanations(client, seeded):
    login(client, "prof", "prof-pass-123")
    quiz = _load(client)
    assert quiz["questions"]
    first = quiz["questions"][0]
    assert "correct_index" in first and "explanation" in first


def test_students_cannot_load_editor_content(client, seeded):
    register_student(client, seeded, "stu_q", "pw-eight-chars")
    assert client.get(f"/api/instructor/quizzes/{QUIZ}/content").status_code == 403


def test_unknown_quiz_is_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert client.get("/api/instructor/quizzes/nope/content").status_code == 404


# --- editing ----------------------------------------------------------------


def test_edit_question_text_and_answer(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    payload["questions"][0]["text"] = "Reworded question?"
    payload["questions"][0]["correct_index"] = 1
    payload["questions"][0]["explanation"] = "Because of the new reason."

    assert _save(client, payload).status_code == 200
    saved = _load(client)["questions"][0]
    assert saved["text"] == "Reworded question?"
    assert saved["correct_index"] == 1
    assert saved["explanation"] == "Because of the new reason."


def test_add_remove_and_reorder_questions(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    original_count = len(payload["questions"])
    payload["questions"] = list(reversed(payload["questions"]))[: original_count - 1]
    payload["questions"].append({
        "text": "A question added in the editor?",
        "options": ["Yes", "No"],
        "correct_index": 0,
        "concept_tag": "editing",
        "explanation": "It was added in the editor.",
    })

    assert _save(client, payload).status_code == 200
    saved = _load(client)["questions"]
    assert len(saved) == original_count
    assert saved[-1]["text"] == "A question added in the editor?"
    assert [q["position"] for q in saved] == list(range(1, len(saved) + 1))


def test_edits_reach_students(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    payload["questions"][0]["text"] = "Visible to students?"
    _save(client, payload)
    client.post("/api/auth/logout", json={})

    register_student(client, seeded, "stu_qsee", "pw-eight-chars")
    quiz = client.get(f"/api/quizzes/{QUIZ}").json()
    assert quiz["questions"][0]["text"] == "Visible to students?"
    # students still never receive the answer key
    assert "correct_index" not in quiz["questions"][0]


def test_grading_follows_the_edited_answer_key(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    for q in payload["questions"]:
        q["correct_index"] = 1
    _save(client, payload)
    client.post("/api/auth/logout", json={})

    register_student(client, seeded, "stu_qgrade", "pw-eight-chars")
    quiz = client.get(f"/api/quizzes/{QUIZ}").json()
    answers = [1] * len(quiz["questions"])
    r = client.post(f"/api/quizzes/{QUIZ}/submissions", json={"answers": answers})
    assert r.status_code == 201 and r.json()["score"] == 1.0


# --- rejections -------------------------------------------------------------


def test_id_mismatch_is_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    payload["quiz_id"] = "other_quiz"
    r = client.post(f"/api/instructor/quizzes/{QUIZ}/content", json=payload)
    assert r.status_code == 400


def test_invalid_quiz_is_rejected_with_findings(client, seeded):
    login(client, "prof", "prof-pass-123")
    before = _load(client)
    payload = _as_payload(before)
    payload["questions"][0]["correct_index"] = 99  # out of range

    r = _save(client, payload)
    assert r.status_code == 422
    assert any(f["severity"] == "error" for f in r.json()["detail"]["findings"])
    assert _load(client)["questions"][0]["text"] == before["questions"][0]["text"]


def test_empty_question_list_is_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    payload["questions"] = []
    assert _save(client, payload).status_code == 422


# --- the restart trap -------------------------------------------------------


def test_edits_survive_a_restart(settings, client, seeded):
    """Boot re-imports the authored JSON files; an edited quiz must be left
    alone or the instructor's work vanishes on the next deploy."""
    login(client, "prof", "prof-pass-123")
    payload = _as_payload(_load(client))
    payload["questions"][0]["text"] = "Survives a restart?"
    _save(client, payload)

    with TestClient(create_app(settings)) as c2:  # fresh boot, same database
        login(c2, "prof", "prof-pass-123")
        assert _load(c2)["questions"][0]["text"] == "Survives a restart?"


def test_unedited_quizzes_still_follow_the_files(settings, app, seeded):
    """The flag is per quiz: one edited in the app is pinned, the rest keep
    picking up changes to the authored JSON on boot."""
    conn = dbmod.connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT edited_in_app FROM quizzes WHERE quiz_id = ?", (QUIZ,)
        ).fetchone()
        assert row is not None and row["edited_in_app"] == 0
        quiz = quiz_store.get_quiz(conn, QUIZ, include_answers=True, include_unpublished=True)
        edited = copy.deepcopy(quiz)
        edited["questions"] = [
            {"text": "Edited", "options": ["a", "b"], "correct_index": 0}
        ]
        quiz_store.import_quiz(conn, edited, edited_in_app=True)
        assert conn.execute(
            "SELECT edited_in_app FROM quizzes WHERE quiz_id = ?", (QUIZ,)
        ).fetchone()["edited_in_app"] == 1
        # seeding runs again and leaves it alone
        quiz_store.seed_quizzes(conn)
        after = quiz_store.get_quiz(conn, QUIZ, include_unpublished=True)
        assert after["questions"][0]["text"] == "Edited"
    finally:
        conn.close()
