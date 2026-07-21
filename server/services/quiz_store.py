"""Quiz storage + grading.

Quizzes are authored as JSON in mock_server/data/quizzes/<tutorial_id>.json
(same authoring-dir convention as tutorials) and imported at boot. Unlike
tutorials they are NOT versioned for the pilot: re-importing replaces the
question set in place (a quiz is a handful of rows, and submissions store the
answers they were graded against, so history stays interpretable).

question_id in the API is the quiz_questions row id — stable between imports
of the same content only within one import, so clients always GET the quiz
before checking/submitting answers.
"""

import json
import sqlite3
import time
from pathlib import Path

from ..config import REPO_ROOT

QUIZZES_DIR = REPO_ROOT / "mock_server" / "data" / "quizzes"


def validate_quiz(conn: sqlite3.Connection, data: dict) -> list[dict]:
    """Findings for an authored quiz dict — same {severity, where, message}
    shape as tutorial validation. Errors block import; warnings don't.
    Keys starting with '_' are authoring comments and ignored."""
    f: list[dict] = []

    def err(where, msg):
        f.append({"severity": "error", "where": where, "message": msg})

    def warn(where, msg):
        f.append({"severity": "warning", "where": where, "message": msg})

    if not isinstance(data, dict):
        err("$", "quiz file must be a JSON object")
        return f
    for key in ("quiz_id", "tutorial_id", "title"):
        if not isinstance(data.get(key), str) or not data.get(key, "").strip():
            err("$", f"'{key}' is required and must be a non-empty string")
    tutorial_id = data.get("tutorial_id")
    if isinstance(tutorial_id, str) and tutorial_id:
        row = conn.execute(
            "SELECT quiz_id FROM tutorials WHERE tutorial_id = ?", (tutorial_id,)
        ).fetchone()
        if row is None:
            err("$", f"tutorial_id '{tutorial_id}' does not exist — upload/publish the tutorial first")
        elif row["quiz_id"] and row["quiz_id"] != data.get("quiz_id"):
            warn("$", f"tutorial already has quiz '{row['quiz_id']}' — this upload will replace the link")
    if isinstance(data.get("quiz_id"), str):
        existing = conn.execute(
            "SELECT 1 FROM quizzes WHERE quiz_id = ?", (data["quiz_id"],)
        ).fetchone()
        if existing:
            warn("$", f"quiz '{data['quiz_id']}' exists — its questions will be replaced")

    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        err("$", "'questions' is required and must be a non-empty array")
        return f
    for i, q in enumerate(questions, start=1):
        where = f"questions[{i}]"
        if not isinstance(q, dict):
            err(where, "each question must be an object")
            continue
        if not isinstance(q.get("text"), str) or not q.get("text", "").strip():
            err(where, "'text' is required")
        options = q.get("options")
        if not isinstance(options, list) or len(options) < 2 or not all(
            isinstance(o, str) and o.strip() for o in options
        ):
            err(where, "'options' must be an array of at least 2 non-empty strings")
            options = None
        ci = q.get("correct_index")
        if not isinstance(ci, int) or isinstance(ci, bool):
            err(where, "'correct_index' is required and must be an integer (0-based)")
        elif options is not None and not (0 <= ci < len(options)):
            err(where, f"'correct_index' {ci} is out of range for {len(options)} options")
        if not q.get("concept_tag"):
            warn(where, "no 'concept_tag' — question won't appear in concept-mastery analytics")
        if not q.get("explanation"):
            warn(where, "no 'explanation' — students get no feedback text after answering")
        unknown = [k for k in q if not k.startswith("_")
                   and k not in ("text", "options", "correct_index", "concept_tag", "explanation")]
        if unknown:
            warn(where, f"unknown key(s) {unknown} — typo? (keys starting with _ are comments)")
    return f


def import_quiz(conn: sqlite3.Connection, data: dict, publish: bool = True) -> str:
    """Insert or replace a quiz and its questions from an authored dict."""
    quiz_id = data["quiz_id"]
    tutorial_id = data["tutorial_id"]
    now = time.time()
    conn.execute(
        """INSERT INTO quizzes (quiz_id, tutorial_id, title, is_published, updated_at)
           VALUES (?,?,?,?,?)
           ON CONFLICT(quiz_id) DO UPDATE SET
             tutorial_id = excluded.tutorial_id,
             title = excluded.title,
             is_published = excluded.is_published,
             updated_at = excluded.updated_at""",
        (quiz_id, tutorial_id, data.get("title", quiz_id), int(publish), now),
    )
    conn.execute("DELETE FROM quiz_questions WHERE quiz_id = ?", (quiz_id,))
    for pos, q in enumerate(data.get("questions", []), start=1):
        conn.execute(
            """INSERT INTO quiz_questions
               (quiz_id, position, text, options, correct_index, concept_tag, explanation)
               VALUES (?,?,?,?,?,?,?)""",
            (
                quiz_id, pos, q["text"], json.dumps(q["options"], ensure_ascii=True),
                int(q["correct_index"]), q.get("concept_tag", ""), q.get("explanation", ""),
            ),
        )
    conn.execute(
        "UPDATE tutorials SET quiz_id = ? WHERE tutorial_id = ?", (quiz_id, tutorial_id)
    )
    # One active quiz per tutorial: superseded quizzes are unpublished so
    # they drop out of stats/analytics listings (submissions are kept).
    conn.execute(
        "UPDATE quizzes SET is_published = 0 WHERE tutorial_id = ? AND quiz_id != ?",
        (tutorial_id, quiz_id),
    )
    conn.commit()
    return quiz_id


def get_quiz(
    conn: sqlite3.Connection, quiz_id: str, include_answers: bool = False
) -> dict | None:
    """Quiz + ordered questions. Students must NEVER receive correct_index /
    explanation here — those only travel through the check/submit endpoints,
    after an answer is committed."""
    meta = conn.execute(
        "SELECT * FROM quizzes WHERE quiz_id = ? AND is_published = 1", (quiz_id,)
    ).fetchone()
    if meta is None:
        return None
    questions = []
    for r in conn.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY position", (quiz_id,)
    ).fetchall():
        q = {
            "question_id": r["id"],
            "position": r["position"],
            "text": r["text"],
            "options": json.loads(r["options"]),
            "concept_tag": r["concept_tag"],
        }
        if include_answers:
            q["correct_index"] = r["correct_index"]
            q["explanation"] = r["explanation"]
        questions.append(q)
    return {
        "quiz_id": meta["quiz_id"],
        "tutorial_id": meta["tutorial_id"],
        "title": meta["title"],
        "questions": questions,
    }


def grade(conn: sqlite3.Connection, quiz_id: str, answers: list[int]) -> dict | None:
    """Server-side grading of a full answer sheet (by question position order).
    Returns per-question verdicts (with the right answers + explanations —
    the attempt is committed, so revealing them is the point) and a
    by-concept rollup for the result screen / mastery analytics."""
    rows = conn.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id = ? ORDER BY position", (quiz_id,)
    ).fetchall()
    if not rows:
        return None
    per_question = []
    by_concept: dict[str, dict] = {}
    correct_count = 0
    for i, r in enumerate(rows):
        chosen = answers[i] if i < len(answers) else -1
        is_correct = chosen == r["correct_index"]
        correct_count += is_correct
        per_question.append(
            {
                "question_id": r["id"],
                "chosen_index": chosen,
                "correct": is_correct,
                "correct_index": r["correct_index"],
                "concept_tag": r["concept_tag"],
                "explanation": r["explanation"],
            }
        )
        tag = r["concept_tag"] or "general"
        agg = by_concept.setdefault(tag, {"correct": 0, "total": 0})
        agg["total"] += 1
        agg["correct"] += is_correct
    return {
        "score": correct_count / len(rows),
        "correct_count": correct_count,
        "total": len(rows),
        "per_question": per_question,
        "by_concept": by_concept,
    }


def seed_quizzes(conn: sqlite3.Connection) -> None:
    """Boot-time import of authored quizzes whose tutorial exists. Idempotent:
    re-imports every boot so authored edits go live on restart (quizzes are
    unversioned, see module docstring)."""
    if not QUIZZES_DIR.is_dir():
        return
    have = {
        r["tutorial_id"]
        for r in conn.execute("SELECT tutorial_id FROM tutorials").fetchall()
    }
    for path in sorted(QUIZZES_DIR.glob("*.json")):
        if path.name.startswith("_"):
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if data.get("tutorial_id") in have and data.get("quiz_id"):
            import_quiz(conn, data)
