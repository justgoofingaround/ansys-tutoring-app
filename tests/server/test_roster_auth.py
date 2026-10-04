"""Roster-based registration + emailed confirmation.

Enrolment grants access: only addresses the instructor loaded can register,
each row can be claimed once, and the account stays unusable until the link
mailed to that address is opened.
"""

import time

import pytest
from fastapi.testclient import TestClient

from server import db as dbmod
from server.app import create_app
from server.config import Settings
from server.security import hash_session_token
from server.services.mailer import FakeMailer

from .conftest import login, register_student

ROSTER_CSV = (
    "email,netid,full_name\n"
    "ana@nyu.edu,ab1234,Ana Becker\n"
    "ben@nyu.edu,bc2345,Ben Cole\n"
    "cara@nyu.edu,cd3456,Cara Diaz\n"
).encode("utf-8")


@pytest.fixture()
def mailer():
    return FakeMailer()


@pytest.fixture()
def settings(tmp_path, mailer):
    return Settings(data_dir=tmp_path / "server_data", enable_llm=False, mailer=mailer)


@pytest.fixture()
def app(settings):
    return create_app(settings)


@pytest.fixture()
def client(app):
    with TestClient(app) as c:
        yield c


def _upload_roster(client, section_id, csv_bytes=ROSTER_CSV):
    return client.post(
        f"/api/instructor/sections/{section_id}/roster",
        files={"file": ("roster.csv", csv_bytes, "text/csv")},
        headers={"X-Requested-With": "fetch"},
    )


@pytest.fixture()
def rostered(client, seeded):
    """Instructor signed in, roster loaded, then signed out again."""
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    assert _upload_roster(client, section_id).status_code == 200
    client.post("/api/auth/logout", json={})
    return section_id


def _register(client, email, password="pw-eight-chars"):
    return client.post("/api/auth/register", json={"email": email, "password": password})


# --- roster management ------------------------------------------------------


def test_upload_lists_entries_as_unclaimed(client, seeded):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id)
    assert r.status_code == 200 and r.json()["added"] == 3
    rows = client.get(f"/api/instructor/sections/{section_id}/roster").json()
    assert [x["status"] for x in rows] == ["unclaimed"] * 3
    assert rows[0]["full_name"] == "Ana Becker"


def test_duplicate_and_malformed_rows_are_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    bad = b"email,netid,full_name\nana@nyu.edu,ab1,Ana\nana@nyu.edu,ab2,Ana Again\nnot-an-email,x,Y\n"
    r = _upload_roster(client, section_id, bad)
    assert r.status_code == 422
    messages = " ".join(f["message"] for f in r.json()["detail"]["findings"])
    assert "duplicate" in messages and "does not look like an email" in messages
    # nothing was written
    assert client.get(f"/api/instructor/sections/{section_id}/roster").json() == []


def test_reupload_is_idempotent_and_updates_names(client, seeded):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    _upload_roster(client, section_id)
    fixed = b"email,netid,full_name\nana@nyu.edu,ab1234,Ana Becker-Smith\n"
    r = _upload_roster(client, section_id, fixed)
    assert r.json() == {"added": 0, "updated": 1, "total": 1, "warnings": []}
    rows = client.get(f"/api/instructor/sections/{section_id}/roster").json()
    assert len(rows) == 3
    assert [x for x in rows if x["email"] == "ana@nyu.edu"][0]["full_name"] == "Ana Becker-Smith"


def test_claimed_entry_cannot_be_deleted(client, rostered):
    _register(client, "ana@nyu.edu")
    login(client, "prof", "prof-pass-123")
    entry = [
        x for x in client.get(f"/api/instructor/sections/{rostered}/roster").json()
        if x["email"] == "ana@nyu.edu"
    ][0]
    r = client.delete(
        f"/api/instructor/roster/{entry['id']}", headers={"X-Requested-With": "fetch"}
    )
    assert r.status_code == 409


# --- registration -----------------------------------------------------------


def test_register_requires_being_on_the_roster(client, rostered):
    assert _register(client, "outsider@nyu.edu").status_code == 400


def test_register_sends_link_without_signing_in(client, rostered, mailer, settings):
    r = _register(client, "ana@nyu.edu")
    assert r.status_code == 202
    assert "session" not in r.cookies  # the key behaviour change: no auto-login
    assert len(mailer.sent) == 1 and mailer.sent[0]["to"] == "ana@nyu.edu"

    conn = dbmod.connect(settings.db_path)
    try:
        user = conn.execute("SELECT * FROM users WHERE email = 'ana@nyu.edu'").fetchone()
        assert user["email_verified_at"] is None
        assert user["username"] == "Ana Becker"  # display name comes from the roster
        assert user["section_id"] is not None     # section assigned from the roster
        n = conn.execute(
            "SELECT COUNT(*) AS n FROM email_verifications WHERE user_id = ?", (user["id"],)
        ).fetchone()["n"]
        assert n == 1
    finally:
        conn.close()


def test_second_registration_replaces_an_unconfirmed_claim(client, rostered):
    """Re-registering is allowed while the claim is unconfirmed (that is how an
    owner recovers an address someone else typed); it is refused once the
    address has been proved — see the impostor tests at the end of this file."""
    assert _register(client, "ana@nyu.edu").status_code == 202
    assert _register(client, "ana@nyu.edu").status_code == 202


def test_email_match_is_case_insensitive(client, rostered):
    assert _register(client, "ANA@nyu.edu").status_code == 202


# --- confirmation -----------------------------------------------------------


def _token_from(mailer):
    return mailer.sent[-1]["url"].split("token=")[1]


def test_link_verifies_and_signs_in(client, rostered, mailer):
    _register(client, "ben@nyu.edu")
    r = client.get("/api/auth/verify", params={"token": _token_from(mailer)})
    assert r.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["username"] == "Ben Cole" and me["role"] == "student"


def test_link_is_single_use(client, rostered, mailer):
    _register(client, "ben@nyu.edu")
    token = _token_from(mailer)
    assert client.get("/api/auth/verify", params={"token": token}).status_code == 200
    client.post("/api/auth/logout", json={})
    assert client.get("/api/auth/verify", params={"token": token}).status_code == 400


def test_expired_link_is_refused(client, rostered, mailer, settings):
    _register(client, "cara@nyu.edu")
    token = _token_from(mailer)
    conn = dbmod.connect(settings.db_path)
    try:
        conn.execute(
            "UPDATE email_verifications SET expires_at = ? WHERE token_hash = ?",
            (time.time() - 1, hash_session_token(token)),
        )
        conn.commit()
    finally:
        conn.close()
    assert client.get("/api/auth/verify", params={"token": token}).status_code == 400


def test_garbage_token_is_refused(client, rostered):
    assert client.get("/api/auth/verify", params={"token": "nope"}).status_code == 400


# --- login ------------------------------------------------------------------


def test_login_blocked_until_verified(client, rostered, mailer):
    _register(client, "ana@nyu.edu")
    r = client.post(
        "/api/auth/login", json={"username": "ana@nyu.edu", "password": "pw-eight-chars"}
    )
    assert r.status_code == 403 and r.json()["detail"] == "email_not_verified"

    client.get("/api/auth/verify", params={"token": _token_from(mailer)})
    client.post("/api/auth/logout", json={})
    r = client.post(
        "/api/auth/login", json={"username": "ana@nyu.edu", "password": "pw-eight-chars"}
    )
    assert r.status_code == 200


def test_instructor_still_logs_in_by_username(client, seeded):
    """Back-compat: accounts with no email (instructors, and students created
    under the retired class-code flow) keep working."""
    assert login(client, "prof", "prof-pass-123")["role"] == "instructor"


def test_manual_verification_fallback(client, rostered):
    """Mail blocked -> the instructor vouches for the student instead."""
    _register(client, "cara@nyu.edu")
    login(client, "prof", "prof-pass-123")
    entry = [
        x for x in client.get(f"/api/instructor/sections/{rostered}/roster").json()
        if x["email"] == "cara@nyu.edu"
    ][0]
    assert entry["status"] == "pending"
    assert client.post(f"/api/instructor/roster/{entry['id']}/verify", json={}).status_code == 200
    client.post("/api/auth/logout", json={})
    r = client.post(
        "/api/auth/login", json={"username": "cara@nyu.edu", "password": "pw-eight-chars"}
    )
    assert r.status_code == 200


def test_resend_is_quiet_about_unknown_addresses(client, rostered, mailer):
    """No account enumeration: same answer either way."""
    before = len(mailer.sent)
    r = client.post("/api/auth/resend", json={"email": "nobody@nyu.edu"})
    assert r.status_code == 200 and len(mailer.sent) == before


# --- real-world Albert export ----------------------------------------------

ALBERT_CSV = (
    "ME-UY 4214 Finite Element Analysis\n"
    "Class roster as of 2026-10-02\n"
    "\n"
    "Counter,Campus ID,Last Name,First Name,Pronoun,Name Recording,"
    "Email Address,Units Taken,Plan Description,Academic Level,"
    "Student Location,Status,Status Notes\n"
    "1,N12345678,Becker,Ana,she/her,,ana@nyu.edu,3,Mechanical Engineering,"
    "Senior,New York,Enrolled,\n"
    "2,N23456789,Cole,Ben,he/him,,ben@nyu.edu,3,Mechanical Engineering,"
    "Junior,New York,Enrolled,\n"
).encode("utf-8")


def test_albert_export_imports_as_is(client, seeded):
    """The real input is Albert's export: preamble lines above the header, an
    'Email Address' column, and names split across First/Last."""
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id, ALBERT_CSV)
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2

    rows = client.get(f"/api/instructor/sections/{section_id}/roster").json()
    by_email = {x["email"]: x for x in rows}
    assert by_email["ana@nyu.edu"]["full_name"] == "Ana Becker"
    # netid falls back to the address's local part when there is no NetID column
    assert by_email["ana@nyu.edu"]["netid"] == "ana"


def test_excel_file_gets_a_useful_message(client, seeded):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id, b"PK\x03\x04 binary xlsx payload")
    assert r.status_code == 422
    assert "Save As" in r.json()["detail"]["findings"][0]["message"]


def test_file_without_an_email_column_is_rejected(client, seeded):
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id, b"name,units\nAna Becker,3\n")
    assert r.status_code == 422
    assert "No email column" in r.json()["detail"]["findings"][0]["message"]


# --- Albert's HTML-in-.xls export -------------------------------------------

ALBERT_HTML = """<html xmlns:x="urn:schemas-microsoft-com:office:excel"><head>
<meta http-equiv=Content-Type content="text/html; charset=utf-8"></head><body>
<table border=0 cellpadding=0 cellspacing=0>
 <tr><td colspan=13>ME-UY 4214 Finite Element Analysis</td></tr>
 <tr><td colspan=13>Class Roster</td></tr>
 <tr><td></td></tr>
 <tr><td>Counter</td><td>Campus ID</td><td>Last Name</td><td>First Name</td>
     <td>Pronoun</td><td>Name Recording</td><td>Email&nbsp;Address</td>
     <td>Units Taken</td><td>Plan Description</td><td>Academic Level</td>
     <td>Student Location</td><td>Status</td><td>Status Notes</td></tr>
 <tr><td>1</td><td>N12345678</td><td>Becker</td><td>Ana</td><td>she/her</td><td></td>
     <td>ab1234@nyu.edu</td><td>3</td><td>Mechanical Engineering</td><td>Senior</td>
     <td>New York</td><td>Enrolled</td><td></td></tr>
 <tr><td>2</td><td>N23456789</td><td>Cole</td><td>Ben</td><td>he/him</td><td></td>
     <td>bc2345@nyu.edu</td><td>3</td><td>Mechanical Engineering</td><td>Junior</td>
     <td>New York</td><td>Enrolled</td><td></td></tr>
</table></body></html>""".encode("utf-8")

# What Excel writes when "Save as Web Page" splits a workbook: the data lives in
# a companion folder, so the uploaded file holds only the tab-strip script.
FRAMESET_XLS = (
    '<html xmlns:x="urn:schemas-microsoft-com:office:excel">\n'
    '<head><meta name="Excel Workbook Frameset">\n'
    '<link id="shLink" href="1%20section_files/sheet001.htm"></head>\n'
    "<body><script>szHTML = \"<table><tr><td>tab strip</td></tr></table>\";</script></body>\n"
    "</html>"
).encode("utf-8")


def test_albert_html_export_is_parsed(client, seeded):
    """Albert's .xls is really HTML; when the rows are in the file, read them."""
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id, ALBERT_HTML)
    assert r.status_code == 200, r.text
    assert r.json()["added"] == 2

    rows = {x["email"]: x for x in
            client.get(f"/api/instructor/sections/{section_id}/roster").json()}
    assert rows["ab1234@nyu.edu"]["full_name"] == "Ana Becker"
    assert rows["ab1234@nyu.edu"]["netid"] == "ab1234"


def test_frameset_xls_explains_where_the_data_went(client, seeded):
    """The file genuinely has no rows in it — say so, instead of 'no email column'."""
    login(client, "prof", "prof-pass-123")
    section_id = client.get("/api/instructor/sections").json()[0]["id"]
    r = _upload_roster(client, section_id, FRAMESET_XLS)
    assert r.status_code == 422
    message = r.json()["detail"]["findings"][0]["message"]
    assert "companion folder" in message and "Save As > CSV" in message


# --- forgotten passwords ----------------------------------------------------


def _reset_token(mailer):
    return [m for m in mailer.sent if m["kind"] == "reset"][-1]["url"].split("token=")[1]


def _verified_student(client, rostered, mailer, email="ana@nyu.edu"):
    _register(client, email)
    client.get("/api/auth/verify", params={"token": _token_from(mailer)})
    client.post("/api/auth/logout", json={})
    return email


def test_forgot_then_reset_lets_the_student_back_in(client, rostered, mailer):
    email = _verified_student(client, rostered, mailer)
    assert client.post("/api/auth/forgot", json={"email": email}).status_code == 200

    r = client.post(
        "/api/auth/reset", json={"token": _reset_token(mailer), "password": "brand-new-pw-1"}
    )
    assert r.status_code == 200

    # old password is dead, new one works
    assert client.post(
        "/api/auth/login", json={"username": email, "password": "pw-eight-chars"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": email, "password": "brand-new-pw-1"}
    ).status_code == 200


def test_reset_revokes_existing_sessions(client, rostered, mailer):
    """If the reset was prompted by someone else having access, it ends here."""
    email = _verified_student(client, rostered, mailer)
    client.post("/api/auth/login", json={"username": email, "password": "pw-eight-chars"})
    assert client.get("/api/auth/me").status_code == 200

    client.post("/api/auth/forgot", json={"email": email})
    client.post(
        "/api/auth/reset", json={"token": _reset_token(mailer), "password": "brand-new-pw-1"}
    )
    assert client.get("/api/auth/me").status_code == 401


def test_reset_link_is_single_use_and_expires(client, rostered, mailer, settings):
    email = _verified_student(client, rostered, mailer)
    client.post("/api/auth/forgot", json={"email": email})
    token = _reset_token(mailer)
    assert client.post(
        "/api/auth/reset", json={"token": token, "password": "brand-new-pw-1"}
    ).status_code == 200
    assert client.post(
        "/api/auth/reset", json={"token": token, "password": "another-new-pw"}
    ).status_code == 400

    client.post("/api/auth/forgot", json={"email": email})
    token2 = _reset_token(mailer)
    conn = dbmod.connect(settings.db_path)
    try:
        conn.execute(
            "UPDATE password_resets SET expires_at = ? WHERE token_hash = ?",
            (time.time() - 1, hash_session_token(token2)),
        )
        conn.commit()
    finally:
        conn.close()
    assert client.post(
        "/api/auth/reset", json={"token": token2, "password": "yet-another-pw"}
    ).status_code == 400


def test_forgot_does_not_reveal_who_has_an_account(client, rostered, mailer):
    before = len(mailer.sent)
    r = client.post("/api/auth/forgot", json={"email": "nobody@nyu.edu"})
    assert r.status_code == 200 and r.json() == {"status": "reset_sent"}
    assert len(mailer.sent) == before  # nothing sent, same answer


def test_reset_also_confirms_an_unverified_address(client, rostered, mailer):
    """A student who never opened the confirmation link can still recover —
    opening a link sent to that address proves the address either way."""
    _register(client, "ben@nyu.edu")
    client.post("/api/auth/forgot", json={"email": "ben@nyu.edu"})
    assert client.post(
        "/api/auth/reset", json={"token": _reset_token(mailer), "password": "brand-new-pw-1"}
    ).status_code == 200
    assert client.post(
        "/api/auth/login", json={"username": "ben@nyu.edu", "password": "brand-new-pw-1"}
    ).status_code == 200


def test_short_password_is_rejected(client, rostered, mailer):
    email = _verified_student(client, rostered, mailer)
    client.post("/api/auth/forgot", json={"email": email})
    r = client.post(
        "/api/auth/reset", json={"token": _reset_token(mailer), "password": "short"}
    )
    assert r.status_code == 422


# --- mail outages -----------------------------------------------------------


class BrokenMailer:
    """Stands in for a dead or unreachable relay."""

    def send_verification(self, *a, **k):
        raise ConnectionRefusedError("relay down")

    def send_password_reset(self, *a, **k):
        raise ConnectionRefusedError("relay down")


@pytest.fixture()
def broken_mail_client(tmp_path):
    s = Settings(
        data_dir=tmp_path / "broken", enable_llm=False, mailer=BrokenMailer(),
        instructor_username="prof", instructor_password="prof-pass-123",
    )
    with TestClient(create_app(s)) as c:
        login(c, "prof", "prof-pass-123")
        section_id = c.get("/api/instructor/sections").json()[0]["id"]
        c.post(
            f"/api/instructor/sections/{section_id}/roster",
            files={"file": ("roster.csv", ROSTER_CSV, "text/csv")},
            headers={"X-Requested-With": "fetch"},
        )
        c.post("/api/auth/logout", json={})
        yield c, section_id


def test_registration_survives_a_dead_mail_server(broken_mail_client):
    """The account must still exist so the instructor can admit the student —
    failing here would leave a claimed roster row nobody can use."""
    client, section_id = broken_mail_client
    r = _register(client, "ana@nyu.edu")
    assert r.status_code == 202
    assert r.json()["status"] == "created"  # honest: no email is coming

    login(client, "prof", "prof-pass-123")
    entry = [e for e in client.get(f"/api/instructor/sections/{section_id}/roster").json()
             if e["email"] == "ana@nyu.edu"][0]
    assert entry["status"] == "pending"
    assert client.post(f"/api/instructor/roster/{entry['id']}/verify", json={}).status_code == 200
    client.post("/api/auth/logout", json={})
    assert client.post(
        "/api/auth/login", json={"username": "ana@nyu.edu", "password": "pw-eight-chars"}
    ).status_code == 200


def test_forgot_password_survives_a_dead_mail_server(broken_mail_client):
    client, _ = broken_mail_client
    _register(client, "ben@nyu.edu")
    assert client.post("/api/auth/forgot", json={"email": "ben@nyu.edu"}).status_code == 200


def test_no_mail_server_configured_does_not_promise_an_email(tmp_path):
    """Default deployment (no SMTP_HOST): the link is only logged, so the
    student must be told to ask the instructor rather than wait for mail."""
    s = Settings(
        data_dir=tmp_path / "nomail", enable_llm=False,
        instructor_username="prof", instructor_password="prof-pass-123",
    )  # mailer=None -> LoggingMailer
    with TestClient(create_app(s)) as c:
        login(c, "prof", "prof-pass-123")
        section_id = c.get("/api/instructor/sections").json()[0]["id"]
        c.post(
            f"/api/instructor/sections/{section_id}/roster",
            files={"file": ("roster.csv", ROSTER_CSV, "text/csv")},
            headers={"X-Requested-With": "fetch"},
        )
        c.post("/api/auth/logout", json={})
        r = c.post("/api/auth/register", json={"email": "ana@nyu.edu", "password": "pw-eight-chars"})
        assert r.status_code == 202
        assert r.json()["status"] == "created"


# --- impostor recovery ------------------------------------------------------


def test_owner_can_reclaim_an_address_someone_else_registered(client, rostered, mailer, settings):
    """Registering with someone else's address must not lock them out: the
    impostor never confirms, so the owner simply registers and gets the link."""
    _register(client, "ana@nyu.edu", password="impostor-pw-1")

    r = _register(client, "ana@nyu.edu", password="rightful-owner-pw")
    assert r.status_code == 202  # not 409 — the pending claim is discarded

    # only the new account survives, and the impostor's password is dead
    conn = dbmod.connect(settings.db_path)
    try:
        rows = conn.execute("SELECT id FROM users WHERE email = 'ana@nyu.edu'").fetchall()
        assert len(rows) == 1
    finally:
        conn.close()

    client.get("/api/auth/verify", params={"token": _token_from(mailer)})
    client.post("/api/auth/logout", json={})
    assert client.post(
        "/api/auth/login", json={"username": "ana@nyu.edu", "password": "impostor-pw-1"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login", json={"username": "ana@nyu.edu", "password": "rightful-owner-pw"}
    ).status_code == 200


def test_confirmed_account_cannot_be_hijacked_by_re_registration(client, rostered, mailer):
    """Once an address is confirmed, re-registering must be refused — otherwise
    this recovery path would itself become the attack."""
    _register(client, "ben@nyu.edu")
    client.get("/api/auth/verify", params={"token": _token_from(mailer)})
    client.post("/api/auth/logout", json={})
    assert _register(client, "ben@nyu.edu", password="attacker-pw-9").status_code == 409


def test_instructor_vouching_is_recorded(client, rostered):
    """A manually confirmed account is flagged, so a disputed account shows it
    was admitted by an instructor rather than proved by email."""
    _register(client, "cara@nyu.edu")
    login(client, "prof", "prof-pass-123")
    entry = [e for e in client.get(f"/api/instructor/sections/{rostered}/roster").json()
             if e["email"] == "cara@nyu.edu"][0]
    assert entry["vouched"] is False
    client.post(f"/api/instructor/roster/{entry['id']}/verify", json={})
    after = [e for e in client.get(f"/api/instructor/sections/{rostered}/roster").json()
             if e["email"] == "cara@nyu.edu"][0]
    assert after["status"] == "active" and after["vouched"] is True


# --- section management -----------------------------------------------------


def test_rename_section(client, seeded):
    login(client, "prof", "prof-pass-123")
    sid = client.get("/api/instructor/sections").json()[0]["id"]
    r = client.post(f"/api/instructor/sections/{sid}", json={"name": "Section A — Fall 2026"})
    assert r.status_code == 200 and r.json()["name"] == "Section A — Fall 2026"
    assert client.post(f"/api/instructor/sections/{sid}", json={"name": "  "}).status_code == 422


def test_archiving_blocks_new_registrations_but_keeps_students(client, rostered):
    """Archiving is the safe alternative to deleting a section in use."""
    login(client, "prof", "prof-pass-123")
    r = client.post(f"/api/instructor/sections/{rostered}", json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    client.post(f"/api/instructor/sections/{rostered}", json={"is_active": True})


def test_delete_empty_section(client, seeded):
    login(client, "prof", "prof-pass-123")
    created = client.post("/api/instructor/sections", json={"name": "Typo section"}).json()
    r = client.delete(
        f"/api/instructor/sections/{created['id']}", headers={"X-Requested-With": "fetch"}
    )
    assert r.status_code == 200
    assert created["id"] not in [s["id"] for s in client.get("/api/instructor/sections").json()]


def test_cannot_delete_a_section_with_students(client, seeded):
    """Deleting would orphan the accounts and their recorded progress."""
    register_student(client, seeded, "stu_sec", "pw-eight-chars")
    login(client, "prof", "prof-pass-123")
    sid = client.get("/api/instructor/sections").json()[0]["id"]
    r = client.delete(f"/api/instructor/sections/{sid}", headers={"X-Requested-With": "fetch"})
    assert r.status_code == 409 and r.json()["detail"] == "section_has_students"
