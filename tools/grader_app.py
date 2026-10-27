"""The instructor's grading app: AI review that only he can run.

Why this exists as a second app rather than a button on the dashboard.
Anyone who learns the instructor password can sign into the hub from any
browser. Running the model is meant to be the professor's alone, so the
trigger must not be reachable with a password at all. It lives here, on his
desktop, behind two things a password does not give you: the AGENT_TOKEN in
tools/checker.env, and a server bound to 127.0.0.1 that nothing off this
machine can reach.

What it is: a small local web app. He opens http://127.0.0.1:8765 in a
browser on his own machine, sees the submitted reports with names, runs the
AI review on whichever he likes, and writes the feedback students see. The
report file is downloaded from the hub, graded here, and the result posted
back through the same agent API the background checker uses. Nothing is
stored on this machine: the temporary copy is deleted as soon as it is read.

    .venv\\Scripts\\python tools\\grader_app.py
    .venv\\Scripts\\python tools\\grader_app.py --port 9000 --open

Settings come from tools/checker.env (HUB_URL, AGENT_TOKEN), the same file
the background checker reads.
"""

import argparse
import contextlib
import sys
import tempfile
import threading
import webbrowser
from pathlib import Path

import httpx
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from server.services import report_verify  # noqa: E402
from tools.report_checker import _settings_file  # noqa: E402

PAGE_PATH = Path(__file__).parent / "grader_app.html"

# One at a time. The GPU is single, and two reviews at once on a laptop is
# how you get an out-of-memory crash halfway through a grading session.
_review_lock = threading.Lock()


def build_app(hub: str, token: str) -> FastAPI:
    app = FastAPI(title="Report grading (local)", docs_url=None, redoc_url=None)
    client = httpx.Client(base_url=hub, headers={"X-Agent-Token": token}, timeout=180)

    def hub_get(path: str, **kw) -> httpx.Response:
        try:
            r = client.get(path, **kw)
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"Cannot reach the hub: {exc}")
        if r.status_code == 401:
            raise HTTPException(status_code=401, detail="The hub rejected AGENT_TOKEN.")
        return r

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        # Read per request, not once at import: a few KB costs nothing, and
        # editing the page then does not need the app restarted.
        return PAGE_PATH.read_text(encoding="utf-8")

    @app.get("/api/health")
    def health() -> dict:
        """What the page shows in its status bar: can we work right now."""
        out = {"hub": hub, "hub_ok": False, "ai_allowed": False,
               "ollama": False, "model": report_verify.default_model(), "detail": ""}
        try:
            r = client.get("/api/agent/config")
            out["hub_ok"] = r.status_code == 200
            if r.status_code == 401:
                out["detail"] = "The hub rejected AGENT_TOKEN (check tools/checker.env)."
            elif r.status_code == 404:
                out["detail"] = "This hub is too old: it has no agent API. Redeploy it."
            elif r.status_code == 200:
                out["ai_allowed"] = bool(r.json().get("ai_enabled"))
                if not out["ai_allowed"]:
                    out["detail"] = ("The hub has report AI switched off. Set "
                                     "ENABLE_REPORT_AI=1 there to allow reviews.")
        except httpx.HTTPError as exc:
            out["detail"] = f"Cannot reach {hub}: {exc}"
            return out
        with contextlib.suppress(Exception):
            import ollama

            names = [str(m.get("model") or m.get("name") or "")
                     for m in (ollama.list().get("models") or [])]
            family = out["model"].split(":")[0]
            out["ollama"] = any(n == out["model"] or n.startswith(family + ":") for n in names)
            if not out["ollama"]:
                out["detail"] = f"Ollama is running but {out['model']} is not installed."
        if not out["ollama"] and not out["detail"]:
            out["detail"] = ("Ollama is not running on this machine. Start it, "
                             f"or run: ollama pull {out['model']}")
        return out

    @app.get("/api/reports")
    def reports(status: str | None = None) -> list:
        params = {"status": status} if status else {}
        r = hub_get("/api/agent/reports", params=params)
        r.raise_for_status()
        rows = r.json()
        # ai_allowed is a hub decision and the page needs it per refresh.
        return rows

    @app.post("/api/reports/{submission_id}/review")
    def review(submission_id: int) -> dict:
        """Grade one report here, now: rubric plus the model, then post back."""
        claim = client.post(f"/api/agent/reports/{submission_id}/claim")
        if claim.status_code == 410:
            raise HTTPException(status_code=410, detail="The uploaded file is gone from the hub.")
        claim.raise_for_status()
        job = claim.json()
        if not job.get("ai_enabled"):
            raise HTTPException(
                status_code=409,
                detail="The hub has report AI switched off (ENABLE_REPORT_AI).",
            )

        suffix = Path(job["filename"]).suffix or ".bin"
        with _review_lock, tempfile.TemporaryDirectory() as tmp:
            local = Path(tmp) / f"submission_{submission_id}{suffix}"
            with client.stream("GET", f"/api/agent/reports/{submission_id}/file") as resp:
                resp.raise_for_status()
                with local.open("wb") as fh:
                    for chunk in resp.iter_bytes():
                        fh.write(chunk)
            try:
                result = report_verify.validate_report(
                    local,
                    {"report_checks": job.get("report_checks") or {}},
                    use_llm=True,
                    guidelines=job.get("guidelines"),
                )
            except Exception as exc:
                body = {"failed": True,
                        "feedback": f"The grader could not read this file: {exc}"}
                client.post(f"/api/agent/reports/{submission_id}/result", json=body)
                raise HTTPException(status_code=422, detail=f"Could not read the file: {exc}")

        body = {
            "ok": bool(result["ok"]), "score": result["score"], "total": result["total"],
            "checks": result["checks"], "feedback": result["feedback"],
            "llm_review": result.get("llm_review"),
        }
        client.post(f"/api/agent/reports/{submission_id}/result", json=body).raise_for_status()
        return body

    @app.post("/api/reports/{submission_id}/feedback")
    def feedback(submission_id: int, body: dict) -> dict:
        r = client.post(f"/api/agent/reports/{submission_id}/feedback", json=body)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text[:300])
        return r.json()

    return app


def main() -> int:
    conf = _settings_file()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hub", default=conf.get("HUB_URL") or "http://127.0.0.1:8000")
    ap.add_argument("--token", default=conf.get("AGENT_TOKEN"))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--open", action="store_true", help="open a browser on start")
    args = ap.parse_args()

    if not args.token:
        print(f"No agent token. Put AGENT_TOKEN=... in {REPO_ROOT / 'tools' / 'checker.env'}",
              file=sys.stderr)
        return 2

    url = f"http://127.0.0.1:{args.port}"
    print(f"Grading app on {url}  (hub: {args.hub})")
    print("Only this machine can reach it. Press Ctrl+C to stop.")
    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    # host is 127.0.0.1 and not 0.0.0.0 deliberately: the whole point of this
    # app is that being on the network is not enough to use it.
    uvicorn.run(build_app(args.hub, args.token), host="127.0.0.1",
                port=args.port, log_level="warning")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
