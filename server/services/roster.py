"""Section rosters: the list of students allowed to register.

Validate-then-import, same shape as services/quiz_store.py's
validate_quiz/import_quiz, so the instructor UI can show findings before
anything is written.

Addresses are matched case-insensitively everywhere (the column is COLLATE
NOCASE): a student who types Student@nyu.edu matches a roster row stored as
student@nyu.edu.
"""

import csv
import io
import re
import sqlite3
import time
from html.parser import HTMLParser

# Deliberately permissive — this guards against paste errors, it is not an
# attempt to validate deliverability. Confirmation mail does that.
_EMAIL_RE = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")

# Header aliases. The real input is the Albert class-list export, whose columns
# are "Email Address", "First Name"/"Last Name", "Campus ID" — not the tidy
# email/netid/full_name a hand-written file would use. Anything unrecognised is
# ignored, so the extra Albert columns (Pronoun, Units Taken, Status, ...) are
# harmless.
_EMAIL_KEYS = ("email", "email address", "e-mail", "e-mail address", "emailaddress")
# NOT "campus id": in Albert that column is the N-number (N12345678), which is a
# different identifier. The NetID is the local part of the NYU address, so it is
# derived from the email instead.
_NETID_KEYS = ("netid", "net id", "username")
_NAME_KEYS = ("full_name", "full name", "name", "student name", "student")
_FIRST_KEYS = ("first name", "first", "firstname", "given name")
_LAST_KEYS = ("last name", "last", "lastname", "surname", "family name")


class _TableExtractor(HTMLParser):
    """Rows out of the first usable HTML table.

    Albert's "Excel" export is really HTML with an .xls extension, so this is
    the normal input, not an edge case. Cells carrying only markup/whitespace
    become empty strings; nested tables are flattened into the current row,
    which is fine here because the roster table has no nested tables.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._rows: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None and self._row is not None:
            text = " ".join("".join(self._cell).split())
            self._row.append(text.replace("\xa0", " ").strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._rows is not None:
                self._rows.append(self._row)
            self._row = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _tables_from_html(text: str) -> list[list[list[str]]]:
    parser = _TableExtractor()
    try:
        parser.feed(text)
    except Exception:
        pass  # keep whatever parsed cleanly; _find_header decides if it is usable
    return parser.tables


def _norm(cell: str) -> str:
    return (cell or "").strip().strip('"').lower()


def _find_header(rows: list[list[str]]) -> int:
    """Index of the header row. Albert exports carry title/filter lines above
    it, so the first line is not necessarily the header — find the first row
    that names an email column instead of assuming."""
    for i, row in enumerate(rows):
        if any(_norm(c) in _EMAIL_KEYS for c in row):
            return i
    return -1


def _table_from_bytes(raw: bytes) -> list[list[str]]:
    """Rows from either a real CSV or Albert's HTML-in-.xls export."""
    if raw[:2] == b"PK":
        # .xlsx is a zip; nothing here can read it.
        raise ValueError(
            "This looks like a modern Excel file (.xlsx). In Excel choose "
            "File > Save As > CSV, then upload that."
        )
    text = raw.decode("utf-8-sig", errors="replace")
    stripped = text.lstrip()

    if stripped[:1] == "<" or "<table" in text[:4000].lower():
        for rows in _tables_from_html(text):
            if _find_header(rows) >= 0:
                return rows
        if "workbook frameset" in text.lower() or "_files/sheet001.htm" in text.lower():
            # Excel "web page" workbooks keep the data in a companion folder, so
            # the uploaded file holds only the tab-strip script.
            raise ValueError(
                "This .xls file contains no data — Excel saved the rows in a "
                "companion folder next to it (…_files/sheet001.htm). Open the "
                "file in Excel and choose File > Save As > CSV, then upload that."
            )
        raise ValueError(
            "No class list found in this file. Open it in Excel and choose "
            "File > Save As > CSV, then upload that."
        )

    return list(csv.reader(io.StringIO(text)))


def parse_csv(raw: bytes) -> list[dict]:
    """Roster file -> row dicts ({line, email, netid, full_name}).

    Handles the Albert export as-is, in CSV or its HTML-in-.xls form: preamble
    rows above the header, an "Email Address" column, and names split across
    First/Last. `line` is the row number in the file so findings point at
    something the instructor can actually look at.
    """
    table = _table_from_bytes(raw)
    header_idx = _find_header(table)
    if header_idx < 0:
        raise ValueError(
            "No email column found. The file needs a header row with an "
            "'Email Address' (or 'email') column."
        )

    header = [_norm(c) for c in table[header_idx]]

    def col(keys) -> int | None:
        for i, name in enumerate(header):
            if name in keys:
                return i
        return None

    i_email, i_netid = col(_EMAIL_KEYS), col(_NETID_KEYS)
    i_name, i_first, i_last = col(_NAME_KEYS), col(_FIRST_KEYS), col(_LAST_KEYS)

    def cell(row, idx):
        return (row[idx].strip() if idx is not None and idx < len(row) else "")

    rows = []
    for offset, raw_row in enumerate(table[header_idx + 1:], start=header_idx + 2):
        if not any((c or "").strip() for c in raw_row):
            continue  # blank separator line
        email = cell(raw_row, i_email)
        if i_name is not None:
            full_name = cell(raw_row, i_name)
        else:
            full_name = " ".join(
                x for x in (cell(raw_row, i_first), cell(raw_row, i_last)) if x
            )
        netid = cell(raw_row, i_netid)
        if not netid and "@" in email:
            netid = email.split("@")[0]
        rows.append({
            "line": offset,
            "email": email,
            "netid": netid,
            "full_name": full_name,
        })
    return rows


def validate(conn: sqlite3.Connection, section_id: int, rows: list[dict]) -> list[dict]:
    """Findings list ({severity, where, message}); any 'error' blocks import."""
    findings = []

    def err(where, msg):
        findings.append({"severity": "error", "where": where, "message": msg})

    def warn(where, msg):
        findings.append({"severity": "warning", "where": where, "message": msg})

    if not rows:
        err("file", "No rows found — expected a header line with at least an 'email' column")
        return findings

    seen: dict[str, int] = {}
    for row in rows:
        where = f"line {row['line']}"
        email = row["email"]
        if not email:
            err(where, "missing email")
            continue
        if not _EMAIL_RE.match(email):
            err(where, f"'{email}' does not look like an email address")
            continue
        key = email.lower()
        if key in seen:
            err(where, f"duplicate email '{email}' (already on line {seen[key]})")
            continue
        seen[key] = row["line"]
        if not row["full_name"]:
            warn(where, f"no name for '{email}' — the address will be shown instead")
        other = conn.execute(
            "SELECT s.name AS section FROM roster_entries r"
            " JOIN sections s ON s.id = r.section_id"
            " WHERE r.email = ? AND r.section_id != ?",
            (email, section_id),
        ).fetchone()
        if other is not None:
            err(where, f"'{email}' is already on the roster for {other['section']}")
    return findings


def import_rows(
    conn: sqlite3.Connection, section_id: int, rows: list[dict], added_by: int | None
) -> dict:
    """Upsert by email. Claimed rows keep their claim; only the descriptive
    fields are refreshed, so re-uploading a corrected roster is safe."""
    added = updated = 0
    now = time.time()
    for row in rows:
        if not row["email"]:
            continue
        existing = conn.execute(
            "SELECT id FROM roster_entries WHERE email = ?", (row["email"],)
        ).fetchone()
        if existing is None:
            conn.execute(
                """INSERT INTO roster_entries
                   (section_id, email, netid, full_name, added_by, added_at)
                   VALUES (?,?,?,?,?,?)""",
                (section_id, row["email"], row["netid"], row["full_name"], added_by, now),
            )
            added += 1
        else:
            conn.execute(
                """UPDATE roster_entries
                   SET section_id = ?, netid = ?, full_name = ?
                   WHERE id = ?""",
                (section_id, row["netid"], row["full_name"], existing["id"]),
            )
            updated += 1
    conn.commit()
    return {"added": added, "updated": updated, "total": added + updated}


def entry_for_email(conn: sqlite3.Connection, email: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM roster_entries WHERE email = ?", (email.strip(),)
    ).fetchone()


def list_entries(conn: sqlite3.Connection, section_id: int) -> list[dict]:
    """Roster rows with their claim status, for the instructor's Class page."""
    rows = conn.execute(
        """SELECT r.*, u.username, u.email_verified_at, u.email_verified_by, u.is_active
           FROM roster_entries r
           LEFT JOIN users u ON u.id = r.claimed_by_user_id
           WHERE r.section_id = ?
           ORDER BY r.full_name COLLATE NOCASE, r.email COLLATE NOCASE""",
        (section_id,),
    ).fetchall()
    out = []
    for r in rows:
        if r["claimed_by_user_id"] is None:
            status = "unclaimed"
        elif r["email_verified_at"] is None:
            status = "pending"  # registered, confirmation link not opened yet
        else:
            status = "active"
        out.append({
            "id": r["id"],
            "email": r["email"],
            "netid": r["netid"],
            "full_name": r["full_name"],
            "status": status,
            # True when an instructor vouched instead of the student opening the
            # emailed link — weaker proof, so the UI flags it.
            "vouched": r["email_verified_by"] is not None,
            "user_id": r["claimed_by_user_id"],
            "added_at": r["added_at"],
        })
    return out
