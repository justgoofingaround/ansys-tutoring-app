/** Mirror of the backend contract (server/models.py). */

export interface Me {
  username: string;
  role: "instructor" | "student";
  section: string | null;
  opaque_token: string | null;
  chatbot_consent: boolean;
}

export interface Section {
  id: number;
  name: string;
  class_code: string;
  is_active: boolean;
  student_count: number;
}

export type TutorialStatus = "not_started" | "in_progress" | "completed";
export type StepStatus = "not_started" | "attempted" | "struggling" | "completed";

export interface QuizState {
  quiz_id: string;
  best_score: number | null;
  attempts: number;
}

export interface ReportState {
  ok: boolean;
  last_score: number;
  last_total: number;
  submitted_at: number;
}

export interface TutorialCardData {
  tutorial_id: string;
  title: string;
  product: string;
  is_mandatory: boolean;
  version: number;
  status: TutorialStatus;
  percent: number;
  steps_total: number;
  steps_completed: number;
  current_step_id: string | null;
  needs_report: boolean;
  report: ReportState | null;
  quiz: QuizState | null;
}

export interface DashboardData {
  tutorials: TutorialCardData[];
  continue: {
    tutorial_id: string;
    title: string;
    step_id: string | null;
    step_title: string | null;
  } | null;
}

export interface StepRow {
  step_id: string;
  title: string;
  app: string;
  status: StepStatus;
  fail_count: number;
  faq_count: number;
}

export interface ReportCheck {
  name: string;
  ok: boolean;
  severity: "error" | "warning";
  message: string;
}

export interface LlmReview {
  available: boolean;
  model: string | null;
  overall: string;
  strengths: string[];
  caveats: string[];
  suggestions: string[];
  confidence?: string;
}

export interface ReportResult {
  submission_id: number;
  ok: boolean;
  score: number;
  total: number;
  checks: ReportCheck[];
  feedback: string;
  llm_review: LlmReview | null;
  filename?: string;
  submitted_at?: number;
}

export interface TutorialDetailData {
  tutorial_id: string;
  title: string;
  version: number;
  product: string;
  is_mandatory: boolean;
  problem: string | null;
  expected_result: { value: number; tolerance: number; units: string } | null;
  status: TutorialStatus;
  percent: number;
  steps_total: number;
  steps_completed: number;
  sections: { section: string; app: string; steps: StepRow[] }[];
  needs_report: boolean;
  report: ReportState | null;
  report_guidelines: string | null;
  report_submissions: {
    submission_id: number;
    filename: string;
    ok: boolean;
    score: number;
    total: number;
    submitted_at: number;
  }[];
  quiz: QuizState | null;
}

export interface QuizQuestion {
  question_id: number;
  position: number;
  text: string;
  options: string[];
  concept_tag: string;
}

export interface QuizData {
  quiz_id: string;
  tutorial_id: string;
  title: string;
  questions: QuizQuestion[];
}

export interface QuizCheckResult {
  question_id: number;
  correct: boolean;
  correct_index: number;
  explanation: string;
}

export interface QuizSubmissionResult {
  quiz_id: string;
  tutorial_id: string;
  score: number;
  correct_count: number;
  total: number;
  attempt: number;
  per_question: {
    question_id: number;
    chosen_index: number;
    correct: boolean;
    correct_index: number;
    concept_tag: string;
    explanation: string;
  }[];
  by_concept: Record<string, { correct: number; total: number }>;
}

export interface Faq {
  faq_id: number;
  step_id: string | null;
  question: string;
  answer: string;
}

/* ── instructor ─────────────────────────────────────────────────────── */

export interface ProgressCell {
  status: TutorialStatus;
  percent: number;
  steps_completed: number;
  steps_total: number;
  report_ok: boolean;
  quiz_attempts: number | null;
  quiz_best: number | null;
}

export interface ProgressMatrix {
  tutorials: { tutorial_id: string; title: string; is_mandatory: boolean }[];
  students: {
    username: string;
    opaque_token: string;
    section: string | null;
    cells: Record<string, ProgressCell>;
  }[];
  tiles: {
    students: number;
    avg_completion: number;
    tutorials_completed: number;
    reports_passed: number;
    quiz_avg: number | null;
  };
}

export interface ActivityItem {
  kind: "event" | "report" | "quiz";
  detail: string;
  step_id: string | null;
  tutorial_id: string;
  tutorial_title: string;
  username: string;
  score: number | null;
  total: number | null;
  timestamp: number;
}

export interface QuizStats {
  quiz_id: string;
  title: string;
  tutorial_id: string;
  total_questions: number;
  students: number;
  attempts: number;
  avg_pct: number | null;
  histogram: { correct: number; count: number }[];
}

export interface QuizAnalytics {
  quiz_id: string;
  title: string;
  tutorial_id: string;
  first_attempt_students: number;
  questions: {
    question_id: number;
    position: number;
    text: string;
    concept_tag: string;
    correct_index: number;
    options: string[];
    attempts: number;
    correct_pct: number | null;
  }[];
  concepts: { tag: string; correct: number; total: number; pct: number | null }[];
}

export interface FaqCandidate {
  id: number;
  tutorial_id: string;
  step_id: string;
  failed_check: string;
  distinct_students: number;
  cohort_size: number;
  failure_rate: number;
  status: "candidate" | "drafted" | "approved" | "rejected";
  draft_question: string | null;
  draft_answer: string | null;
  draft_model: string | null;
  step_title: string | null;
  step_description: string | null;
  step_hints: string[];
}

export interface PublishedFaq {
  faq_id: number;
  tutorial_id: string;
  step_id: string | null;
  question: string;
  answer: string;
  created_at: number;
}

export interface ValidationFinding {
  severity: "error" | "warning";
  where: string;
  message: string;
}

export interface LibraryTutorial {
  tutorial_id: string;
  title: string;
  product: string;
  is_mandatory: boolean;
  quiz_id: string | null;
  published_version: number | null;
  is_archived: boolean;
  report_guidelines: string | null;
  versions: { version: number; uploaded_at: number; warnings: ValidationFinding[] }[];
}

/** Raw tutorial JSON as served by GET /api/tutorials/{id} (authored fields). */
export interface TutorialContentStep {
  step_id: string;
  app: string;
  title: string;
  description: string;
  hints?: string[];
  source_image?: string | null;
}

export interface TutorialContent {
  tutorial_id: string;
  title: string;
  runtime_steps?: string[];
  sections: { section: string; app?: string; steps: TutorialContentStep[] }[];
  _meta: { version: number; product: string; is_mandatory: boolean; quiz_id: string | null };
}
