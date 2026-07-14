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
