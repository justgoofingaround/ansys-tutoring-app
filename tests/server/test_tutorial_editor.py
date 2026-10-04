"""Instructor tutorial editor: load a version, save edits as a draft, publish.

Editing never mutates a stored version — `tutorial_versions` rows stay immutable,
so a save mints a new version and students keep seeing the published one until
the instructor publishes.
"""

import copy
import json

from .conftest import login, register_student

TUT = "tut1_3d_bar"


def _content(client, tutorial_id, version):
    r = client.get(f"/api/instructor/tutorials/{tutorial_id}/versions/{version}/content")
    assert r.status_code == 200, r.text
    return r.json()["content"]


def _published_version(client, tutorial_id=TUT):
    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    return lib[tutorial_id]["published_version"]


def _save(client, tutorial_id, content):
    return client.post(f"/api/instructor/tutorials/{tutorial_id}/content", json=content)


def _first_step(content):
    return content["sections"][0]["steps"][0]


# --- loading ----------------------------------------------------------------


def test_load_published_version_content(client, seeded):
    login(client, "prof", "prof-pass-123")
    content = _content(client, TUT, _published_version(client))
    assert content["tutorial_id"] == TUT
    assert content["sections"] and _first_step(content)["step_id"]


def test_unknown_version_is_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert client.get(
        f"/api/instructor/tutorials/{TUT}/versions/999/content"
    ).status_code == 404


def test_students_cannot_read_editor_content(client, seeded):
    register_student(client, seeded, "stu_ed", "pw-eight-chars")
    assert client.get(
        f"/api/instructor/tutorials/{TUT}/versions/1/content"
    ).status_code == 403


# --- saving -----------------------------------------------------------------


def test_save_creates_an_unpublished_version(client, seeded):
    login(client, "prof", "prof-pass-123")
    published = _published_version(client)
    content = _content(client, TUT, published)
    content["sections"][0]["steps"][0]["title"] = "Open Workbench (edited)"

    r = _save(client, TUT, content)
    assert r.status_code == 200, r.text
    new_version = r.json()["version"]
    assert new_version > published
    # students still see the old text until it is published
    assert _published_version(client) == published


def test_publishing_the_draft_reaches_students(client, seeded):
    login(client, "prof", "prof-pass-123")
    content = _content(client, TUT, _published_version(client))
    content["sections"][0]["steps"][0]["title"] = "Open Workbench (edited)"
    new_version = _save(client, TUT, content).json()["version"]

    assert client.post(
        f"/api/instructor/tutorials/{TUT}/publish", json={"version": new_version}
    ).status_code == 200
    client.post("/api/auth/logout", json={})

    register_student(client, seeded, "stu_pub", "pw-eight-chars")
    detail = client.get(f"/api/student/tutorials/{TUT}").json()
    titles = [s["title"] for sec in detail["sections"] for s in sec["steps"]]
    assert "Open Workbench (edited)" in titles


def test_round_trip_preserves_keys_the_editor_does_not_model(client, seeded):
    """The editor sends the whole document back; anything it does not understand
    (report_checks, apps, ...) must survive untouched."""
    login(client, "prof", "prof-pass-123")
    original = _content(client, TUT, _published_version(client))
    edited = copy.deepcopy(original)
    edited["sections"][0]["steps"][0]["title"] = "Changed"

    version = _save(client, TUT, edited).json()["version"]
    saved = _content(client, TUT, version)

    for key in ("report_checks", "apps", "problem"):
        if key in original:
            assert saved[key] == original[key], f"{key} was altered"
    assert _first_step(saved)["title"] == "Changed"
    # untouched technical fields on the edited step survive too
    assert _first_step(saved)["verify"] == _first_step(original)["verify"]


def test_reordering_and_adding_steps(client, seeded):
    login(client, "prof", "prof-pass-123")
    content = _content(client, TUT, _published_version(client))
    steps = content["sections"][0]["steps"]
    if len(steps) >= 2:
        steps[0], steps[1] = steps[1], steps[0]
    # Mirrors the template the editor's "add step" button inserts: a valid step
    # needs app, highlight and a conventional step_id, not just title/description.
    new_id = "wb_99_added_in_editor"
    steps.append({
        "step_id": new_id,
        "app": steps[0].get("app", "workbench"),
        "title": "A step added in the editor",
        "description": "Do the new thing.",
        "highlight": "none",
        "verify": {"type": "manual", "prompt": "Did you do the new thing?"},
        "hints": ["Ask a TA if you get stuck."],
    })
    if isinstance(content.get("runtime_steps"), list):
        content["runtime_steps"].append(new_id)

    version = _save(client, TUT, content).json()["version"]
    saved_ids = [s["step_id"] for s in _content(client, TUT, version)["sections"][0]["steps"]]
    assert new_id in saved_ids
    assert saved_ids[:2] == [steps[0]["step_id"], steps[1]["step_id"]]


# --- rejections -------------------------------------------------------------


def test_id_mismatch_is_rejected(client, seeded):
    """Saving under the wrong id would quietly fork a tutorial."""
    login(client, "prof", "prof-pass-123")
    content = _content(client, TUT, _published_version(client))
    content["tutorial_id"] = "some_other_tutorial"
    r = client.post(f"/api/instructor/tutorials/{TUT}/content", json=content)
    assert r.status_code == 400 and r.json()["detail"] == "tutorial_id_mismatch"


def test_invalid_content_is_rejected_with_findings(client, seeded):
    login(client, "prof", "prof-pass-123")
    before = _published_version(client)
    content = _content(client, TUT, before)
    del content["sections"][0]["steps"][0]["step_id"]

    r = _save(client, TUT, content)
    assert r.status_code == 422
    findings = r.json()["detail"]["findings"]
    assert any(f["severity"] == "error" for f in findings)
    # nothing was stored
    versions = [v["version"] for v in
                {t["tutorial_id"]: t for t in
                 client.get("/api/instructor/tutorials").json()}[TUT]["versions"]]
    assert max(versions) == before


def test_saving_unchanged_content_does_not_mint_a_duplicate(client, seeded):
    login(client, "prof", "prof-pass-123")
    published = _published_version(client)
    content = _content(client, TUT, published)
    assert _save(client, TUT, content).json()["version"] == published


def test_unknown_tutorial_is_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    content = _content(client, TUT, _published_version(client))
    content["tutorial_id"] = "nope_not_here"
    r = client.post("/api/instructor/tutorials/nope_not_here/content", json=content)
    assert r.status_code == 404
