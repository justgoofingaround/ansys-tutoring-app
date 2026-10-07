"""Step reference images uploaded through the editor, and blank tutorials.

Uploads land in DATA_DIR rather than the repo: content/data/images is baked
into the Docker image, so anything written there would vanish on redeploy.
"""

import json
import struct
import zlib

from .conftest import login, register_student

TUT = "tut1_3d_bar"


def _png(width=2, height=2) -> bytes:
    """A real 2x2 PNG — the endpoint checks magic bytes, not just the suffix."""
    def chunk(tag, payload):
        return (
            struct.pack(">I", len(payload)) + tag + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _upload(client, tutorial_id, content, filename="shot.png", ctype="image/png"):
    return client.post(
        f"/api/instructor/tutorials/{tutorial_id}/images",
        files={"file": (filename, content, ctype)},
        headers={"X-Requested-With": "fetch"},
    )


# --- uploading --------------------------------------------------------------


def test_upload_stores_the_file_and_returns_a_relative_path(client, seeded, settings):
    login(client, "prof", "prof-pass-123")
    r = _upload(client, TUT, _png())
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["source_image"].startswith(f"uploads/step_images/{TUT}/")
    # stored under DATA_DIR, not the repo — this is what survives a redeploy
    name = body["source_image"].rsplit("/", 1)[-1]
    assert (settings.step_images_dir / TUT / name).is_file()


def test_uploaded_image_is_served(client, seeded):
    login(client, "prof", "prof-pass-123")
    url = _upload(client, TUT, _png()).json()["url"]
    r = client.get(url)
    assert r.status_code == 200
    assert r.content.startswith(b"\x89PNG")


def test_two_uploads_of_the_same_name_do_not_collide(client, seeded):
    """An older published version may still point at the first one."""
    login(client, "prof", "prof-pass-123")
    first = _upload(client, TUT, _png()).json()["source_image"]
    second = _upload(client, TUT, _png(4, 4)).json()["source_image"]
    assert first != second
    assert client.get(f"/step-images/{first.split('/', 2)[2]}").status_code == 200


def test_disguised_executable_is_rejected(client, seeded):
    """Extension alone is not proof: check the magic bytes."""
    login(client, "prof", "prof-pass-123")
    r = _upload(client, TUT, b"MZ\x90\x00 this is a windows executable")
    assert r.status_code == 400 and r.json()["detail"] == "not_an_image"


def test_unsupported_extension_is_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = _upload(client, TUT, _png(), filename="shot.svg", ctype="image/svg+xml")
    assert r.status_code == 400


def test_oversized_image_is_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    big = b"\x89PNG\r\n\x1a\n" + b"0" * (6 * 1024 * 1024)
    assert _upload(client, TUT, big).status_code == 413


def test_unknown_tutorial_is_404(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert _upload(client, "no_such_tutorial", _png()).status_code == 404


def test_students_cannot_upload(client, seeded):
    register_student(client, seeded, "stu_img", "pw-eight-chars")
    assert _upload(client, TUT, _png()).status_code == 403


# --- using the image in a step ----------------------------------------------


def test_uploaded_path_saves_without_new_warnings(client, seeded):
    """The validator checks source_image files exist under the repo root.
    Uploaded ones never will, so the prefix must be exempt or every save would
    carry a spurious warning."""
    login(client, "prof", "prof-pass-123")
    uploaded = _upload(client, TUT, _png()).json()["source_image"]

    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    version = lib[TUT]["published_version"]
    content = client.get(
        f"/api/instructor/tutorials/{TUT}/versions/{version}/content"
    ).json()["content"]
    content["sections"][0]["steps"][0]["source_image"] = uploaded

    r = client.post(f"/api/instructor/tutorials/{TUT}/content", json=content)
    assert r.status_code == 200, r.text
    assert not [
        w for w in r.json()["warnings"]
        if "source_image" in w["message"] and "step_images" in str(w)
    ]


def test_guide_endpoint_exposes_the_uploaded_path(client, seeded):
    """The desktop launcher reads source_image from this endpoint and fetches
    the bytes from /step-images — both must work unauthenticated."""
    login(client, "prof", "prof-pass-123")
    uploaded = _upload(client, TUT, _png()).json()["source_image"]
    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    content = client.get(
        f"/api/instructor/tutorials/{TUT}/versions/{lib[TUT]['published_version']}/content"
    ).json()["content"]
    content["sections"][0]["steps"][0]["source_image"] = uploaded
    version = client.post(f"/api/instructor/tutorials/{TUT}/content", json=content).json()["version"]
    client.post(f"/api/instructor/tutorials/{TUT}/publish", json={"version": version})
    client.post("/api/auth/logout", json={})

    guide = client.get(f"/api/guide/tutorials/{TUT}").json()
    paths = [s.get("source_image") for sec in guide["sections"] for s in sec["steps"]]
    assert uploaded in paths
    assert client.get(f"/step-images/{uploaded.split('/', 2)[2]}").status_code == 200


# --- blank tutorials --------------------------------------------------------


def test_create_blank_tutorial(client, seeded):
    login(client, "prof", "prof-pass-123")
    r = client.post(
        "/api/instructor/tutorials/blank",
        json={"tutorial_id": "m09_new_lab", "title": "Tutorial 9 — New lab"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["version"] == 1

    lib = {t["tutorial_id"]: t for t in client.get("/api/instructor/tutorials").json()}
    assert lib["m09_new_lab"]["published_version"] is None  # draft until published

    content = client.get(
        "/api/instructor/tutorials/m09_new_lab/versions/1/content"
    ).json()["content"]
    assert content["sections"][0]["steps"][0]["step_id"]


def test_blank_tutorial_can_be_edited_and_published(client, seeded):
    login(client, "prof", "prof-pass-123")
    client.post(
        "/api/instructor/tutorials/blank",
        json={"tutorial_id": "m10_new_lab", "title": "Tutorial 10"},
    )
    content = client.get(
        "/api/instructor/tutorials/m10_new_lab/versions/1/content"
    ).json()["content"]
    content["sections"][0]["steps"][0]["title"] = "Open Workbench"
    version = client.post(
        "/api/instructor/tutorials/m10_new_lab/content", json=content
    ).json()["version"]
    assert client.post(
        "/api/instructor/tutorials/m10_new_lab/publish", json={"version": version}
    ).status_code == 200


def test_duplicate_and_bad_ids_are_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    assert client.post(
        "/api/instructor/tutorials/blank", json={"tutorial_id": TUT, "title": "Clash"}
    ).status_code == 409
    assert client.post(
        "/api/instructor/tutorials/blank", json={"tutorial_id": "Bad Id!", "title": "x"}
    ).status_code == 422
    assert client.post(
        "/api/instructor/tutorials/blank", json={"tutorial_id": "ok_id", "title": "  "}
    ).status_code == 422


def test_students_cannot_create_tutorials(client, seeded):
    register_student(client, seeded, "stu_blank", "pw-eight-chars")
    r = client.post(
        "/api/instructor/tutorials/blank", json={"tutorial_id": "sneaky", "title": "x"}
    )
    assert r.status_code == 403
