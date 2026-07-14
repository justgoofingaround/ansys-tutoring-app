import { useRef, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, Check, ChevronDown, Copy, FileUp, ListChecks, MonitorPlay, Play, X,
} from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { Faq, ReportResult, StepRow, TutorialDetailData } from "@/types/api";
import { useMe } from "@/auth/useMe";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ProgressBar } from "@/components/ProgressBar";
import { StatusDot } from "@/components/StatusDot";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

/* ── steps ──────────────────────────────────────────────────────────── */

function StepFaqs({ tutorialId, stepId }: { tutorialId: string; stepId: string }) {
  const { data, isPending } = useQuery({
    queryKey: ["student", "faqs", tutorialId, stepId],
    queryFn: () => apiFetch<Faq[]>(`/api/tutorials/${tutorialId}/steps/${stepId}/faqs`),
  });
  if (isPending) return <Spinner className="my-2 size-4" />;
  return (
    <div className="mb-2 ml-8 space-y-2">
      {(data ?? []).map((f) => (
        <div key={f.faq_id} className="rounded-(--radius-control) border border-hairline bg-paper p-3">
          <div className="text-sm font-medium text-ink">{f.question}</div>
          <div className="mt-1 text-sm text-ink-soft">{f.answer}</div>
        </div>
      ))}
    </div>
  );
}

function StepLine({ step, tutorialId }: { step: StepRow; tutorialId: string }) {
  const [faqsOpen, setFaqsOpen] = useState(false);
  return (
    <li className="border-b border-hairline last:border-b-0">
      <div className="flex items-center gap-3 py-2.5">
        <StatusDot status={step.status} />
        <code className="w-44 shrink-0 truncate font-mono text-[13px] text-ink-faint">
          {step.step_id}
        </code>
        <span className="min-w-0 flex-1 truncate text-[15px] text-ink">{step.title}</span>
        <Badge className="hidden sm:inline-flex">{step.app}</Badge>
        {step.faq_count > 0 && (
          <button
            onClick={() => setFaqsOpen(!faqsOpen)}
            className="inline-flex items-center gap-1 rounded-full border border-warning/30 bg-warning-tint px-2 py-0.5 text-xs font-medium text-warning"
          >
            {step.faq_count} common issue{step.faq_count > 1 ? "s" : ""}
            <ChevronDown className={cn("size-3 transition-transform", faqsOpen && "rotate-180")} />
          </button>
        )}
      </div>
      {faqsOpen && <StepFaqs tutorialId={tutorialId} stepId={step.step_id} />}
    </li>
  );
}

/* ── launch guide ───────────────────────────────────────────────────── */

function LaunchGuideCard({ tutorialId }: { tutorialId: string }) {
  const { data: me } = useMe();
  const [copied, setCopied] = useState<string | null>(null);
  const command = `python spikes\\guide_tut1.py ${tutorialId}`;

  function copy(text: string, key: string) {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(key);
      setTimeout(() => setCopied(null), 1500);
    });
  }

  return (
    <Card>
      <div className="flex items-center gap-2">
        <MonitorPlay className="size-5 text-violet" />
        <CardTitle>Guided walkthrough</CardTitle>
      </div>
      <p className="mt-2 text-sm text-ink-soft">
        The desktop guide overlays Ansys itself, highlighting exactly what to click.
        With Ansys Workbench open:
      </p>
      <div className="mt-3 flex gap-2">
        <a
          href={`ansysguide://${tutorialId}`}
          className="inline-flex h-10 flex-1 items-center justify-center gap-2 rounded-(--radius-control) bg-violet px-4 text-[15px] font-medium text-white transition-colors hover:bg-violet-hover"
        >
          <MonitorPlay className="size-4" />
          Launch desktop guide
        </a>
        <a
          href="ansysguide://close"
          title="Close the guide running on this PC"
          className="inline-flex h-10 items-center justify-center gap-1.5 rounded-(--radius-control) border border-hairline bg-paper px-3 text-sm font-medium text-ink-soft transition-colors hover:border-ink-faint hover:text-ink"
        >
          <X className="size-4" />
          Close
        </a>
      </div>
      <p className="mt-1.5 text-[13px] leading-snug text-ink-faint">
        Your browser will ask permission the first time. Nothing happening? The lab
        setup script (<code className="font-mono">register_guide_protocol.py</code>)
        hasn't been run on this PC — start it manually instead:
      </p>
      <button
        onClick={() => copy(command, "cmd")}
        className="mt-2 flex w-full items-center justify-between gap-2 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 text-left font-mono text-[13px] text-ink hover:border-ink-faint"
        title="Copy"
      >
        <span className="truncate">{command}</span>
        {copied === "cmd" ? <Check className="size-4 text-success" /> : <Copy className="size-4 text-ink-faint" />}
      </button>
      {me?.opaque_token && (
        <>
          <p className="mt-3 text-sm text-ink-soft">Your anonymous session token (for pairing):</p>
          <button
            onClick={() => copy(me.opaque_token!, "tok")}
            className="mt-1 flex w-full items-center justify-between gap-2 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 text-left font-mono text-[13px] text-ink hover:border-ink-faint"
            title="Copy"
          >
            <span>{me.opaque_token}</span>
            {copied === "tok" ? <Check className="size-4 text-success" /> : <Copy className="size-4 text-ink-faint" />}
          </button>
        </>
      )}
    </Card>
  );
}

/* ── quiz entry gate ────────────────────────────────────────────────── */

function QuizCard({ detail }: { detail: TutorialDetailData }) {
  const quiz = detail.quiz;
  if (!quiz) return null;
  const attempted = quiz.attempts > 0;
  const best = quiz.best_score !== null ? Math.round(quiz.best_score * 100) : null;
  const stepsDone = detail.steps_completed === detail.steps_total;
  return (
    <Card>
      <div className="flex items-center gap-2">
        <ListChecks className="size-5 text-violet" />
        <CardTitle>Check your understanding</CardTitle>
      </div>
      {attempted ? (
        <div className="mt-2 flex items-baseline gap-2">
          <span className="font-serif text-3xl font-semibold text-ink">{best}%</span>
          <span className="text-sm text-ink-soft">
            best of {quiz.attempts} attempt{quiz.attempts > 1 ? "s" : ""}
          </span>
        </div>
      ) : (
        <p className="mt-2 text-sm text-ink-soft">
          A short quiz on the concepts behind this tutorial. It counts toward
          completing the tutorial, and you can retake it.
        </p>
      )}
      {!attempted && !stepsDone && (
        <p className="mt-1.5 text-[13px] text-ink-faint">
          Tip: finish the steps first — the questions assume you've run the analysis.
        </p>
      )}
      <Link
        to={`/tutorials/${detail.tutorial_id}/quiz`}
        className={cn(
          "mt-3 inline-flex h-10 w-full items-center justify-center gap-2 rounded-(--radius-control) px-4 text-[15px] font-medium transition-colors",
          attempted
            ? "border border-hairline bg-surface text-ink hover:border-ink-faint"
            : "bg-violet text-white hover:bg-violet-hover",
        )}
      >
        <ListChecks className="size-4" />
        {attempted ? "Retake quiz" : "Take the quiz"}
      </Link>
    </Card>
  );
}

/* ── report upload + rubric feedback ────────────────────────────────── */

function RubricFeedback({ result }: { result: ReportResult }) {
  const errors = result.checks.filter((c) => c.severity !== "warning");
  const warnings = result.checks.filter((c) => c.severity === "warning");
  return (
    <div className="mt-4 space-y-3">
      <div
        className={cn(
          "rounded-(--radius-control) border px-3 py-2 text-[15px] font-semibold",
          result.ok
            ? "border-success/30 bg-success-tint text-success"
            : "border-warning/30 bg-warning-tint text-warning",
        )}
      >
        {result.ok ? "Report verified" : "Report needs fixes"}{" "}
        <span className="font-mono">
          {result.score}/{result.total}
        </span>
      </div>
      <ul className="space-y-1.5">
        {[...errors, ...warnings].map((c) => (
          <li key={c.name} className="flex items-start gap-2 text-sm">
            {c.ok ? (
              <Check className="mt-0.5 size-4 shrink-0 text-success" strokeWidth={3} />
            ) : (
              <X
                className={cn(
                  "mt-0.5 size-4 shrink-0",
                  c.severity === "warning" ? "text-warning" : "text-error",
                )}
                strokeWidth={3}
              />
            )}
            <span className={c.ok ? "text-ink-soft" : "text-ink"}>{c.message}</span>
          </li>
        ))}
      </ul>
      {result.llm_review?.available && (
        <div className="border-l-2 border-hairline pl-3 text-sm text-ink-soft">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Feedback (AI-generated — the rubric above is authoritative)
          </div>
          <p>{result.llm_review.overall}</p>
          {result.llm_review.suggestions.length > 0 && (
            <ul className="mt-1 list-disc pl-4">
              {result.llm_review.suggestions.map((s, i) => (
                <li key={i}>{s}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function ReportUploadCard({ detail }: { detail: TutorialDetailData }) {
  const qc = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragOver, setDragOver] = useState(false);
  const [result, setResult] = useState<ReportResult | null>(null);

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const res = await fetch(`/api/tutorials/${detail.tutorial_id}/report`, {
        method: "POST",
        body: form,
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
      });
      if (!res.ok) {
        let code = `http_${res.status}`;
        try {
          const body = await res.json();
          if (typeof body.detail === "string") code = body.detail;
        } catch { /* ignore */ }
        throw new ApiError(res.status, code);
      }
      return (await res.json()) as ReportResult;
    },
    onSuccess: (r) => {
      setResult(r);
      qc.invalidateQueries({ queryKey: ["student"] });
    },
  });

  function onFiles(files: FileList | null) {
    const file = files?.[0];
    if (file) upload.mutate(file);
  }

  return (
    <Card>
      <div className="flex items-center gap-2">
        <FileUp className="size-5 text-violet" />
        <CardTitle>Report check</CardTitle>
        {detail.report?.ok && <Badge tone="success">Passed</Badge>}
      </div>
      <p className="mt-2 text-sm text-ink-soft">
        Upload the report you generated from Mechanical (.html, .docx, .pdf…). It's graded
        against the tutorial rubric.
      </p>
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={(e) => { e.preventDefault(); setDragOver(false); onFiles(e.dataTransfer.files); }}
        className={cn(
          "mt-3 flex flex-col items-center gap-2 rounded-(--radius-control) border border-dashed p-5 text-center transition-colors",
          dragOver ? "border-violet bg-violet-tint" : "border-hairline",
        )}
      >
        {upload.isPending ? (
          <>
            <Spinner />
            <span className="text-sm text-ink-soft">Analyzing your report…</span>
          </>
        ) : (
          <>
            <span className="text-sm text-ink-soft">Drop your report here, or</span>
            <Button variant="secondary" onClick={() => inputRef.current?.click()}>
              Choose file
            </Button>
            <input
              ref={inputRef}
              type="file"
              accept=".docx,.pdf,.html,.htm,.txt,.md,.markdown,.json"
              className="hidden"
              onChange={(e) => onFiles(e.target.files)}
            />
          </>
        )}
      </div>
      {upload.isError && (
        <p className="mt-2 text-sm text-error">
          {upload.error instanceof ApiError && upload.error.code === "unsupported_report_format"
            ? "That file type isn't supported."
            : upload.error instanceof ApiError && upload.error.code === "report_too_large"
              ? "That file is too large (max 20 MB)."
              : "Upload failed — try again."}
        </p>
      )}
      {result && <RubricFeedback result={result} />}
      {detail.report_submissions.length > 0 && (
        <div className="mt-4 border-t border-hairline pt-3">
          <div className="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-faint">
            Previous submissions
          </div>
          <ul className="space-y-1">
            {detail.report_submissions.map((s) => (
              <li key={s.submission_id} className="flex items-center gap-2 text-sm">
                {s.ok ? (
                  <Check className="size-3.5 text-success" strokeWidth={3} />
                ) : (
                  <X className="size-3.5 text-error" strokeWidth={3} />
                )}
                <span className="truncate text-ink-soft">{s.filename}</span>
                <span className="ml-auto font-mono text-xs text-ink-faint">
                  {s.score}/{s.total} · {new Date(s.submitted_at * 1000).toLocaleDateString()}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

/* ── page ───────────────────────────────────────────────────────────── */

export function TutorialDetailPage() {
  const { tutorialId = "" } = useParams();
  const { data: detail, isPending, isError, refetch } = useQuery({
    queryKey: ["student", "tutorial", tutorialId],
    queryFn: () => apiFetch<TutorialDetailData>(`/api/student/tutorials/${tutorialId}`),
  });

  if (isPending) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }
  if (isError || !detail) {
    return (
      <Card className="text-center">
        <p className="text-ink-soft">Couldn't load this tutorial.</p>
        <button onClick={() => refetch()} className="mt-2 font-medium text-violet">
          Try again
        </button>
      </Card>
    );
  }

  return (
    <>
      <Link
        to="/dashboard"
        className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-ink-soft hover:text-ink"
      >
        <ArrowLeft className="size-4" /> Dashboard
      </Link>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h1 className="font-serif text-[28px] font-semibold leading-tight text-ink">
              {detail.title}
            </h1>
            {detail.is_mandatory ? <Badge tone="violet">Mandatory</Badge> : <Badge>Optional</Badge>}
            <Badge className="font-mono">v{detail.version}</Badge>
          </div>
          <div className="mt-3 w-full max-w-xl min-w-72">
            <ProgressBar total={detail.steps_total} completed={detail.steps_completed} />
            <div className="mt-1 text-sm text-ink-soft">
              {detail.steps_completed}/{detail.steps_total} steps · {detail.percent}% complete
            </div>
          </div>
        </div>
        <Link
          to={`/tutorials/${detail.tutorial_id}/run`}
          className="inline-flex h-10 items-center gap-2 rounded-(--radius-control) bg-violet px-4 text-[15px] font-medium text-white transition-colors hover:bg-violet-hover"
        >
          <Play className="size-4" />
          {detail.status === "not_started" ? "Run tutorial" : "Continue tutorial"}
        </Link>
      </div>

      <div className="grid gap-4 lg:grid-cols-[1fr_360px]">
        <div className="min-w-0 space-y-4">
          {detail.problem && (
            <Card>
              <CardTitle>Problem</CardTitle>
              <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">{detail.problem}</p>
              {detail.expected_result && (
                <p className="mt-3 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 font-mono text-sm text-ink">
                  Target: ≈ {detail.expected_result.value} {detail.expected_result.units} ±{" "}
                  {detail.expected_result.tolerance}
                </p>
              )}
            </Card>
          )}

          <Card>
            <CardTitle>Steps</CardTitle>
            <div className="mt-2 space-y-4">
              {detail.sections.map((sec) => (
                <div key={sec.section}>
                  <div className="mb-1 flex items-center gap-2">
                    <span className="text-sm font-semibold text-ink">{sec.section}</span>
                    <Badge>{sec.app}</Badge>
                  </div>
                  <ul>
                    {sec.steps.map((st) => (
                      <StepLine key={st.step_id} step={st} tutorialId={detail.tutorial_id} />
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          </Card>
        </div>

        <div className="space-y-4">
          <LaunchGuideCard tutorialId={detail.tutorial_id} />
          <QuizCard detail={detail} />
          {detail.needs_report && <ReportUploadCard detail={detail} />}
        </div>
      </div>
    </>
  );
}
