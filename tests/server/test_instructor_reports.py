"""The instructor's view of what students submitted.

The rubric answers "did it pass"; this is where the instructor reads the work
itself, which is why the name is joined here rather than kept pseudonymous.
"""

from .conftest import login, register_student

TUT = "tut1_3d_bar"
REPORT = b"""Static Structural
Solution
Results
Total Deformation
Structural Steel
Directional Deformation: 0.00382 in
"""


def _submit(client, seeded, name="stu_rep"):
    register_student(client, seeded, name, "pw-eight-chars")
    r = client.post(
        f"/api/tutorials/{TUT}/report",
        files={"file": ("my_report.txt", REPORT, "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )
    assert r.status_code == 200, r.text
    client.post("/api/auth/logout", json={})
    return r.json()


def test_list_shows_the_students_name_and_score(client, seeded):
    _submit(client, seeded, "Dana Reyes")
    login(client, "prof", "prof-pass-123")

    rows = client.get("/api/instructor/reports").json()
    assert len(rows) == 1
    row = rows[0]
    assert row["student"] == "Dana Reyes"
    assert row["tutorial_id"] == TUT
    assert row["status"] == "checked" and row["total"] > 0
    assert row["checks"], "the rubric breakdown travels with the row"
    # the filesystem path is never handed to the browser
    assert "stored_path" not in row


def test_the_file_itself_can_be_opened(client, seeded):
    sub = _submit(client, seeded)
    login(client, "prof", "prof-pass-123")

    r = client.get(f"/api/instructor/reports/{sub['submission_id']}/file")
    assert r.status_code == 200
    assert b"Structural Steel" in r.content


def test_filtering_by_state(client, seeded):
    _submit(client, seeded)
    login(client, "prof", "prof-pass-123")
    assert len(client.get("/api/instructor/reports?status=checked").json()) == 1
    assert client.get("/api/instructor/reports?status=pending").json() == []


def test_recheck_puts_it_back_in_the_queue(client, seeded):
    """For when the checker was down, or the rubric has since been fixed."""
    sub = _submit(client, seeded)
    login(client, "prof", "prof-pass-123")

    r = client.post(f"/api/instructor/reports/{sub['submission_id']}/recheck", json={})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert client.get("/api/instructor/reports?status=pending").json()[0][
        "submission_id"
    ] == sub["submission_id"]


def test_unknown_submission_is_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert client.get("/api/instructor/reports/999/file").status_code == 404
    assert client.post("/api/instructor/reports/999/recheck", json={}).status_code == 404


def test_students_cannot_read_anyone_elses_reports(client, seeded):
    _submit(client, seeded, "Dana Reyes")
    register_student(client, seeded, "nosy", "pw-eight-chars")
    assert client.get("/api/instructor/reports").status_code == 403
    assert client.get("/api/instructor/reports/1/file").status_code == 403


def test_a_removed_account_leaves_the_work_anonymous(client, seeded, settings):
    """Deleting a student must not break the page, and must not resurrect a
    name against work that no longer belongs to anyone."""
    import sqlite3

    _submit(client, seeded, "Gone Student")
    conn = sqlite3.connect(settings.db_path)
    conn.execute("DELETE FROM users WHERE username = 'Gone Student'")
    conn.commit()
    conn.close()

    login(client, "prof", "prof-pass-123")
    rows = client.get("/api/instructor/reports").json()
    assert rows[0]["student"] == "(removed account)"


# --- the human half: what the instructor writes back ------------------------


def test_feedback_reaches_the_student(client, seeded):
    sub = _submit(client, seeded, "Dana Reyes")
    login(client, "prof", "prof-pass-123")
    r = client.post(
        f"/api/instructor/reports/{sub['submission_id']}/feedback",
        json={"feedback": "Mesh is too coarse at the fillet. Refine and resubmit."},
    )
    assert r.status_code == 200
    client.post("/api/auth/logout", json={})

    login(client, "dana.reyes@nyu.edu", "pw-eight-chars")
    detail = client.get(f"/api/student/tutorials/{TUT}").json()
    row = detail["report_submissions"][0]
    assert row["instructor_feedback"] == "Mesh is too coarse at the fillet. Refine and resubmit."
    assert row["instructor_feedback_at"]
    # and the dashboard card flags that something is waiting to be read
    card = {t["tutorial_id"]: t for t in client.get("/api/student/dashboard").json()["tutorials"]}
    assert card[TUT]["report"]["has_feedback"] is True


def test_feedback_can_be_updated_and_cleared(client, seeded):
    sub = _submit(client, seeded)
    login(client, "prof", "prof-pass-123")
    sid = sub["submission_id"]

    client.post(f"/api/instructor/reports/{sid}/feedback", json={"feedback": "First note."})
    client.post(f"/api/instructor/reports/{sid}/feedback", json={"feedback": "Second note."})
    assert client.get("/api/instructor/reports").json()[0]["instructor_feedback"] == "Second note."

    client.post(f"/api/instructor/reports/{sid}/feedback", json={"feedback": "   "})
    row = client.get("/api/instructor/reports").json()[0]
    assert row["instructor_feedback"] is None and row["instructor_feedback_at"] is None


def test_students_cannot_write_feedback(client, seeded):
    sub = _submit(client, seeded)
    register_student(client, seeded, "nosy2", "pw-eight-chars")
    r = client.post(
        f"/api/instructor/reports/{sub['submission_id']}/feedback",
        json={"feedback": "A+ for me"},
    )
    assert r.status_code == 403


def test_absurdly_long_feedback_is_refused(client, seeded):
    sub = _submit(client, seeded)
    login(client, "prof", "prof-pass-123")
    r = client.post(
        f"/api/instructor/reports/{sub['submission_id']}/feedback",
        json={"feedback": "x" * 4001},
    )
    assert r.status_code == 422


def test_waiting_filter_covers_reports_being_checked_right_now(client, seeded, settings):
    """A report a checker has claimed is still something the instructor is
    waiting for; filtering on 'pending' alone made it vanish from every tab."""
    import sqlite3

    sub = _submit(client, seeded)
    conn = sqlite3.connect(settings.db_path)
    conn.execute("UPDATE report_submissions SET status = 'claimed' WHERE id = ?",
                 (sub["submission_id"],))
    conn.commit()
    conn.close()

    login(client, "prof", "prof-pass-123")
    assert client.get("/api/instructor/reports?status=pending").json() == []
    waiting = client.get("/api/instructor/reports?status=queued").json()
    assert [r["submission_id"] for r in waiting] == [sub["submission_id"]]


def test_download_is_named_after_the_student(client, seeded):
    """A folder of files called report.pdf cannot be graded."""
    sub = _submit(client, seeded, "Dana Reyes")
    login(client, "prof", "prof-pass-123")

    r = client.get(f"/api/instructor/reports/{sub['submission_id']}/file")
    assert r.status_code == 200
    disposition = r.headers["content-disposition"]
    assert "Dana_Reyes_tut1_3d_bar_my_report.txt" in disposition


def test_download_name_survives_an_awkward_filename(client, seeded, settings):
    """Students upload things like 'final report (2).pdf'; the name has to stay
    a legal filename on the instructor's machine."""
    import sqlite3

    sub = _submit(client, seeded, "Dana Reyes")
    conn = sqlite3.connect(settings.db_path)
    conn.execute("UPDATE report_submissions SET filename = ? WHERE id = ?",
                 ('final report: v2 <draft>.pdf', sub["submission_id"]))
    conn.commit()
    conn.close()

    login(client, "prof", "prof-pass-123")
    r = client.get(f"/api/instructor/reports/{sub['submission_id']}/file")
    name = r.headers["content-disposition"]
    for bad in ('<', '>', ':'):
        assert bad not in name.split("filename=")[-1]
    assert "Dana_Reyes" in name and name.strip().endswith('.pdf"')
