"""FAQ pipeline: mine -> draft -> review -> publish.

Mining is instructor-triggered (no background scheduler in the pilot): it
groups verify_failed events by (tutorial_id, step_id, extra.failed_check)
and promotes a group to a candidate when at least `faq_threshold` of that
tutorial's attempters hit it (min cohort `faq_min_cohort` so one struggling
student in a class of three doesn't spawn FAQs).

Drafting uses local Ollama directly (not the chatbot's retrieval pipeline —
the source material here is the step's own authored text, not the Ansys
docs). With LLM off it returns an empty draft for the instructor to write
by hand; the review queue works either way, and nothing publishes without
an instructor pressing Approve.
"""

import json
import sqlite3
import time

from . import tutorial_store

DRAFT_PROMPT = """A student following an Ansys tutorial repeatedly failed a step check.

Step: {step_title}
What the step asks: {step_description}
Step hints: {hints}
Failed check: {failed_check}

Write a short FAQ entry that helps the NEXT student past this exact problem.
Answer with JSON only: {{"question": "...", "answer": "..."}}.
The question is what a confused student would ask (one sentence). The answer
is 2-4 short sentences, concrete and specific to this step."""


def _step_lookup(conn: sqlite3.Connection, tutorial_id: str) -> dict[str, dict]:
    found = tutorial_store.get_published(conn, tutorial_id)
    if not found:
        return {}
    content, _ = found
    return {
        st["step_id"]: st
        for sec in content.get("sections", [])
        for st in sec.get("steps", [])
    }


def mine_candidates(conn: sqlite3.Connection, settings) -> dict:
    """Upsert candidates from verify_failed events. Never downgrades a row
    that an instructor already acted on (drafted/approved/rejected)."""
    cohorts = {
        r["tutorial_id"]: r["n"]
        for r in conn.execute(
            """SELECT tutorial_id, COUNT(DISTINCT session_token) AS n
               FROM action_events GROUP BY tutorial_id"""
        ).fetchall()
    }
    groups = conn.execute(
        """SELECT tutorial_id, step_id,
                  COALESCE(json_extract(extra, '$.failed_check'), '') AS failed_check,
                  COUNT(DISTINCT session_token) AS students
           FROM action_events WHERE action_type = 'verify_failed'
           GROUP BY tutorial_id, step_id, failed_check"""
    ).fetchall()

    touched = 0
    for g in groups:
        cohort = cohorts.get(g["tutorial_id"], 0)
        if cohort < settings.faq_min_cohort:
            continue
        rate = g["students"] / cohort
        if rate < settings.faq_threshold:
            continue
        conn.execute(
            """INSERT INTO faq_candidates
               (tutorial_id, step_id, failed_check, distinct_students, cohort_size, failure_rate)
               VALUES (?,?,?,?,?,?)
               ON CONFLICT(tutorial_id, step_id, failed_check) DO UPDATE SET
                 distinct_students = excluded.distinct_students,
                 cohort_size = excluded.cohort_size,
                 failure_rate = excluded.failure_rate""",
            (g["tutorial_id"], g["step_id"], g["failed_check"],
             g["students"], cohort, round(rate, 3)),
        )
        touched += 1
    conn.commit()
    total = conn.execute(
        "SELECT COUNT(*) AS n FROM faq_candidates WHERE status = 'candidate'"
    ).fetchone()["n"]
    return {"open_candidates": total, "touched": touched}


def candidate_context(conn: sqlite3.Connection, cand: sqlite3.Row) -> dict:
    """Candidate row + the step's authored text (for display and drafting)."""
    step = _step_lookup(conn, cand["tutorial_id"]).get(cand["step_id"], {})
    return {
        "id": cand["id"],
        "tutorial_id": cand["tutorial_id"],
        "step_id": cand["step_id"],
        "failed_check": cand["failed_check"],
        "distinct_students": cand["distinct_students"],
        "cohort_size": cand["cohort_size"],
        "failure_rate": cand["failure_rate"],
        "status": cand["status"],
        "draft_question": cand["draft_question"],
        "draft_answer": cand["draft_answer"],
        "draft_model": cand["draft_model"],
        "step_title": step.get("title"),
        "step_description": step.get("description"),
        "step_hints": step.get("hints") or [],
    }


def draft_candidate(conn: sqlite3.Connection, settings, candidate_id: int) -> dict:
    """LLM-draft a question/answer for the candidate. status -> drafted."""
    cand = conn.execute(
        "SELECT * FROM faq_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if cand is None:
        raise KeyError("candidate_not_found")
    step = _step_lookup(conn, cand["tutorial_id"]).get(cand["step_id"], {})

    question, answer, model = "", "", ""
    if settings.enable_llm:
        import ollama

        try:
            from config import OLLAMA_MODEL  # chatbot_spike config (sys.path bridge)
        except Exception:
            OLLAMA_MODEL = "gemma3:4b"
        model = OLLAMA_MODEL
        prompt = DRAFT_PROMPT.format(
            step_title=step.get("title", cand["step_id"]),
            step_description=step.get("description", ""),
            hints="; ".join(step.get("hints") or []) or "none",
            failed_check=cand["failed_check"] or "manual verification failed",
        )
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            format="json",
        )
        try:
            parsed = json.loads(resp["message"]["content"])
            question = str(parsed.get("question", "")).strip()
            answer = str(parsed.get("answer", "")).strip()
        except (json.JSONDecodeError, TypeError):
            answer = resp["message"]["content"].strip()

    conn.execute(
        """UPDATE faq_candidates SET status = 'drafted', draft_question = ?,
           draft_answer = ?, draft_model = ?, drafted_at = ? WHERE id = ?""",
        (question, answer, model, time.time(), candidate_id),
    )
    conn.commit()
    return candidate_context(
        conn, conn.execute("SELECT * FROM faq_candidates WHERE id = ?", (candidate_id,)).fetchone()
    )


def approve_candidate(
    conn: sqlite3.Connection, candidate_id: int, question: str, answer: str, reviewer_id: int
) -> dict:
    """Publish the (instructor-edited) FAQ. status -> approved."""
    cand = conn.execute(
        "SELECT * FROM faq_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()
    if cand is None:
        raise KeyError("candidate_not_found")
    now = time.time()
    cur = conn.execute(
        """INSERT INTO faqs (tutorial_id, step_id, question, answer,
           source_candidate_id, created_by, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?)""",
        (cand["tutorial_id"], cand["step_id"], question, answer,
         candidate_id, reviewer_id, now, now),
    )
    conn.execute(
        """UPDATE faq_candidates SET status = 'approved', reviewed_by = ?,
           reviewed_at = ?, published_faq_id = ? WHERE id = ?""",
        (reviewer_id, now, cur.lastrowid, candidate_id),
    )
    conn.commit()
    return {"faq_id": cur.lastrowid}


def reject_candidate(conn: sqlite3.Connection, candidate_id: int, reviewer_id: int) -> None:
    conn.execute(
        """UPDATE faq_candidates SET status = 'rejected', reviewed_by = ?,
           reviewed_at = ? WHERE id = ?""",
        (reviewer_id, time.time(), candidate_id),
    )
    conn.commit()
