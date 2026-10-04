# ME-UY 4214 Tutoring Hub — Response to Tandon Security & AI Review

**Host:** meuy4214.poly.edu · **Pilot:** Fall 2026 · **Prepared:** 2026-09-17
**Scope:** every numbered question in *Questions for Tandon ANSYS Chatbot*.

Answers below are drawn from the deployed code and configuration, with file references
so any claim can be checked directly. Where the honest answer is "no" or "not yet," it
says so rather than describing an intention.

---

## 0. Corrections to information previously provided

Three things in earlier correspondence were inaccurate or imprecise. Correcting them up
front, because several of the review's questions turn on them.

1. **File uploads ARE enabled.** Students upload lab reports
   (`.docx .pdf .html .htm .txt .md .markdown .json`, 20 MB cap) at
   `POST /api/tutorials/{id}/report` (`server/routers/reports.py`). The earlier
   "uploads are not enabled" statement was wrong. Details in §6.
2. **"Only accessible via the NYU LAN" is not correct.** The host is reachable from the
   public internet: we verified an HTTPS GET returning 200 from an off-campus home
   connection on 2026-09-14. The reviewer's inference from the ACME challenge is right.
   See §A2. This claim should be withdrawn and restated, not defended.
3. **There is no GPU.** The architecture document describes an instructor desktop with
   a GPU. The actual pilot host is a 2-vCPU / 15 GB-RAM VM running CPU-only inference
   (`deploy/docker-compose.yml`). This materially changes the concurrency answer (§14).

---

## Non-AI Questions

### A1. Is the tutor mandatory or voluntary?

The platform supports both: `tutorials.is_mandatory` (`server/schema.sql`) is a
per-tutorial instructor setting. **[CONFIRM — course policy, not a technical decision:
state the Fall 2026 intent.]** Note that the Compass chatbot specifically is always
voluntary: it sits behind a consent screen a student can decline, and declining blocks
nothing else (§11c).

### A2. Let's Encrypt / ACME vs. LAN-only access

The reviewer is right, the earlier description was wrong, and the certificate
description is accurate — it is the "LAN-only" claim that does not hold.

Sequence of events, stated plainly:

- The cert was obtained with `certbot certonly --standalone` directly on the host
  (`deploy/DEPLOY-NYU.md` §4). Standalone mode binds port 80 and serves the ACME
  challenge to Let's Encrypt's validation servers, which connect **from the public
  internet**. A host with no inbound path from outside NYU cannot complete that
  challenge.
- At the time the app was first deployed (2026-08-14), 80/443 were in fact firewalled
  externally — SSH on 22 worked from off-campus but 443 timed out. We then **requested
  that HTTP/HTTPS be opened** on the box firewalld or the NYU ACL for 128.238.147.50, in
  order to make the site reachable.
- That request was granted. On **2026-09-14 we verified an HTTPS GET returning 200 from
  an off-campus home connection.** The host is therefore internet-facing today, by our
  own request, and the only access control in front of student data is the application
  login.

**[CONFIRM with the box admin, and attach raw output, so the reviewer has the current
authoritative state rather than our observation:]**
- `dig +short meuy4214.poly.edu` — public A record?
- `sudo firewall-cmd --list-all` — zones, services, rich rules, source CIDRs
- `sudo iptables -S` / `sudo nft list ruleset`
- Whether any NYU perimeter ACL still restricts inbound to campus ranges.

**Our recommendation:** pick one posture and make the configuration match the claim.
Either (a) restrict inbound 443 to NYU CIDRs with a firewalld rich rule and move the
certificate to a DNS-01 challenge, which needs no inbound port 80 and would also fix the
renewal problem below — this restores the "NYU-network-only" property that was described
to the reviewer; or (b) accept that the host is internet-facing, document it as such,
and apply the controls appropriate to an internet-exposed FERPA system. We would prefer
(a), since nothing about the pilot requires off-campus access.

**Related defect, already known to us:** certificate renewal **will fail** as currently
configured. The cert was issued in standalone mode, but the nginx container now holds
port 80, so unattended standalone renewal cannot bind. `deploy/DEPLOY-NYU.md` §4
documents the fix (switch to webroot mode against the shared `certbot-webroot` volume
with a deploy hook reloading nginx) and it is pending with the box admin.

### A3. How is access restricted to the NYU network?

**It is not.** As established in A2, the site answers from off-campus. Access control is
at the application layer only: authentication is required on every route
(`server/deps.py:current_user`), and students self-register with a section code
(`SEC-XXXXXX`) issued by the instructor. **There is no network-layer restriction to NYU
ranges in our configuration.** The app container binds `127.0.0.1:8000` and is reachable
only through the nginx container on 443 — but nginx accepts any source IP the host
firewall permits, which is currently any.

Worth noting alongside this: registration is open to anyone holding a section code, and
the code is a shared 6-character string distributed to the class. Combined with public
reachability, that means the registration endpoint is exposed to the internet. Not
high-risk on its own — a forged account sees only tutorials — but it is the kind of thing
posture (a) in A2 would close.

### A4. Firewall settings

Not owned or configured by this project; the host is administered by NYU IT. Our
runbook's only firewall note is a fallback `firewall-cmd --add-service=http
--add-service=https` if campus machines cannot reach the site. **[CONFIRM: the box admin
must supply the current ruleset.]**

---

## 1. Which specific model is served?

**a/b. Exact tag and digest.** The served model is **`gemma3:4b`**, pulled per
`deploy/DEPLOY-NYU.md` §6 (`docker exec tutoring-hub-ollama ollama pull gemma3:4b`). The
application reference is `chatbot_spike/config.py:OLLAMA_MODEL = "gemma3:4b"`, read by
`server/services/chatbot_service.py:OllamaEngine`. Report review and FAQ drafting use
the same constant (`server/services/report_verify.py`).

**The tag is NOT pinned by digest.** `gemma3:4b` is a mutable tag; a re-`pull` could
change the served weights with no code change and no review. To supply the digest
currently in service, run on the host:

```bash
docker exec tutoring-hub-ollama ollama list
docker exec tutoring-hub-ollama ollama show gemma3:4b --modelfile
```

**[ATTACH that output to the response.]**

*Remediation we propose before the pilot:* pin by digest
(`gemma3:4b@sha256:<digest>`) in `chatbot_spike/config.py`, record it in the runbook,
and treat a digest change as a reviewable code change.

**c. Only Gemma 3? Any Chinese-origin open-weight models?**

Confirmed: **the only model served on the NYU host is Gemma 3 (Google, US).** No Qwen,
DeepSeek, Yi, GLM, InternLM or other PRC-origin weights are pulled or referenced
anywhere in the deployment.

One disclosure for completeness: the codebase contains a second, alternative engine
(`CloudApiEngine`, `server/services/chatbot_service.py`) that routes generation to an
OpenAI-compatible cloud API. It activates **only** if `CHATBOT_API_KEY` is set. It is
deliberately **not set on the NYU host** — `deploy/docker-compose.yml` does not pass it,
and `deploy/DEPLOY-NYU.md` warns twice that setting it there would break the FERPA
invariant. That path is used only on a separate throwaway Render deployment for team
testing with no student data, where it points at Groq's `openai/gpt-oss-20b` (OpenAI
weights). Verify on the host:

```bash
docker exec tutoring-hub env | grep -c CHATBOT_API_KEY   # expect 0
```

---

## 2. Safeguards

**a. Verbatim system prompt.** The student-facing Compass prompt is
`chatbot_spike/generate.py:SYSTEM_PROMPT`, reproduced exactly:

```
You are Compass, an assistant embedded in a tutoring tool for NYU's ME-UY 4214 Finite
Element Analysis course, helping students use Ansys Mechanical. If asked your name,
say you're Compass.

Rules:
1. Answer ONLY using the numbered context passages provided. If the context doesn't
contain the answer, say so plainly instead of guessing.
2. PARAPHRASE the documentation in your own words. Never quote more than a short
phrase verbatim -- this is a licensing requirement (Ansys Academic license), not a
style preference.
3. Mark every factual claim with the bracketed number(s) of the context passage(s)
it came from, like [1] or [2][3].
4. BE BRIEF -- a student is mid-tutorial waiting for an answer. Default to 2-4 short
sentences or a short list of 2-3 steps. Only go longer if the question explicitly asks
for a full walkthrough or a comparison of multiple methods.
5. If `tutorial context` is provided below, tailor the answer to that step rather
than giving a fully generic answer -- don't re-explain things the student has clearly
already done (e.g. don't say "first create a Static Structural analysis" if the context
says they're already several steps past that).
```

**Generation parameters** (`chatbot_spike/generate.py:stream_answer`):
`num_predict = 220` (`MAX_RESPONSE_TOKENS` in `chatbot_spike/config.py`). Temperature
and context window are **left at Ollama/Gemma-3 defaults — not explicitly set.**
*(Recommendation: set temperature explicitly, e.g. 0.2, and pin `num_ctx`.)*

**Prompt assembly, end to end:**
`webapp/src/pages/student/ChatPage.tsx` → `POST /api/chatbot/query` →
`server/routers/chatbot.py:chat_query` (consent check; `_tutorial_context()` builds a
"Tutorial title — step: title" string from the published tutorial JSON) →
`server/services/chatbot_service.py:OllamaEngine.generate` →
`chatbot_spike/retrieve.py:retrieve` (hybrid search) →
`chatbot_spike/generate.py:_build_user_message` (numbered context block + optional
tutorial context + the student's question) → `ollama.chat`.

The only student-authored text reaching the model is the question itself; tutorial
context is instructor-authored content.

**Report review** uses a separate prompt (`server/services/report_verify.py:
_review_report_with_llm`) with `temperature: 0`, `num_predict: 260`, `format="json"`.
That prompt *does* contain instructor free text (`report_guidelines`) and an excerpt of
the student's uploaded report — see §12.

**b. What happens when retrieval returns nothing relevant?**

Two distinct cases, and the honest answer differs between them:

- *Zero chunks returned* (only if the index is empty or missing): the code
  short-circuits without calling the model and returns the fixed string "I couldn't
  find anything in the indexed Ansys documentation relevant to that question."
  (`chatbot_spike/generate.py:stream_answer`).
- *Chunks returned but none actually relevant* — the realistic case: the model **is**
  called with those six passages, and abstention depends entirely on Gemma 3 4B obeying
  Rule 1 of the system prompt. There is no mechanical guarantee, and we would not
  represent a 4B model's instruction-following here as reliable absent the evaluation
  in §10, which has not been run.

**c. Is there a relevance threshold below which the bot abstains?**

**No.** `chatbot_spike/retrieve.py` fuses semantic and BM25 rankings with Reciprocal
Rank Fusion and returns the top 6 unconditionally — RRF produces rank-based scores with
no meaningful absolute cutoff, and no distance or score threshold is applied anywhere.
Every question receives six passages regardless of match quality.

*Remediation we propose:* capture the raw ChromaDB cosine distance before fusion and
abstain when the best chunk exceeds a tuned threshold. Contained change; we would rather
make it before the pilot than defend the current behavior.

**d. Are retrieved sources shown to the student?**

**Not currently — this is a regression we introduced on 2026-09-14 and intend to
reverse.** Commit `bca9eca` strips the model's `[n]` markers client-side and stops
rendering the source list (`webapp/src/pages/student/ChatPage.tsx:renderAnswer`). Sources
are still computed, streamed over SSE and written to `chatbot_queries.sources`, so the
instructor can see them; the student cannot.

The citations that *are* recorded carry document filename + page number (e.g.
`ANSYS_Meshing_Users_Guide.pdf p. 218`), from `chunk["metadata"]["citation"]`. Document
and section-by-page: yes. Product *version*: not in the citation string — and see §9 for
why that matters acutely here.

*Remediation:* restore the visible source list before the pilot. A student unable to
check an answer against the document is a real defect, not a UI preference.

---

## 3. Human in the loop

**a. FERPA applicability.** Conceded without qualification. This is a graded-courseware
platform storing student identity, quiz scores, uploaded lab reports and free-text
submissions, and exporting cohort analytics. It is subject to FERPA and should be
reviewed as such, not as a standalone chatbot.

What the design does get right, and which we ask be credited accurately: every
analytics table (`action_events`, `quiz_submissions`, `report_submissions`,
`chatbot_queries`) stores **only** an opaque token (`student_a4f9c2`), never a username.
CSV exports (`server/routers/instructor.py:export_csv`) select from those tables
verbatim and are therefore token-only by construction. The username↔token join exists in
exactly one place — the instructor dashboard queries. That limits blast radius; it does
not take the system out of FERPA scope.

**b. Who reviews grading and model output for accuracy?**

An important distinction, and it is favorable:

- **Quizzes are not AI-graded.** Instructor-authored multiple choice, graded server-side
  by exact index comparison against the stored answer key
  (`server/services/quiz_store.py:grade`, `server/routers/quizzes.py`). No model is in
  that path at all.
- **Report scores are not AI-generated.** `ok / score / total` come solely from
  deterministic rubric checks — required section headings, required phrases, and a
  numeric result within a stated tolerance
  (`server/services/report_verify.py:validate_report`). The local LLM produces a
  separate narrative `llm_review` (`overall / strengths / caveats / suggestions /
  confidence`) shown to the student and stored, which **never contributes to the
  score**. This is enforced structurally: `score` is computed before
  `_review_report_with_llm` is called and is not touched afterward.
- **Compass answers are not reviewed before display.** They stream live. Instructor
  review is retrospective only, via the logged `chatbot_queries` table.

**[CONFIRM: name the faculty member responsible for retrospective review and the
cadence — e.g. "instructor reviews the chatbot_queries export weekly during the pilot."
No review cadence is currently defined, which is a fair criticism.]**

**c. Can students challenge the tutor's output?**

**No in-product mechanism exists** — no thumbs-down, flag or report control. The only
channel is contacting the instructor directly. *Remediation:* add a per-answer "flag
this answer" control writing to a table the instructor dashboard surfaces. Small change;
worth doing before the pilot.

**d. AI must not autograde anything contributing to a final grade.**

Agreed, and the architecture already complies as described in 3b: no model output feeds
any score. We accept this as a binding pilot constraint and propose stating it
explicitly in the pilot agreement: *no AI-generated output contributes to any grade of
record; all graded artifacts are either deterministically scored against an
instructor-authored key or reviewed by the instructor.*

---

## 4. Input handling

**a. What happens to student text before it reaches the model or the database?**

Honestly, very little.

- **Size limits:** question capped at 2,000 characters
  (`server/models.py:ChatQueryIn`); report uploads capped at 20 MB, enforced while
  streaming (`reports.py`); nginx `client_max_body_size 25m`.
- **Storage safety:** all DB writes are parameterized SQL; upload filenames are
  sanitized to `[A-Za-z0-9._-]` and `Path(...).name`-stripped, so no path traversal.
- **Filtering / redaction / classification: none.** No PII redaction, no profanity or
  safety classifier, no content categorization. Question text is stored verbatim in
  `chatbot_queries.question`.

**b. Data classification under NYU's standard.**

Our assessment: the store contains student education records and free-text student
submissions, which we read as **NYU "Restricted"** (FERPA-protected), not Confidential
or Public. We defer to the reviewer's formal determination. Relevant contents: `users`
(self-chosen username + bcrypt hash + section), `chatbot_queries` (token + verbatim
question + answer), `report_submissions` (token + original filename + score + LLM
narrative), `quiz_submissions` (token + answers + score), and the uploaded report files
themselves, which contain student names in their body text.

**c. Where do the backups go?**

The runbook's only backup instruction is `tar czf hub-backup-$(date +%F).tgz
../server_data` — a local tarball in the deploy directory on the same host. **There is
no defined offsite destination, no schedule, no encryption and no rotation.** Nothing
currently copies data off the host, so nothing leaves NYU infrastructure; equally, there
is no recovery story if the host is lost. **[CONFIRM: whether the VM is covered by
NYU-managed VM-level backup.]** *Remediation:* define an NYU-managed destination, or
state plainly that the pilot runs without backups and accept the availability risk.

**d. Encryption at rest.**

Not implemented at the application layer: `server_data/app.db` is a plain SQLite file
(WAL mode) bind-mounted from the host, and uploaded reports are plain files under
`server_data/uploads/reports/<opaque_token>/`. Whether the underlying volume is
encrypted depends on the host build. **[CONFIRM with the box admin:
`lsblk -o NAME,FSTYPE,MOUNTPOINT`, and whether LUKS is in use.]** If the volume is not
encrypted we should say so plainly rather than imply otherwise.

**e. Retention period and enforcement.**

**There is no retention policy and no purge mechanism.** Verified directly: no scheduled
job, no TTL, no deletion code path anywhere in the server. Records persist until
manually deleted. The previous answer on this was accurate.

*Remediation we propose:* define retention (our suggestion: raw `chatbot_queries` and
uploaded reports purged at end of term + 30 days; aggregate analytics retained for the
grant's research purpose), implement it as a `tools/purge.py` driven by a systemd timer,
and log each run. Straightforward to build; it simply has not been.

---

## 5. Internet access and egress

**a. Outbound calls at inference time: none.**

On the NYU host the entire inference path is host-local. `OllamaEngine` calls the
`ollama` container at `http://ollama:11434` over the Docker Compose bridge network. That
container **publishes no ports** (`deploy/docker-compose.yml` has no `ports:` key), so
it is unreachable from the network. Retrieval reads ChromaDB and a pickled BM25 index
from a bind-mounted folder. No network call occurs.

**b. What httpx is for.**

`httpx` is used in exactly one place: `CloudApiEngine.generate`
(`server/services/chatbot_service.py`) — the cloud engine that is **not active on the
NYU host** (§1c). With `CHATBOT_API_KEY` unset, no httpx client is ever constructed.
`grep -rn "httpx" server/` returns only that file.

Three further egress paths were closed deliberately, visible in the `Dockerfile`:

- `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` — the `all-MiniLM-L6-v2` embedding model
  is baked into the image at build time; sentence-transformers never calls Hugging Face
  at runtime.
- `ANONYMIZED_TELEMETRY=False` — ChromaDB reports usage events by default; disabled.
- No model download at runtime: `ollama pull` is a one-time manual deploy step.

**Egress is not restricted at the host or network level** by anything we configured —
the guarantees above are application-level. *Remediation:* if the reviewer wants a hard
guarantee, an egress-deny firewall rule on the host (or a Docker network with no default
route for the `hub` container) would enforce it independently of code. We would support
that.

**c. Can the retrieval corpus be updated at runtime, and by whom?**

**No runtime path exists.** The index is a pre-built artifact in `chatbot_spike/data/`,
bind-mounted but written by nothing in the running application — there is no ingest
endpoint and no UI for it. Changing the corpus requires filesystem access to the host,
running `ingest.py` on a machine holding the source PDFs, copying ~230 MB across, and
restarting the container. In practice: the project maintainer, plus anyone with host
shell access.

---

## 6. File uploads

**a. Reconciling the contradiction.** The earlier "no file uploads" statement was simply
wrong; the security answers describing stored lab reports were correct. Uploads are, and
have been, enabled.

**b. What is accepted and what happens to it.**

- **Accepted types:** `.docx .pdf .html .htm .txt .md .markdown .json`
  (`ALLOWED_SUFFIXES`, `server/routers/reports.py`).
- **Validation:** extension allow-list; 20 MB streaming size cap; filename sanitized;
  content parsed by type — PyMuPDF for PDF, stdlib `zipfile` + XML text extraction for
  DOCX, stdlib `HTMLParser` for HTML. Malformed files raise 422 and the stored file is
  deleted. There is **no antivirus scan and no content-type sniffing** beyond the
  extension check.
- **Is uploaded content parsed into the model's context?** Into the *local* model's
  context, yes; into the retrieval index, no. Precisely: an excerpt of the extracted
  report text (up to ~70 keyword-selected lines, `_report_excerpt`) is sent to the local
  Ollama model for the narrative review. It is **never** added to the retrieval index,
  never sent to any cloud API on this host, and never used to answer another student's
  question. The extracted text is deliberately not returned in the API response either
  (`reports.py`, explicit comment).
- **Retention:** indefinite (§4e). Files persist at
  `server_data/uploads/reports/<opaque_token>/<timestamp>_<filename>` with the DB row in
  `report_submissions`.
- **Access model:** no route serves uploaded files back to anyone — not students, not
  instructors. `stored_path` is recorded in the DB but no endpoint reads the file after
  validation. Retrieval is by host filesystem access only.

Note: the *path* is pseudonymous (opaque token), but the *content* contains student
names, and `report_submissions.filename` preserves the student's original filename,
which frequently contains a name. That is identifying data in an otherwise token-only
table, and we flag it rather than let it be discovered.

**c/d. Who can read uploaded reports and the prompt database, under what authority?**

- **The instructor account** — a single account seeded from `INSTRUCTOR_USERNAME` /
  `INSTRUCTOR_PASSWORD` in `deploy/.env` (mode 600). It can read all dashboards, the
  username↔token mapping, quiz/report/chat analytics and all CSV exports. It cannot read
  uploaded files (no endpoint exists).
- **Anyone with shell access to the host** — the `ay3140` account and root (NYU IT / the
  box administrator). Unrestricted: the SQLite file and every uploaded report are
  readable directly.
- **No one else.** No third-party processor, no cloud storage, no analytics SDK.

Two weaknesses to state rather than gloss: there is exactly **one shared instructor
credential** — no per-TA accounts, so dashboard access has no individual attribution —
and **no access logging** beyond nginx request logs. *Remediation:* named instructor
accounts and an access log for identity-joining queries, if the reviewer considers that
in scope for a pilot.

---

## 7. Concerning content and off-task use

**a. Scope enforcement.**

The only mechanism is the system prompt's framing ("an assistant embedded in a tutoring
tool for NYU's ME-UY 4214... helping students use Ansys Mechanical") plus Rule 1's
instruction to answer only from the retrieved Ansys passages. **There is no classifier,
no topic filter, and no input or output gate.** A student asking an off-topic question
receives six irrelevant Ansys passages and whatever Gemma 3 4B does with them — which,
given no relevance threshold (§2c), may be a general-knowledge answer rather than a
refusal.

On academic integrity: the tool is course-scoped by design (reached from inside a lab
tutorial), and quiz answers are never in the retrieval corpus — the index contains only
Ansys product documentation, not course assessments. However, **the academic integrity
position has not been reviewed with any Tandon authority.** We would welcome direction
on whether use during assessed work should be blocked; if so, we can gate Compass on
quiz state.

**b. Model output safety / adversarial testing.**

**No adversarial testing, jailbreak testing or harmful-content testing has been
performed.** There is **no output filtering of any kind** between the model and the
student — `stream_answer` yields tokens straight through SSE to the browser.

We accept the reviewer's characterization: an open-weight 4B model served through Ollama
with no provider-side moderation has weaker refusal behavior than a hosted commercial
model, and nothing here compensates for that.

*Remediation options, in the order we would recommend:*
1. Run a structured red-team pass before the pilot (jailbreak prompts, harmful-content
   requests, prompt injection via the tutorial-context field) and publish the results.
2. Add an output gate — a keyword or classifier check between generation and display.
3. Both.

**c. Student disclosure of self-harm, threats, harassment, or sensitive personal
information.**

**Stated plainly, as the reviewer asked: there is no detection. Nothing flags such
content, nothing notifies anyone, and no one monitors the database.** A disclosure of
this kind would be written verbatim to `chatbot_queries.question` and would sit unread
unless an instructor happened to review the logs.

There is **no escalation path, no owner, and no review with the office that would
normally receive such a report** (the Wellness Exchange / Student Affairs). We have not
engaged them.

This is the item in this review we consider most serious, because unlike the others it
involves a student in distress rather than a data or accuracy concern. We are not asking
for it to be accepted as-is. Our proposal, before the pilot: (1) add a keyword-triggered
detection path that surfaces crisis resources to the student in-product and raises an
instructor alert; (2) agree an escalation owner and route with the Wellness Exchange;
(3) state in the consent screen that submissions are logged and read by the instructor.
If the reviewer prefers the risk be formally accepted instead, it should be accepted
explicitly and in writing.

---

## 8. Corpus provenance and licensing

**a. What is in the index and where it came from.**

18 PDFs from the official Ansys product documentation set, curated from the full
284-document / 3.2 GB distribution down to the Mechanical / Workbench / Meshing /
DesignModeler subset relevant to this course
(`chatbot_spike/config.py:RELEVANT_DOCS`). The complete list with chunk counts is in
`chatbot_spike/data/index_manifest.json`; it includes `Ansys_Mechanical_Users_Guide.pdf`
(3,159 chunks), `SpaceClaim_Documentation.pdf` (1,351), `Workbench_Scripting_Guide.pdf`
(1,332), `ANSYS_Meshing_Users_Guide.pdf` (1,011), and the Mechanical APDL guides. Total
≈ 11,100 chunks of ~400 tokens each.

The source is the Ansys documentation distribution available under the university's
Ansys Academic license. **No other documents are in the index** — no course materials, no
student work, no web-scraped content.

**b. Licensing and Ansys engagement.**

**No engagement with Ansys has taken place, and OGC has not reviewed this.** We should
not represent otherwise.

What the implementation does do — relevant, but not a substitute for a license
determination: Rule 2 of the system prompt forbids verbatim quotation beyond a short
phrase and requires paraphrase, explicitly on licensing grounds, and every answer records
its source documents. The index stores extracted chunk text, so the documentation text
does reside on the host in a derived form.

We agree this is a question for the Ansys agreement and likely OGC, and we would rather
have that determination before the pilot than after. **[ACTION: route to OGC / the Ansys
account contact.]**

---

## 9. Corpus version alignment

**This is a real defect in the current build, and the reviewer has identified it
correctly.**

- **The index is built from Ansys 2026 R1 (v261) documentation**
  (`chatbot_spike/config.py:DOCS_DIR = .../ProductDocPDF/v261`; two source PDFs are even
  named `..._2026_R1.pdf`).
- **The lab targets Ansys 2025 R2.** The project pins to it, the tutorial authoring guide
  requires UIA selectors be verified against 2025 R2 (`mock_server/data/README.md`), and
  the student-facing README instructs students to open Workbench 2025 R2.

So Compass is answering from documentation **one release newer** than what is installed
in RH217. We agree with the reviewer that this is not cosmetic: menu paths, defaults and
workflow steps move between Ansys releases, and a confidently-worded answer citing a v261
page for a 2025 R2 UI is exactly the failure that wastes a student's lab period or
teaches them something wrong.

*Remediation — we consider this a pilot blocker:* re-run `ingest.py` with
`ANSYS_DOCS_DIR` pointed at the **v251** documentation set, rebuild the index, and add
the release to the citation string so students see "Mechanical User's Guide, 2025 R2,
p. 218". Alternatively, confirm the lab is upgrading to 2026 R1 and re-pin everything
else. Either way the two must match before students use it.

**[CONFIRM: which Ansys release is actually installed in RH217 for Fall 2026?]**

---

## 10. Evaluation

**a/b. What accuracy testing has been done?**

**No systematic accuracy evaluation has been performed, and there is no question set with
known-correct answers.** `chatbot_spike/README.md`'s "Findings" section is explicitly a
work in progress, with unfilled entries for retrieval quality, latency and citation
accuracy.

What exists is one documented retrieval comparison, which is a design justification and
not an accuracy measurement: for the query "How do I refine the mesh on a face?", hybrid
search surfaced pages titled "Refinement controls" and "Refine Surface Mesh", while
semantic-only search drifted to the adjacent "Inflation" feature. That validated the
hybrid-retrieval choice; it says nothing about end-to-end answer correctness.

The automated test suite (`tests/server/test_chatbot.py`) exercises the API contract —
consent gating, SSE framing, logging — against a fake engine. It does not test answer
quality.

One known retrieval defect is documented and unfixed: the Ansys per-page copyright footer
is chunked like body text and is occasionally retrieved as a top-5 hit, consuming a
context slot with boilerplate.

**c. What would constitute pilot failure?**

No thresholds have been defined. We propose adopting these before the pilot, and running
the evaluation against them:

| Metric | Definition | Proposed failure threshold |
|---|---|---|
| Grounding rate | Claims supported by a retrieved passage, human-scored | < 85% |
| Factual accuracy | Answer correct for the installed Ansys release | < 90% |
| Appropriate refusal | Abstains on out-of-corpus questions | < 80% |
| Harmful output | Any unsafe completion in the red-team set | > 0 |
| Latency (p95) | Time to full answer under lab load | > 120 s |

Method: a 50-question set drawn from real ME-UY 4214 lab friction points with
instructor-written reference answers, scored by the instructor. This is a modest amount
of work and we would rather do it than run the pilot without it.

---

## 11. Student-facing disclosure and consent

**a. What the consent gate actually says.** Verbatim, from
`webapp/src/pages/student/ChatPage.tsx:ConsentGate`:

> **Before you use Compass**
>
> Compass answers Ansys questions from locally indexed documentation — nothing leaves
> NYU's network. To help improve the course, your questions and Compass's answers are
> logged for your instructor, **under an anonymous session token, never your name or
> NetID**.
>
> You can withdraw consent any time; Compass simply stops working.
>
> [ I understand — enable Compass ]

Mechanically it is a real gate: `POST /api/chatbot/query` returns `403 consent_required`
until a `consents` row exists (`server/routers/chatbot.py`), and withdrawal deletes the
row and re-blocks the endpoint.

**b. Is the disclosure adequate?** Three gaps, conceded:

1. **It does not say the output may be wrong.** Nothing in the gate or the chat UI warns
   that Compass can be inaccurate. Given §9 (version mismatch) and §10 (no accuracy
   testing), that omission is not defensible.
2. **It does not say submissions are stored indefinitely.** "Logged for your instructor"
   is accurate but understates it; retention is unbounded (§4e).
3. **"Anonymous session token, never your name or NetID" is true of the log table but
   potentially misleading.** The instructor can join the token back to the username on
   their dashboard. A student could reasonably read "anonymous" as "the instructor can't
   tell it was me," which is not the case. The wording should say *pseudonymous* and
   state that the instructor can identify them.

*Remediation:* rewrite the gate to cover accuracy, retention and instructor
identifiability, and add a persistent "Compass can be wrong — verify against the
documentation" line in the chat UI. We would propose wording for the reviewer's approval
rather than choosing it unilaterally.

**c. Can a student decline and still complete the lab?**

**Yes, fully.** Consent gates the chatbot endpoint only. Tutorials, quizzes, report upload
and all progress tracking work identically without it — we verified that no other router
checks the `consents` table. The alternative is the ordinary lab path: the tutorial's own
instructions, the Ansys documentation, and asking the instructor or TA. Declining costs
the student nothing that is graded.

---

## 12. Change control on behavior

**a/b. Who can edit the system prompt or swap the model, and is it reviewed?**

The reviewer's concern is partly mitigated and partly accurate.

*Mitigated:* the student-facing system prompt is **source code**
(`chatbot_spike/generate.py:SYSTEM_PROMPT`), not a database row or an admin-panel field.
Editing it produces a git diff, and it reaches students only through `git pull` +
`docker compose up -d --build` on the host. There is no runtime prompt editing, and no UI
anywhere exposes it. The same holds for the model reference (`chatbot_spike/config.py`)
and the generation parameters.

*Accurate:* this is currently a single-maintainer repository with **no required pull
request review and no branch protection** — so a prompt edit produces a diff that, in
practice, no second person reads. And the model *tag* is not digest-pinned, so a
re-`pull` on the host could change the weights with no diff at all (§1b). Anyone with
shell access to the host can do both.

*One genuine unreviewed prompt surface we should disclose:*
`tutorials.report_guidelines` is instructor free text, edited through the web app, stored
unversioned in the database, and interpolated directly into the report-review prompt
(`report_verify.py:_review_report_with_llm`, capped at 4,000 chars). That is a
model-behavior change with no diff and no review. It is instructor-authored rather than
student-authored, so it is lower severity, but it is exactly the class of thing this
question is about.

*Remediation we propose:* require PR review for `chatbot_spike/` and `server/services/`,
digest-pin the model, and version `report_guidelines` with an audit trail.

---

## 13. Kill switches

Anyone with shell access to `meuy4214.poly.edu` (the `ay3140` account; NYU IT via root)
can take the system down in well under a minute. Graduated options:

| Scope | Command | Effect |
|---|---|---|
| Compass + all AI only | `docker stop tutoring-hub-ollama` | Every LLM path fails cleanly; tutorials, quizzes and reports keep working. Chat shows an error event, not a crash. |
| Whole application | `docker compose down` | Site offline; all data persists on disk. |
| Public access only | `docker stop tutoring-hub-nginx` | Site unreachable; app and data untouched. |

The graceful degradation is deliberate: `OllamaEngine` imports lazily and surfaces a
clean SSE `error` event, so killing the model server never takes down the courseware.

**Gap:** there is no in-product kill switch — an instructor without SSH cannot disable
Compass mid-lab. **[CONFIRM: who besides the maintainer holds host access during lab
periods?]** *Remediation:* an instructor-dashboard toggle the chatbot router checks. Small
change, and worth having for a live lab.

---

## 14. Concurrency limits

**a. How many students at once?**

Architecturally the hub handles a 30-student section comfortably — FastAPI with SQLite in
WAL mode, one connection per request. **But Compass and all LLM features are strictly
serialized: one student at a time.** `OllamaEngine.generate` holds a process-wide
`threading.Lock` for the entire generation (`server/services/chatbot_service.py`),
deliberately, because a single machine cannot run the embedding model and Ollama
concurrently at useful speed.

**b. Hardware, and what happens at saturation.**

The host is a **2-vCPU, 15 GB-RAM VM with no GPU**. Inference is CPU-only. This
contradicts the architecture document's "instructor desktop GPU" and the reviewer should
work from the real figure. Practical consequences, from our own notes and the UI we had
to build around them:

- A Compass answer takes **on the order of a minute or more**. The chat UI shows an
  elapsed-seconds counter and, after 15 seconds, the message "Answers can take a minute
  or two" — that copy exists because the wait is genuinely that long.
- Requests **queue** behind the lock. With 20 students asking questions in a 10-minute
  window, the last student waits many minutes. nginx allows 300 s per request; beyond
  that they receive a 504.
- `OLLAMA_KEEP_ALIVE=-1` holds the model resident (~3–4 GB of the 15 GB) to avoid tens of
  seconds of reload latency on each request.
- Memory saturation would mean the OOM killer terminating the Ollama container;
  `restart: unless-stopped` brings it back, and the LLM features degrade gracefully
  rather than taking the courseware down.

**We regard this as the most likely cause of pilot failure in practice** — not a security
failure, a usability one. It should be sized honestly before Fall 2026. Options: GPU
passthrough (needs the NVIDIA container toolkit and root), a smaller model, or accepting
Compass as a low-throughput aid rather than a live-lab tool.

**c. Rate limiting or max generation length?**

- **Rate limiting: none.** No per-user or per-IP limit anywhere in the server. The global
  lock bounds *throughput* but not *submission*; a student can queue unlimited questions.
  *Remediation: a per-token rate limit is a small change and we would recommend it.*
- **Max generation length: yes.** `num_predict = 220` tokens for Compass, 260 for report
  review. Input is capped at 2,000 characters per question.

---

## Summary: what we propose to change before the pilot

Blockers:

1. **Rebuild the retrieval index from Ansys 2025 R2 (v251) docs** to match RH217 (§9).
2. **Agree a student-disclosure escalation path** with the Wellness Exchange, or have the
   risk formally accepted in writing (§7c).
3. **Restore visible source citations** to students (§2d).
4. **Run the accuracy and red-team evaluation** against defined thresholds (§10, §7b).
5. **Decide the network posture and make the configuration match the claim** (§A2). The
   host is currently internet-facing; we recommend restricting inbound 443 to NYU ranges
   and moving to a DNS-01 certificate, which also fixes renewal — renewal will otherwise
   fail before ~2026-10-10, since the nginx container holds port 80.
6. **Obtain an OGC / Ansys determination** on serving documentation chunks (§8b).

Proposed pilot conditions:

7. Digest-pin the model; require review on prompt and model changes (§1b, §12).
8. Define and implement data retention (§4e).
9. Rewrite the consent gate for accuracy, retention and identifiability (§11b).
10. Add per-student rate limiting and an in-product kill switch (§14c, §13).
11. Add an answer-flagging control for students (§3c).
12. Size the concurrency reality honestly, or add a GPU (§14b).

---

## Items requiring confirmation before this response is sent

These cannot be answered from the code and need input from the course or host owner:

- [ ] §A1 — Is Compass mandatory or voluntary for Fall 2026?
- [ ] §A2/A3/A4 — Current firewall ruleset and any NYU perimeter ACL (box admin), to
      confirm our off-campus reachability observation authoritatively
- [ ] §A2 — Decision on network posture: restrict to NYU ranges, or accept internet-facing
- [ ] §1a — `ollama list` / `ollama show` output from the host, for the digest
- [ ] §3b — Named reviewer and cadence for retrospective output review
- [ ] §4c — Whether NYU-managed VM-level backup covers this host
- [ ] §4d — Whether the host volume is encrypted at rest
- [ ] §7a — Academic-integrity position, and who at Tandon reviews it
- [ ] §8b — Status of any Ansys / OGC contact
- [ ] §9 — Ansys release actually installed in RH217 for Fall 2026
- [ ] §13 — Who holds host access during lab periods
