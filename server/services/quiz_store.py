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
