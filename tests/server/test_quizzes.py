"""Quiz seeding, answer-stripping, per-question check, graded submissions,
and the quiz milestone's effect on tutorial progress."""

import io

from .conftest import login, register_student

QUIZ_ID = "quiz_tut1_3d_bar"

GOOD_REPORT = """Project
Static Structural
Model
Material: Structural Steel
Solution
Total Deformation
Results
Directional Deformation maximum 0.00382 in
"""


def _correct_answers(client):
    """Instructor view includes correct_index — build a perfect answer sheet."""
    login(client, "prof", "prof-pass-123")
    quiz = client.get(f"/api/quizzes/{QUIZ_ID}").json()
    client.post("/api/auth/logout", json={})
    return [q["correct_index"] for q in quiz["questions"]]


def test_quiz_seeded_and_linked(client, seeded):
    register_student(client, seeded)
    detail = client.get("/api/student/tutorials/tut1_3d_bar").json()
    assert detail["quiz"] is not None
    assert detail["quiz"]["quiz_id"] == QUIZ_ID
    assert detail["quiz"]["attempts"] == 0


def test_student_get_strips_answers(client, seeded):
    register_student(client, seeded)
    quiz = client.get(f"/api/quizzes/{QUIZ_ID}").json()
    assert quiz["tutorial_id"] == "tut1_3d_bar"
    assert len(quiz["questions"]) == 6
    for q in quiz["questions"]:
        assert "correct_index" not in q
        assert "explanation" not in q
        assert len(q["options"]) >= 2


def test_instructor_get_includes_answers(client, seeded):
    login(client, "prof", "prof-pass-123")
    quiz = client.get(f"/api/quizzes/{QUIZ_ID}").json()
    assert all("correct_index" in q and "explanation" in q for q in quiz["questions"])


def test_check_endpoint_feedback(client, seeded):
    register_student(client, seeded)
    quiz = client.get(f"/api/quizzes/{QUIZ_ID}").json()
    q1 = quiz["questions"][0]  # axial-deformation formula, correct_index 0
    right = client.post(
        f"/api/quizzes/{QUIZ_ID}/check",
        json={"question_id": q1["question_id"], "choice_index": 0},
    ).json()
    assert right["correct"] is True and right["correct_index"] == 0
    assert right["explanation"]
    wrong = client.post(
        f"/api/quizzes/{QUIZ_ID}/check",
        json={"question_id": q1["question_id"], "choice_index": 3},
    ).json()
    assert wrong["correct"] is False and wrong["correct_index"] == 0


def test_submission_graded_server_side(client, seeded):
    register_student(client, seeded)
    answers = _correct_answers(client)
    register_student(client, seeded, username="ben", password="bens-password")
    answers[0] = (answers[0] + 1) % 4  # one deliberate mistake
    r = client.post(
        f"/api/quizzes/{QUIZ_ID}/submissions",
        json={"answers": answers, "client_score": 1.0},  # lying client score ignored
    )
    assert r.status_code == 201
    body = r.json()
    assert body["correct_count"] == 5 and body["total"] == 6
    assert abs(body["score"] - 5 / 6) < 1e-9
    assert body["attempt"] == 1
    verdicts = {p["question_id"]: p["correct"] for p in body["per_question"]}
    assert sum(verdicts.values()) == 5
    # by_concept rollup covers every question exactly once
    assert sum(c["total"] for c in body["by_concept"].values()) == 6
    axial = body["by_concept"]["axial-deformation"]
    assert axial["total"] == 2 and axial["correct"] == 1

    hist = client.get(f"/api/quizzes/{QUIZ_ID}/submissions/mine").json()
    assert len(hist) == 1 and abs(hist[0]["score"] - 5 / 6) < 1e-9


def test_answer_count_mismatch_rejected(client, seeded):
    register_student(client, seeded)
    r = client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [0, 1]})
    assert r.status_code == 422


def test_instructor_cannot_submit(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [0] * 6})
    assert r.status_code == 403


def test_quiz_requires_auth(client, seeded):
    assert client.get(f"/api/quizzes/{QUIZ_ID}").status_code == 401


def test_quiz_milestone_gates_completion(client, seeded):
    """tut1 now has BOTH milestones (report + quiz): a passing report alone is
    in_progress; adding a quiz submission completes the tutorial."""
    register_student(client, seeded)
    r = client.post(
        "/api/tutorials/tut1_3d_bar/report",
        files={"file": ("report.txt", io.BytesIO(GOOD_REPORT.encode()), "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.json()["ok"] is True
    card = client.get("/api/student/dashboard").json()["tutorials"][0]
    assert card["status"] == "in_progress"  # quiz milestone still open

    client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [0] * 6})
    card = client.get("/api/student/dashboard").json()["tutorials"][0]
    assert card["status"] == "completed"
    assert card["percent"] == 100
    assert card["quiz"]["attempts"] == 1
