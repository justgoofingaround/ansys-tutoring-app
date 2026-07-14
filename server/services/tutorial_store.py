"""Versioned tutorial storage.

Tutorials are authored in mock_server/data/ (the cross-module contract dir);
the server IMPORTS them here into immutable versioned copies under
server_data/tutorials/{id}/v{n}.json. New versions never overwrite old ones,
so students mid-session keep the version they started with.

Upload/import runs tools/validate_tutorial.validate(); validator ERRORS
reject the import, WARNINGS are stored alongside the version.
"""

import json
import sqlite3
import time
import uuid
from pathlib import Path

from tools.validate_tutorial import validate  # repo root is on sys.path (config.py)

from ..config import REPO_ROOT, Settings

DEFAULT_SEED = REPO_ROOT / "mock_server" / "data" / "tut1.json"


class TutorialValidationError(Exception):
    def __init__(self, findings: list[dict]):
        super().__init__("tutorial failed validation")
        self.findings = findings


def _findings_as_dicts(findings) -> list[dict]:
    return [
        {"severity": sev, "where": where, "message": msg}
        for sev, where, msg in findings.items
    ]


def import_tutorial(
    conn: sqlite3.Connection,
    settings: Settings,
    source: Path | bytes,
    *,
    product: str = "mechanical",
    is_mandatory: bool = False,
    uploaded_by: int | None = None,
    publish: bool = True,
) -> dict:
    """Validate + store a tutorial JSON as a new immutable version.

    Raises TutorialValidationError (with findings) on validator errors or
    unparseable JSON. Returns {tutorial_id, version, warnings}.
    """
    incoming = settings.tutorials_dir / "_incoming"
    incoming.mkdir(parents=True, exist_ok=True)
    if isinstance(source, bytes):
        tmp_path = incoming / f"{uuid.uuid4().hex}.json"
        tmp_path.write_bytes(source)
    else:
        tmp_path = Path(source)

    findings = validate(tmp_path)
    if findings.errors:
        raise TutorialValidationError(_findings_as_dicts(findings))

    data = json.loads(tmp_path.read_text(encoding="utf-8"))
    tutorial_id = data["tutorial_id"]
    title = data.get("title", tutorial_id)

    row = conn.execute(
        "SELECT COALESCE(MAX(version), 0) AS v FROM tutorial_versions WHERE tutorial_id = ?",
        (tutorial_id,),
    ).fetchone()
    version = max(row["v"] + 1, int(data.get("version", 1)))
    dest_dir = settings.tutorials_dir / tutorial_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"v{version}.json"
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=True), encoding="utf-8")

    now = time.time()
    conn.execute(
        """INSERT INTO tutorials (tutorial_id, title, product, is_mandatory, created_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(tutorial_id) DO UPDATE SET title = excluded.title""",
        (tutorial_id, title, product, int(is_mandatory), now),
    )
    warnings = _findings_as_dicts(findings)
    conn.execute(
        """INSERT INTO tutorial_versions
           (tutorial_id, version, content, file_path, validation_findings, uploaded_by, uploaded_at)
           VALUES (?,?,?,?,?,?,?)""",
        (
            tutorial_id, version, json.dumps(data, ensure_ascii=True),
            str(dest), json.dumps(warnings), uploaded_by, now,
        ),
    )
    if publish:
        conn.execute(
            "UPDATE tutorials SET latest_published_version = ? WHERE tutorial_id = ?",
            (version, tutorial_id),
        )
    conn.commit()
    if isinstance(source, bytes):
        tmp_path.unlink(missing_ok=True)
    return {"tutorial_id": tutorial_id, "version": version, "warnings": warnings}


def get_published(
    conn: sqlite3.Connection, tutorial_id: str, version: int | None = None
) -> tuple[dict, sqlite3.Row] | None:
    """Return (content, meta_row) for the published (or pinned) version."""
    meta = conn.execute(
        "SELECT * FROM tutorials WHERE tutorial_id = ? AND is_archived = 0", (tutorial_id,)
    ).fetchone()
    if meta is None:
        return None
    v = version or meta["latest_published_version"]
    if v is None:
        return None
    row = conn.execute(
        "SELECT content FROM tutorial_versions WHERE tutorial_id = ? AND version = ?",
        (tutorial_id, v),
    ).fetchone()
    if row is None:
        return None
    return json.loads(row["content"]), meta


def list_published(
    conn: sqlite3.Connection,
    product: str | None = None,
    is_mandatory: bool | None = None,
) -> list[dict]:
    sql = """SELECT * FROM tutorials
             WHERE latest_published_version IS NOT NULL AND is_archived = 0"""
    args: list = []
    if product is not None:
        sql += " AND product = ?"
        args.append(product)
    if is_mandatory is not None:
        sql += " AND is_mandatory = ?"
        args.append(int(is_mandatory))
    sql += " ORDER BY created_at"
    out = []
    for meta in conn.execute(sql, args).fetchall():
        content, _ = get_published(conn, meta["tutorial_id"]) or ({}, None)
        out.append(
            {
                "tutorial_id": meta["tutorial_id"],
                "title": meta["title"],
                "product": meta["product"],
                "is_mandatory": bool(meta["is_mandatory"]),
                "version": meta["latest_published_version"],
                "quiz_id": meta["quiz_id"],
                "has_report_checks": bool(content.get("report_checks")),
            }
        )
    return out


def runtime_step_ids(content: dict) -> list[str]:
    """The step universe the guide actually runs: runtime_steps if present,
    else all authored steps in document order (mirrors guide_tut1.load_steps)."""
    explicit = content.get("runtime_steps")
    if explicit:
        return list(explicit)
    return [
        st["step_id"]
        for sec in content.get("sections", [])
        for st in sec.get("steps", [])
    ]


def seed_if_empty(conn: sqlite3.Connection, settings: Settings) -> None:
    """First boot: import tut1 from the authoring dir so the server is
    demoable with real content immediately."""
    row = conn.execute("SELECT COUNT(*) AS n FROM tutorials").fetchone()
    if row["n"] == 0 and DEFAULT_SEED.is_file():
        import_tutorial(
            conn, settings, DEFAULT_SEED, product="mechanical", is_mandatory=True
        )
