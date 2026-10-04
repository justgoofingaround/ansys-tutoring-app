-- ME-UY 4214 Tutoring Hub — SQLite schema.
-- FERPA invariant: every analytics-bearing table (action_events, quiz_submissions,
-- report_submissions, chatbot_queries) carries ONLY the opaque session token.
-- The username<->token join lives in `users` and is performed exclusively inside
-- instructor-dashboard queries; exports select from the event tables verbatim.

PRAGMA journal_mode = WAL;

CREATE TABLE IF NOT EXISTS sections (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    class_code  TEXT NOT NULL UNIQUE,
    is_active   INTEGER NOT NULL DEFAULT 1,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id                INTEGER PRIMARY KEY,
    username          TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash     TEXT NOT NULL,
    role              TEXT NOT NULL CHECK (role IN ('instructor', 'student')),
    section_id        INTEGER REFERENCES sections(id),
    opaque_token      TEXT UNIQUE,          -- 'student_a4f9c2'; NULL for instructors
    is_active         INTEGER NOT NULL DEFAULT 1,
    created_at        REAL NOT NULL,
    -- Students sign in with their NYU address; `username` stays the DISPLAY
    -- name (seeded from the roster's full_name) so instructor dashboards keep
    -- showing a human name. NULL for instructors and for accounts created
    -- under the retired class-code flow, which still sign in by username.
    email             TEXT UNIQUE COLLATE NOCASE,
    email_verified_at REAL,
    -- NULL when the student opened the emailed link themselves; set to the
    -- instructor's id when they vouched for the account instead, so a
    -- disputed account shows who admitted it.
    email_verified_by INTEGER REFERENCES users(id)
);

-- Enrolment is the thing that grants access: a student can only register if
-- their address is on a section's roster, and each row can be claimed once.
CREATE TABLE IF NOT EXISTS roster_entries (
    id                INTEGER PRIMARY KEY,
    section_id        INTEGER NOT NULL REFERENCES sections(id),
    email             TEXT NOT NULL UNIQUE COLLATE NOCASE,
    netid             TEXT NOT NULL DEFAULT '',
    full_name         TEXT NOT NULL DEFAULT '',
    claimed_by_user_id INTEGER REFERENCES users(id),
    added_by          INTEGER REFERENCES users(id),
    added_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_roster_section ON roster_entries (section_id);

-- One-time registration confirmation links. Same shape as `sessions`: only the
-- sha256 of the token is stored, so the database never holds a usable link.
CREATE TABLE IF NOT EXISTS email_verifications (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_email_verifications_user ON email_verifications (user_id);

-- Password reset links. Same single-use, hash-only discipline as above; kept in
-- its own table so a reset link can never be replayed as a confirmation link.
CREATE TABLE IF NOT EXISTS password_resets (
    token_hash  TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    used        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_password_resets_user ON password_resets (user_id);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash  TEXT PRIMARY KEY,           -- sha256 of the cookie value
    user_id     INTEGER NOT NULL REFERENCES users(id),
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL,
    revoked     INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS consents (
    user_id     INTEGER NOT NULL REFERENCES users(id),
    kind        TEXT NOT NULL,              -- 'chatbot'
    granted_at  REAL NOT NULL,
    PRIMARY KEY (user_id, kind)
);

CREATE TABLE IF NOT EXISTS tutorials (
    tutorial_id              TEXT PRIMARY KEY,
    title                    TEXT NOT NULL,
    product                  TEXT NOT NULL DEFAULT 'mechanical',
    is_mandatory             INTEGER NOT NULL DEFAULT 0,
    quiz_id                  TEXT,
    latest_published_version INTEGER,
    is_archived              INTEGER NOT NULL DEFAULT 0,
    report_guidelines        TEXT,    -- instructor's free-text report criteria
    created_at               REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tutorial_versions (
    id                  INTEGER PRIMARY KEY,
    tutorial_id         TEXT NOT NULL REFERENCES tutorials(tutorial_id),
    version             INTEGER NOT NULL,
    content             TEXT NOT NULL,      -- full tutorial JSON, immutable
    file_path           TEXT NOT NULL,
    validation_findings TEXT NOT NULL DEFAULT '[]',
    uploaded_by         INTEGER REFERENCES users(id),
    uploaded_at         REAL NOT NULL,
    UNIQUE (tutorial_id, version)
);

CREATE TABLE IF NOT EXISTS quizzes (
    quiz_id      TEXT PRIMARY KEY,
    tutorial_id  TEXT NOT NULL REFERENCES tutorials(tutorial_id),
    title        TEXT NOT NULL,
    is_published INTEGER NOT NULL DEFAULT 0,
    updated_at   REAL NOT NULL,
    -- Set once a quiz has been edited in the web app. Quizzes are unversioned
    -- and re-imported from mock_server/data/quizzes/ on every boot; without
    -- this flag a restart would silently discard the instructor's edits.
    edited_in_app INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS quiz_questions (
    id           INTEGER PRIMARY KEY,
    quiz_id      TEXT NOT NULL REFERENCES quizzes(quiz_id),
    position     INTEGER NOT NULL,
    text         TEXT NOT NULL,
    options      TEXT NOT NULL,             -- JSON array of strings
    correct_index INTEGER NOT NULL,
    concept_tag  TEXT NOT NULL DEFAULT '',
    explanation  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS quiz_submissions (
    id            INTEGER PRIMARY KEY,
    quiz_id       TEXT NOT NULL,
    tutorial_id   TEXT NOT NULL,
    session_token TEXT NOT NULL,            -- opaque token, NEVER a username
    answers       TEXT NOT NULL,            -- JSON array of ints
    score         REAL NOT NULL,            -- 0.0-1.0, server-graded
    client_score  REAL,
    attempt       INTEGER NOT NULL,
    submitted_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quiz_submissions_token ON quiz_submissions (session_token, quiz_id);

CREATE TABLE IF NOT EXISTS action_events (
    id                INTEGER PRIMARY KEY,
    session_token     TEXT NOT NULL,
    tutorial_id       TEXT NOT NULL,
    step_id           TEXT NOT NULL,
    action_type       TEXT NOT NULL,
    uia_automation_id TEXT NOT NULL DEFAULT '',
    timestamp         REAL NOT NULL,
    extra             TEXT NOT NULL DEFAULT '{}',
    received_at       REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_events_token ON action_events (session_token, tutorial_id);
CREATE INDEX IF NOT EXISTS idx_action_events_step ON action_events (tutorial_id, step_id, action_type);

CREATE TABLE IF NOT EXISTS report_submissions (
    id               INTEGER PRIMARY KEY,
    session_token    TEXT NOT NULL,
    tutorial_id      TEXT NOT NULL,
    tutorial_version INTEGER,
    filename         TEXT NOT NULL,
    stored_path      TEXT NOT NULL,
    ok               INTEGER NOT NULL,
    score            INTEGER NOT NULL,
    total            INTEGER NOT NULL,
    checks           TEXT NOT NULL DEFAULT '[]',
    feedback         TEXT NOT NULL DEFAULT '',
    llm_review       TEXT,
    submitted_at     REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_submissions_token ON report_submissions (session_token, tutorial_id);

CREATE TABLE IF NOT EXISTS chatbot_queries (
    id            INTEGER PRIMARY KEY,
    session_token TEXT NOT NULL,
    tutorial_id   TEXT,
    step_id       TEXT,
    question      TEXT NOT NULL,
    answer        TEXT NOT NULL DEFAULT '',
    sources       TEXT NOT NULL DEFAULT '[]',
    model         TEXT NOT NULL DEFAULT '',
    duration_ms   INTEGER,
    created_at    REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS faq_candidates (
    id                INTEGER PRIMARY KEY,
    tutorial_id       TEXT NOT NULL,
    step_id           TEXT NOT NULL,
    failed_check      TEXT NOT NULL,
    distinct_students INTEGER NOT NULL DEFAULT 0,
    cohort_size       INTEGER NOT NULL DEFAULT 0,
    failure_rate      REAL NOT NULL DEFAULT 0,
    status            TEXT NOT NULL DEFAULT 'candidate'
                      CHECK (status IN ('candidate', 'drafted', 'approved', 'rejected')),
    draft_question    TEXT,
    draft_answer      TEXT,
    draft_model       TEXT,
    drafted_at        REAL,
    reviewed_by       INTEGER REFERENCES users(id),
    reviewed_at       REAL,
    published_faq_id  INTEGER,
    UNIQUE (tutorial_id, step_id, failed_check)
);

CREATE TABLE IF NOT EXISTS faqs (
    id                  INTEGER PRIMARY KEY,
    tutorial_id         TEXT NOT NULL,
    step_id             TEXT,               -- NULL = tutorial-level FAQ
    question            TEXT NOT NULL,
    answer              TEXT NOT NULL,
    source_candidate_id INTEGER,
    is_published        INTEGER NOT NULL DEFAULT 1,
    created_by          INTEGER REFERENCES users(id),
    created_at          REAL NOT NULL,
    updated_at          REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_faqs_tutorial ON faqs (tutorial_id, step_id);
