"""Checks student reports on the instructor desktop, for a hub that can't.

The hub runs on a VM with no GPU. This runs where the GPU is: it polls the
hub for a waiting report, downloads it, runs the same rubric the hub would
have run — plus the AI review, which only exists here — and posts the result
back. Students see the outcome on their tutorial page as soon as it lands.

Only outbound HTTPS is used, so this machine needs no inbound rule, no fixed
address and no certificate. Close it and the queue simply stops draining;
nothing is lost and the hub keeps accepting uploads.

    set AGENT_TOKEN=<the same secret the hub has>
    .venv\\Scripts\\python tools\\report_checker.py --hub https://meuy4214.poly.edu
    .venv\\Scripts\\python tools\\report_checker.py --hub http://127.0.0.1:8000 --once

Run it under pythonw, or from a scheduled task at logon, to keep it quiet.
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.services import report_verify  # noqa: E402

LOG_PATH = REPO_ROOT / "server_data" / "report_checker.log"
IDLE_SLEEP_S = 10       # nothing waiting: how long before asking again
BUSY_SLEEP_S = 1        # work found: come back almost immediately
MAX_BACKOFF_S = 120     # hub unreachable: back off to this and stay there

log = logging.getLogger("report_checker")


def _setup_logging(verbose: bool) -> None:
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    handlers = [logging.FileHandler(LOG_PATH, encoding="utf-8")]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def check_one(client: httpx.Client, job: dict, allow_llm: bool) -> dict:
    """Download one report, run the rubric on it, and build the result body.

    A failure to read or parse the file is reported as failed rather than as
    a score of zero: a student whose .docx could not be opened has not earned
    a zero, and the instructor needs to see the difference.
    """
    sid = job["submission_id"]
    # The hub's ENABLE_AI wins: this machine may have a GPU and a model
    # sitting right there, but a hub with AI switched off must not get an
    # AI-written review back.
    use_llm = allow_llm and bool(job.get("ai_enabled"))
    suffix = Path(job["filename"]).suffix or ".bin"
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / f"submission_{sid}{suffix}"
        with client.stream("GET", f"/api/agent/reports/{sid}/file") as r:
            r.raise_for_status()
            with local.open("wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)

        try:
            result = report_verify.validate_report(
                local,
                {"report_checks": job.get("report_checks") or {}},
                use_llm=use_llm,
                guidelines=job.get("guidelines"),
            )
        except Exception as exc:  # unreadable file, parser blow-up, LLM crash
            log.exception("submission %s could not be checked", sid)
            return {
                "failed": True,
                "feedback": f"The checker could not read this file: {exc}",
            }

    return {
        "ok": bool(result["ok"]),
        "score": result["score"],
        "total": result["total"],
        "checks": result["checks"],
        "feedback": result["feedback"],
        "llm_review": result.get("llm_review"),
    }


def run(hub: str, token: str, once: bool, use_llm: bool) -> int:
    backoff = BUSY_SLEEP_S
    with httpx.Client(base_url=hub, headers={"X-Agent-Token": token}, timeout=120) as client:
        log.info("checker started against %s (llm allowed here: %s; the hub decides "
                 "per job)", hub, use_llm)
        while True:
            try:
                r = client.post("/api/agent/reports/claim")
                if r.status_code == 401:
                    log.error("hub rejected the agent token — check AGENT_TOKEN on both sides")
                    return 1
                r.raise_for_status()
                job = r.json()
                backoff = BUSY_SLEEP_S
            except httpx.HTTPError as exc:
                log.warning("hub unreachable (%s); retrying in %ss", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                continue

            if not job:
                if once:
                    log.info("queue empty")
                    return 0
                time.sleep(IDLE_SLEEP_S)
                continue

            sid = job["submission_id"]
            log.info("checking submission %s (%s)", sid, job["filename"])
            started = time.time()
            body = check_one(client, job, allow_llm=use_llm)
            try:
                client.post(f"/api/agent/reports/{sid}/result", json=body).raise_for_status()
                log.info("submission %s -> %s in %.1fs", sid,
                         "failed" if body.get("failed") else
                         f"{body.get('score')}/{body.get('total')}",
                         time.time() - started)
            except httpx.HTTPError as exc:
                # The claim times out hub-side, so the work returns to the
                # queue on its own; no local retry state to keep.
                log.error("could not post the result for %s: %s", sid, exc)

            if once:
                return 0
            time.sleep(BUSY_SLEEP_S)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default=os.environ.get("HUB_URL", "http://127.0.0.1:8000"),
                    help="hub origin, e.g. https://meuy4214.poly.edu")
    ap.add_argument("--token", default=os.environ.get("AGENT_TOKEN"),
                    help="shared secret; defaults to AGENT_TOKEN")
    ap.add_argument("--once", action="store_true",
                    help="check at most one report, then exit (for testing)")
    ap.add_argument("--no-llm", action="store_true",
                    help="never run the Ollama review, even if the hub allows it")
    ap.add_argument("-v", "--verbose", action="store_true", help="also log to the console")
    args = ap.parse_args()

    if not args.token:
        print("AGENT_TOKEN is not set (or pass --token)", file=sys.stderr)
        return 2

    _setup_logging(args.verbose)
    try:
        return run(args.hub, args.token, args.once, use_llm=not args.no_llm)
    except KeyboardInterrupt:
        log.info("checker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
