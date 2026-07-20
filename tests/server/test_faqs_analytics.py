"""M6: FAQ mining -> draft -> approve/reject pipeline, quiz analytics,
token-only CSV exports. LLM off -> drafting returns an empty draft."""

import time

from .conftest import login, register_student

QUIZ_ID = "quiz_tut1_3d_bar"


def _fail_step(client, step="wb_03_add_static_structural", check="ocr_text_present"):
    client.post(
        "/api/events/action_events",
        json=[{"tutorial_id": "tut1_3d_bar", "step_id": step,
               "action_type": "verify_failed", "timestamp": time.time(),
               "extra": {"failed_check": check}}],
    )


def _touch_tutorial(client):
    client.post(
        "/api/events/action_events",
        json=[{"tutorial_id": "tut1_3d_bar", "step_id": "wb_01_open",
               "action_type": "step_started", "timestamp": time.time()}],
    )


def _seed_cohort(client, seeded, n=5, failers=2):
    """n students touch the tutorial; the first `failers` also fail wb_03."""
    for i in range(n):
        register_student(client, seeded, username=f"stu{i}", password="pw-eight-chars")
        _touch_tutorial(client)
        if i < failers:
            _fail_step(client)
        client.post("/api/auth/logout", json={})


def test_mining_threshold(client, seeded):
    # 2/5 = 40% >= 30% threshold, cohort 5 >= min 5 -> candidate
    _seed_cohort(client, seeded, n=5, failers=2)
    login(client, "prof", "prof-pass-123")
    r = client.post("/api/instructor/faqs/refresh", json={})
    assert r.status_code == 200
    cands = client.get("/api/instructor/faqs/candidates").json()
    assert len(cands) == 1
    c = cands[0]
    assert c["step_id"] == "wb_03_add_static_structural"
    assert c["distinct_students"] == 2 and c["cohort_size"] == 5
    assert abs(c["failure_rate"] - 0.4) < 1e-6
    assert c["status"] == "candidate"
    assert c["step_title"]  # authored step context resolved


def test_mining_below_threshold_or_small_cohort(client, seeded):
    # 1/5 = 20% < 30% -> nothing
    _seed_cohort(client, seeded, n=5, failers=1)
    login(client, "prof", "prof-pass-123")
    client.post("/api/instructor/faqs/refresh", json={})
    assert client.get("/api/instructor/faqs/candidates").json() == []


def test_small_cohort_never_mines(client, seeded):
    # 3/4 students fail, but cohort < 5 -> nothing
    _seed_cohort(client, seeded, n=4, failers=3)
    login(client, "prof", "prof-pass-123")
    client.post("/api/instructor/faqs/refresh", json={})
    assert client.get("/api/instructor/faqs/candidates").json() == []


def test_draft_approve_publish_flow(client, seeded):
    _seed_cohort(client, seeded, n=5, failers=3)
    login(client, "prof", "prof-pass-123")
    client.post("/api/instructor/faqs/refresh", json={})
    cand = client.get("/api/instructor/faqs/candidates").json()[0]

    # LLM off in tests -> empty draft, but status moves to drafted
    d = client.post(f"/api/instructor/faqs/candidates/{cand['id']}/draft", json={}).json()
    assert d["status"] == "drafted"

    r = client.post(
        f"/api/instructor/faqs/candidates/{cand['id']}/approve",
        json={"question": "Why won't Static Structural drop onto the schematic?",
              "answer": "Drag the SYSTEM from the Toolbox onto the Project Schematic canvas."},
    )
    assert r.status_code == 200
    faq_id = r.json()["faq_id"]

    # re-mining must NOT downgrade the approved row
    client.post("/api/instructor/faqs/refresh", json={})
    cand2 = [c for c in client.get("/api/instructor/faqs/candidates").json()
             if c["id"] == cand["id"]][0]
    assert cand2["status"] == "approved"

    pub = client.get("/api/instructor/faqs").json()
    assert any(f["faq_id"] == faq_id for f in pub)

    # students see it on the step
    client.post("/api/auth/logout", json={})
    login(client, "stu0", "pw-eight-chars")
    faqs = client.get(
        "/api/tutorials/tut1_3d_bar/steps/wb_03_add_static_structural/faqs"
    ).json()
    assert len(faqs) == 1 and "Toolbox" in faqs[0]["answer"]


def test_reject_and_unpublish(client, seeded):
    _seed_cohort(client, seeded, n=5, failers=3)
    login(client, "prof", "prof-pass-123")
    client.post("/api/instructor/faqs/refresh", json={})
    cand = client.get("/api/instructor/faqs/candidates").json()[0]
    client.post(f"/api/instructor/faqs/candidates/{cand['id']}/reject", json={})
    statuses = {c["id"]: c["status"] for c in client.get("/api/instructor/faqs/candidates").json()}
    assert statuses[cand["id"]] == "rejected"


def test_quiz_analytics_first_attempt(client, seeded):
    # stu0 takes the quiz twice (first all-A, then all-B); stu1 once (all-B).
    register_student(client, seeded, username="stu0", password="pw-eight-chars")
    client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [0] * 6})
    client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [1] * 6})
    client.post("/api/auth/logout", json={})
    register_student(client, seeded, username="stu1", password="pw-eight-chars")
    client.post(f"/api/quizzes/{QUIZ_ID}/submissions", json={"answers": [1] * 6})
    client.post("/api/auth/logout", json={})

    login(client, "prof", "prof-pass-123")
    a = client.get(f"/api/instructor/quizzes/{QUIZ_ID}/analytics").json()
    assert a["first_attempt_students"] == 2
    q1 = a["questions"][0]  # correct_index 0: stu0 first attempt right, stu1 wrong
    assert q1["correct_pct"] == 50
    # every concept aggregates 2 attempts per question
    total = sum(c["total"] for c in a["concepts"])
    assert total == 12  # 6 questions x 2 first-attempts
    assert client.get("/api/instructor/quizzes/nope/analytics").status_code == 404


def test_csv_exports_token_only(client, seeded):
    _seed_cohort(client, seeded, n=5, failers=2)
    login(client, "prof", "prof-pass-123")
    r = client.get("/api/instructor/export/action_events.csv")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    text = r.text
    assert text.splitlines()[0].startswith("session_token,")
    assert "student_" in text
    assert "stu0" not in text  # usernames never leave via exports
    assert client.get("/api/instructor/export/users.csv").status_code == 404


def test_students_cannot_reach_m6_endpoints(client, seeded):
    register_student(client, seeded)
    assert client.get("/api/instructor/faqs/candidates").status_code == 403
    assert client.get("/api/instructor/export/action_events.csv").status_code == 403
    assert client.get(f"/api/instructor/quizzes/{QUIZ_ID}/analytics").status_code == 403
