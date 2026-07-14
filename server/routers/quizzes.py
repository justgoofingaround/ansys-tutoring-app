"""Quiz endpoints.

Students GET a quiz WITHOUT correct answers or explanations; those are only
revealed per-question through /check (immediate feedback after committing a
choice) and in full through /submissions (the graded attempt). Instructors
GET the full quiz including answers.
"""

import json
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException

from ..deps import current_user, get_db, require_student
from ..models import QuizCheckIn, QuizSubmitIn
from ..services import quiz_store

router = APIRouter(prefix="/api/quizzes", tags=["quizzes"])


def _quiz_or_404(conn: sqlite3.Connection, quiz_id: str, include_answers: bool) -> dict:
    quiz = quiz_store.get_quiz(conn, quiz_id, include_answers=include_answers)
    if quiz is None:
        raise HTTPException(status_code=404, detail="quiz_not_found")
    return quiz


@router.get("/{quiz_id}")
def get_quiz(
    quiz_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    return _quiz_or_404(conn, quiz_id, include_answers=user["role"] == "instructor")


@router.post("/{quiz_id}/check")
def check_answer(
    quiz_id: str,
    body: QuizCheckIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    """Stateless per-question feedback: reveals the right answer + explanation
    for ONE question after the student commits a choice. Nothing is recorded —
    the graded attempt is the /submissions POST at the end."""
    row = conn.execute(
        "SELECT * FROM quiz_questions WHERE quiz_id = ? AND id = ?",
        (quiz_id, body.question_id),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="question_not_found")
    return {
        "question_id": row["id"],
        "correct": body.choice_index == row["correct_index"],
        "correct_index": row["correct_index"],
        "explanation": row["explanation"],
    }


@router.post("/{quiz_id}/submissions", status_code=201)
def submit_quiz(
    quiz_id: str,
    body: QuizSubmitIn,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> dict:
    quiz = _quiz_or_404(conn, quiz_id, include_answers=False)
    if len(body.answers) != len(quiz["questions"]):
        raise HTTPException(status_code=422, detail="answer_count_mismatch")
    result = quiz_store.grade(conn, quiz_id, body.answers)
    token = user["opaque_token"]
    attempt = (
        conn.execute(
            "SELECT COUNT(*) AS n FROM quiz_submissions WHERE session_token = ? AND quiz_id = ?",
            (token, quiz_id),
        ).fetchone()["n"]
        + 1
    )
    conn.execute(
        """INSERT INTO quiz_submissions
           (quiz_id, tutorial_id, session_token, answers, score, client_score,
            attempt, submitted_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            quiz_id, quiz["tutorial_id"], token, json.dumps(body.answers),
            result["score"], body.client_score, attempt, time.time(),
        ),
    )
    conn.commit()
    return {**result, "quiz_id": quiz_id, "tutorial_id": quiz["tutorial_id"], "attempt": attempt}


@router.get("/{quiz_id}/submissions/mine")
def my_submissions(
    quiz_id: str,
    conn: sqlite3.Connection = Depends(get_db),
    user: sqlite3.Row = Depends(require_student),
) -> list[dict]:
    return [
        {
            "attempt": r["attempt"],
            "score": r["score"],
            "submitted_at": r["submitted_at"],
        }
        for r in conn.execute(
            """SELECT attempt, score, submitted_at FROM quiz_submissions
               WHERE session_token = ? AND quiz_id = ? ORDER BY attempt DESC""",
            (user["opaque_token"], quiz_id),
        ).fetchall()
    ]
