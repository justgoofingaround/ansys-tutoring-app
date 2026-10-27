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

With --drain it checks what is already waiting, says what it did and stops,
which is the shape for grading a batch after the lab rather than during it.

This only has work to do when the hub runs with REPORT_CHECKER=agent, which
makes it queue uploads instead of grading them itself. In the normal setup the
hub scores the rubric on upload and the instructor adds the AI review from
tools/grader_app.py, so nothing here ever runs.
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
SETTINGS_PATH = REPO_ROOT / "tools" / "checker.env"
IDLE_SLEEP_S = 10       # nothing waiting: how long before asking again
BUSY_SLEEP_S = 1        # work found: come back almost immediately
MAX_BACKOFF_S = 120     # hub unreachable: back off to this and stay there

log = logging.getLogger("report_checker")


def _settings_file() -> dict[str, str]:
    """HUB_URL / AGENT_TOKEN from tools/checker.env, if it exists.

    Reading them here rather than only from the environment is what lets the
    scheduled task hold no secret: the task line is just python + this script,
    and the token stays in one gitignored file the instructor edits once.
    Real environment variables still win, so a one-off run can override.
    """
    if not SETTINGS_PATH.exists():
        return {}
    out: dict[str, str] = {}
    for line in SETTINGS_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip("'\"")
    return out


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


def preflight(client: httpx.Client, use_llm: bool) -> tuple[bool, dict | None]:
    """Say plainly whether this machine can do the job, before it starts.

    Returns (ready, already_claimed): the claim doubles as the token check, so
    anything it hands back is carried into the loop rather than dropped. A
    missing model is not fatal, because the rubric decides pass or fail and
    needs nothing installed; only an unreachable hub or a bad token stops us.
    """
    try:
        r = client.post("/api/agent/reports/claim")
        if r.status_code == 401:
            print("  [X] The hub rejected the token.")
            print("      AGENT_TOKEN here has to match AGENT_TOKEN on the server.")
            return False, None
        r.raise_for_status()
        waiting = r.json() or None
        print(f"  [OK] Reached the hub at {client.base_url}")
    except httpx.HTTPError as exc:
        print(f"  [X] Could not reach the hub at {client.base_url}")
        print(f"      {exc}")
        print("      Check the address, and that this machine is on the NYU network or VPN.")
        return False, None

    if not use_llm:
        print("  [--] Rubric only (--no-llm was passed), which needs no model.")
        return True, waiting

    try:
        import ollama
    except ImportError:
        print("  [!] The 'ollama' package is missing from this Python environment.")
        print("      Run:  pip install ollama")
        print("      Reports will still be checked against the rubric.")
        return True, waiting

    try:
        from config import OLLAMA_MODEL  # compass settings, when importable
    except Exception:
        OLLAMA_MODEL = "gemma3:4b"

    try:
        installed = [str(m.get("model") or m.get("name") or "")
                     for m in (ollama.list().get("models") or [])]
    except Exception as exc:
        print("  [!] Ollama is installed but not answering:")
        print(f"      {str(exc).splitlines()[0][:150]}")
        print("      Start Ollama, or install it from https://ollama.com")
        print("      Reports will still be checked against the rubric.")
        return True, waiting

    family = OLLAMA_MODEL.split(":")[0]
    if any(n == OLLAMA_MODEL or n.startswith(family + ":") for n in installed):
        print(f"  [OK] Ollama is running and '{OLLAMA_MODEL}' is installed")
    else:
        print(f"  [!] Ollama is running, but '{OLLAMA_MODEL}' is not installed.")
        print(f"      Run:  ollama pull {OLLAMA_MODEL}")
        print("      Reports will still be checked against the rubric.")
    return True, waiting


def _drain_summary(checked: int, failed: int) -> str:
    if not checked and not failed:
        return "Nothing was waiting. Every report has already been evaluated."
    line = f"All reports evaluated: {checked} checked"
    if failed:
        line += (f", {failed} could not be read. Those are listed on the "
                 "Reports page for you to open by hand")
    return line + "."


def run(hub: str, token: str, once: bool, use_llm: bool, drain: bool = False) -> int:
    """Claim reports from the hub, check them, and post the results back.

    Continuous by default, which is what a running lab wants: an upload is
    checked within seconds. With --drain it checks everything already waiting,
    says what it did and stops, which is what grading a batch afterwards wants.
    """
    backoff = BUSY_SLEEP_S
    checked = failed = 0
    job: dict | None = None
    with httpx.Client(base_url=hub, headers={"X-Agent-Token": token}, timeout=120) as client:
        log.info("checker started against %s (llm allowed here: %s; the hub decides "
                 "per job)", hub, use_llm)
        if drain:
            print("Checking this machine:")
            ready, job = preflight(client, use_llm)
            print()
            if not ready:
                return 2

        while True:
            if job is None:
                try:
                    r = client.post("/api/agent/reports/claim")
                    if r.status_code == 401:
                        log.error("hub rejected the agent token - check AGENT_TOKEN on both sides")
                        return 1
                    r.raise_for_status()
                    job = r.json()
                    backoff = BUSY_SLEEP_S
                except httpx.HTTPError as exc:
                    log.warning("hub unreachable (%s); retrying in %ss", exc, backoff)
                    if drain:
                        print(f"Lost contact with the hub: {exc}")
                        print("Nothing is lost, the reports stay in the queue. Try again.")
                        return 1
                    time.sleep(backoff)
                    backoff = min(backoff * 2, MAX_BACKOFF_S)
                    continue

            if not job:
                if drain:
                    print(_drain_summary(checked, failed))
                    return 0
                if once:
                    log.info("queue empty")
                    return 0
                time.sleep(IDLE_SLEEP_S)
                continue

            sid = job["submission_id"]
            log.info("checking submission %s (%s)", sid, job["filename"])
            if drain:
                print(f"  #{sid}  {job['filename']} ... ", end="", flush=True)
            started = time.time()
            body = check_one(client, job, allow_llm=use_llm)
            outcome = ("could not be read" if body.get("failed")
                       else f"{body.get('score')}/{body.get('total')}")
            try:
                client.post(f"/api/agent/reports/{sid}/result", json=body).raise_for_status()
                log.info("submission %s -> %s in %.1fs", sid, outcome, time.time() - started)
                if body.get("failed"):
                    failed += 1
                else:
                    checked += 1
                if drain:
                    print(f"{outcome}  ({time.time() - started:.0f}s)")
            except httpx.HTTPError as exc:
                # The claim times out hub-side, so the work returns to the
                # queue on its own; no local retry state to keep.
                log.error("could not post the result for %s: %s", sid, exc)
                if drain:
                    print("the result could not be sent back")
                    print(f"      {exc}")
                    print("      This report stays in the queue; run the checker again.")
                    return 1

            job = None
            if once:
                return 0
            time.sleep(BUSY_SLEEP_S)


def main() -> int:
    conf = _settings_file()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--hub",
        default=os.environ.get("HUB_URL") or conf.get("HUB_URL") or "http://127.0.0.1:8000",
        help="hub origin, e.g. https://meuy4214.poly.edu",
    )
    ap.add_argument(
        "--token",
        default=os.environ.get("AGENT_TOKEN") or conf.get("AGENT_TOKEN"),
        help="shared secret; defaults to AGENT_TOKEN, then tools/checker.env",
    )
    ap.add_argument("--once", action="store_true",
                    help="check at most one report, then exit (for testing)")
    ap.add_argument("--drain", action="store_true",
                    help="check everything waiting, report what happened, then stop")
    ap.add_argument("--no-llm", action="store_true",
                    help="never run the Ollama review, even if the hub allows it")
    ap.add_argument("-v", "--verbose", action="store_true", help="also log to the console")
    args = ap.parse_args()

    if not args.token:
        print(f"No agent token. Put AGENT_TOKEN=... in {SETTINGS_PATH}, "
              "or pass --token.", file=sys.stderr)
        return 2

    _setup_logging(args.verbose)
    try:
        return run(args.hub, args.token, args.once, use_llm=not args.no_llm,
                   drain=args.drain)
    except KeyboardInterrupt:
        log.info("checker stopped")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
