import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CheckCircle2, FileUp, GraduationCap } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { QuizAnalytics, QuizStats, ValidationFinding } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";
import { FindingsList } from "./TutorialLibraryPage";

function pctTone(pct: number | null): string {
  if (pct === null) return "bg-hairline";
  if (pct < 50) return "bg-error";
  if (pct < 75) return "bg-warning";
  return "bg-success";
}

function Bar({ pct }: { pct: number | null }) {
  return (
    <div className="h-2 flex-1 overflow-hidden rounded-full bg-hairline">
      <div
        className={cn("h-full rounded-full", pctTone(pct))}
        style={{ width: `${pct ?? 0}%` }}
      />
    </div>
  );
}

function QuizAnalyticsCard({ quizId }: { quizId: string }) {
  const { data: a, isPending } = useQuery({
    queryKey: ["instructor", "quiz-analytics", quizId],
    queryFn: () => apiFetch<QuizAnalytics>(`/api/instructor/quizzes/${quizId}/analytics`),
  });
  const [openQ, setOpenQ] = useState<number | null>(null);

  if (isPending || !a) return <Spinner className="mx-auto my-10 size-6" />;

  const hardestFirst = [...a.questions].sort(
    (x, y) => (x.correct_pct ?? 101) - (y.correct_pct ?? 101),
  );

  return (
    <div className="grid items-start gap-4 xl:grid-cols-[1fr_380px]">
      <Card>
        <CardTitle>Question difficulty</CardTitle>
        <p className="mt-1 text-[13px] text-ink-faint">
          % correct on each student's first attempt ({a.first_attempt_students} student
          {a.first_attempt_students === 1 ? "" : "s"}) — hardest first. Click a question to
          see its options.
        </p>
        {a.first_attempt_students === 0 ? (
          <p className="py-4 text-[15px] text-ink-faint">No submissions yet.</p>
        ) : (
          <ul className="mt-3 space-y-3">
            {hardestFirst.map((q) => (
              <li key={q.question_id}>
                <button
                  className="w-full text-left"
                  onClick={() => setOpenQ(openQ === q.question_id ? null : q.question_id)}
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm text-ink">
                      <span className="font-mono text-ink-faint">Q{q.position}</span> {q.text}
                    </span>
                    <span className="shrink-0 font-mono text-sm text-ink">
                      {q.correct_pct != null ? `${q.correct_pct}%` : "—"}
                    </span>
                  </div>
                  <div className="mt-1.5 flex items-center gap-2">
                    <Bar pct={q.correct_pct} />
                    <Badge className="font-mono text-[11px]">{q.concept_tag}</Badge>
                  </div>
                </button>
                {openQ === q.question_id && (
                  <ul className="mt-2 space-y-1 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2">
                    {q.options.map((opt, i) => (
                      <li key={i} className="flex items-center gap-2 text-[13px]">
                        {i === q.correct_index ? (
                          <Check className="size-3.5 shrink-0 text-success" />
                        ) : (
                          <span className="size-3.5 shrink-0" />
                        )}
                        <span className={i === q.correct_index ? "text-ink" : "text-ink-soft"}>
                          {opt}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card>
        <CardTitle>Concept mastery</CardTitle>
        <p className="mt-1 text-[13px] text-ink-faint">
          First-attempt accuracy pooled across each concept's questions.
        </p>
        <div className="mt-3 space-y-3">
          {a.concepts.map((c) => (
            <div key={c.tag}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="font-mono text-[13px] text-ink">{c.tag}</span>
                <span className="text-[13px] text-ink-soft">
                  {c.pct != null ? `${c.pct}%` : "—"} ({c.correct}/{c.total})
                </span>
              </div>
              <Bar pct={c.pct} />
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

/* ── quiz upload ────────────────────────────────────────────────────── */

interface QuizUploadResult {
  quiz_id: string;
  tutorial_id: string;
  questions: number;
  replaced: boolean;
  warnings: ValidationFinding[];
}

function QuizUploadCard() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [fileName, setFileName] = useState<string | null>(null);
  const [findings, setFindings] = useState<ValidationFinding[] | null>(null);
  const [uploaded, setUploaded] = useState<QuizUploadResult | null>(null);

  const upload = useMutation({
    mutationFn: async () => {
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("no file");
      const form = new FormData();
      form.append("file", file);
      const res = await fetch("/api/instructor/quizzes", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        body: form,
      });
      if (res.status === 422) {
        const body = await res.json();
        setFindings(body.detail.findings as ValidationFinding[]);
        setUploaded(null);
        throw new ApiError(422, "validation_failed");
      }
      if (!res.ok) throw new ApiError(res.status, `http_${res.status}`);
      return (await res.json()) as QuizUploadResult;
    },
    onSuccess: (r) => {
      setFindings(r.warnings.length > 0 ? r.warnings : null);
      setUploaded(r);
      setFileName(null);
      if (fileRef.current) fileRef.current.value = "";
      qc.invalidateQueries({ queryKey: ["instructor", "quiz-stats"] });
      qc.invalidateQueries({ queryKey: ["instructor", "quiz-analytics"] });
    },
  });

  return (
    <Card className="mb-4">
      <div className="flex items-center gap-2">
        <FileUp className="size-5 text-violet" />
        <CardTitle>Upload a quiz</CardTitle>
      </div>
      <p className="mt-2 text-sm text-ink-soft">
        A quiz is one JSON file attached to an existing tutorial — start from{" "}
        <code className="font-mono text-[13px]">mock_server/data/quizzes/_template.json</code>{" "}
        (a full real example is <code className="font-mono text-[13px]">tut1_3d_bar.json</code>).
        Re-uploading the same <code className="font-mono text-[13px]">quiz_id</code> replaces its
        questions; uploads publish immediately.
      </p>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <label className="flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-(--radius-control) border border-dashed border-ink-faint bg-paper px-4 py-4 text-sm text-ink-soft hover:border-violet hover:text-ink">
          <FileUp className="size-4" />
          {fileName ?? "Choose a .json file…"}
          <input
            ref={fileRef}
            type="file"
            accept=".json,application/json"
            className="hidden"
            onChange={(e) => {
              setFileName(e.target.files?.[0]?.name ?? null);
              setFindings(null);
              setUploaded(null);
            }}
          />
        </label>
        <Button disabled={!fileName} loading={upload.isPending} onClick={() => upload.mutate()}>
          Validate &amp; upload
        </Button>
      </div>
      {findings && (
        <div
          className={cn(
            "mt-3 rounded-(--radius-control) border px-4 py-3",
            uploaded ? "border-warning/40 bg-warning-tint" : "border-error/40 bg-error-tint",
          )}
        >
          <div className={cn("text-sm font-semibold", uploaded ? "text-warning" : "text-error")}>
            {uploaded ? "Uploaded with warnings" : "Validation failed — nothing was stored"}
          </div>
          <FindingsList findings={findings} />
        </div>
      )}
      {uploaded && (
        <div className="mt-3 flex items-center gap-2 rounded-(--radius-control) border border-success/40 bg-success-tint px-4 py-3 text-sm text-ink">
          <CheckCircle2 className="size-4 shrink-0 text-success" />
          <span>
            {uploaded.replaced ? "Replaced" : "Published"}{" "}
            <code className="font-mono">{uploaded.quiz_id}</code> ({uploaded.questions} question
            {uploaded.questions === 1 ? "" : "s"}) on{" "}
            <code className="font-mono">{uploaded.tutorial_id}</code> — live for students now.
          </span>
        </div>
      )}
    </Card>
  );
}

export function QuizzesPage() {
  const { data: quizzes, isPending } = useQuery({
    queryKey: ["instructor", "quiz-stats"],
    queryFn: () => apiFetch<QuizStats[]>("/api/instructor/quiz-stats"),
  });
  const [selected, setSelected] = useState<string | null>(null);
  const active = selected ?? quizzes?.[0]?.quiz_id ?? null;

  return (
    <>
      <PageHeader
        title="Quizzes"
        subtitle="Upload JSON-authored quizzes; review question difficulty and concept mastery."
      />
      <QuizUploadCard />
      {isPending ? (
        <div className="flex justify-center py-16">
          <Spinner className="size-6" />
        </div>
      ) : !quizzes || quizzes.length === 0 ? (
        <Card>
          <p className="py-4 text-[15px] text-ink-faint">
            No published quizzes. Add a JSON file under{" "}
            <code className="font-mono">mock_server/data/quizzes/</code> and restart the server.
          </p>
        </Card>
      ) : (
        <>
          <div className="mb-4 flex flex-wrap gap-2">
            {quizzes.map((q) => (
              <button
                key={q.quiz_id}
                onClick={() => setSelected(q.quiz_id)}
                className={cn(
                  "flex items-center gap-2 rounded-(--radius-control) border px-3 py-2 text-sm transition-colors",
                  active === q.quiz_id
                    ? "border-violet bg-violet-tint text-ink"
                    : "border-hairline bg-surface text-ink-soft hover:border-ink-faint",
                )}
              >
                <GraduationCap className="size-4" />
                {q.title}
                {q.avg_pct != null && (
                  <span className="font-mono text-[12px] text-ink-faint">avg {q.avg_pct}%</span>
                )}
              </button>
            ))}
          </div>
          {active && <QuizAnalyticsCard quizId={active} />}
        </>
      )}
    </>
  );
}
