import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Check, GraduationCap } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { QuizAnalytics, QuizStats } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

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
        subtitle="Question difficulty and concept mastery. Quiz content is JSON-authored in mock_server/data/quizzes/."
      />
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
