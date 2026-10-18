"""Submitting a report to a tutorial that has no rubric yet.

Refusing these uploads hid the whole feature from every tutorial whose rubric
had not been written, which was most of them. The file is now always accepted;
with no rubric there is nothing to check automatically, so the submission waits
for the instructor instead of being scored.
"""

from .conftest import login, register_student

WITH_RUBRIC = "tut1_3d_bar"
REPORT = b"Mesh\nStatistics\nElement size 3 mm\n"


def _blank_tutorial(client, tutorial_id="m20_no_rubric"):
    """A published tutorial with no report_checks — the common case."""
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/instructor/tutorials/blank",
        json={"tutorial_id": tutorial_id, "title": "Tutorial 20 — Meshing practice"},
    )
    assert r.status_code == 201, r.text
    client.post(
        f"/api/instructor/tutorials/{tutorial_id}/publish", json={"version": r.json()["version"]}
    )
    client.post("/api/auth/logout", json={})
    return tutorial_id


def _submit(client, seeded, tutorial_id, name="stu_norub"):
    register_student(client, seeded, name, "pw-eight-chars")
    return client.post(
        f"/api/tutorials/{tutorial_id}/report",
        files={"file": ("mesh_report.txt", REPORT, "text/plain")},
        headers={"X-Requested-With": "fetch"},
    )


def test_upload_is_accepted_and_waits_for_the_instructor(client, seeded):
    tid = _blank_tutorial(client)
    r = _submit(client, seeded, tid)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "unchecked"
    assert body["checks"] == [] and body["total"] == 0

    detail = client.get(f"/api/student/tutorials/{tid}").json()
    assert detail["has_rubric"] is False
    assert detail["report_submissions"][0]["status"] == "unchecked"


def test_a_tutorial_with_a_rubric_still_gets_checked(client, seeded):
    r = _submit(client, seeded, WITH_RUBRIC, "stu_rub")
    assert r.json()["status"] == "checked"
    assert r.json()["total"] > 0
    assert client.get(f"/api/student/tutorials/{WITH_RUBRIC}").json()["has_rubric"] is True


def test_the_instructor_sees_it_and_can_write_back(client, seeded):
    tid = _blank_tutorial(client, "m21_no_rubric")
    sub = _submit(client, seeded, tid, "stu_norub2").json()
    client.post("/api/auth/logout", json={})

    login(client, "prof", "prof-pass-123")
    rows = client.get("/api/instructor/reports").json()
    assert rows[0]["submission_id"] == sub["submission_id"]
    assert rows[0]["status"] == "unchecked"
    assert client.post(
        f"/api/instructor/reports/{sub['submission_id']}/feedback",
        json={"feedback": "Mesh looks right. Add the statistics table next time."},
    ).status_code == 200


def test_a_rubric_written_later_applies_to_the_next_submission(client, seeded):
    """What the editor's rubric panel does: edit, save a draft, publish."""
    tid = _blank_tutorial(client, "m22_rubric_later")
    login(client, "prof", "prof-pass-123")
    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    version = lib[tid]["versions"][-1]["version"]
    content = client.get(
        f"/api/instructor/tutorials/{tid}/versions/{version}/content"
    ).json()["content"]
    content["report_checks"] = {"required_sections": ["Mesh", "Statistics"]}

    saved = client.post(f"/api/instructor/tutorials/{tid}/content", json=content)
    assert saved.status_code == 200, saved.text
    client.post(f"/api/instructor/tutorials/{tid}/publish", json={"version": saved.json()["version"]})
    client.post("/api/auth/logout", json={})

    r = _submit(client, seeded, tid, "stu_after")
    assert r.json()["status"] == "checked"
    assert r.json()["total"] > 0
