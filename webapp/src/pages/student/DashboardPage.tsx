import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight, FileCheck2, ListChecks } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { DashboardData, TutorialCardData } from "@/types/api";
import { useMe } from "@/auth/useMe";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { ProgressBar } from "@/components/ProgressBar";
import { Spinner } from "@/components/Spinner";

function statusLine(t: TutorialCardData): { text: string; tone: "success" | "warning" | "neutral" } {
  if (t.needs_report) {
    if (t.report?.ok) return { text: "Report: passed", tone: "success" };
    if (t.report) return { text: `Report: needs fixes (${t.report.last_score}/${t.report.last_total})`, tone: "warning" };
  }
  if (t.quiz?.attempts) {
    return { text: `Quiz: best ${Math.round((t.quiz.best_score ?? 0) * 100)}%`, tone: "neutral" };
  }
  return { text: `${t.steps_completed}/${t.steps_total} steps`, tone: "neutral" };
}

function TutorialCard({ t }: { t: TutorialCardData }) {
  const action =
    t.status === "completed" ? "Review" : t.status === "in_progress" ? "Continue" : "Start";
  const line = statusLine(t);
  return (
    <Card className="flex flex-col gap-3">
      <div className="flex items-start justify-between gap-3">
        <CardTitle className="leading-snug">{t.title}</CardTitle>
        {t.status === "completed" && <Badge tone="success">Done</Badge>}
      </div>
      <div className="flex flex-wrap gap-1.5">
        {t.is_mandatory ? <Badge tone="violet">Mandatory</Badge> : <Badge>Optional</Badge>}
        <Badge>{t.product}</Badge>
        <Badge className="font-mono">v{t.version}</Badge>
      </div>
      <ProgressBar total={t.steps_total} completed={t.steps_completed} />
      <div className="flex items-center justify-between">
        <span
          className={
            line.tone === "success"
              ? "text-sm font-medium text-success"
              : line.tone === "warning"
                ? "text-sm font-medium text-warning"
                : "text-sm text-ink-soft"
          }
        >
          {line.text}
        </span>
        <Link
          to={
            t.status === "completed"
              ? `/tutorials/${t.tutorial_id}`
              : `/tutorials/${t.tutorial_id}/run`
          }
          className="inline-flex items-center gap-1 text-[15px] font-medium text-violet hover:text-violet-hover"
        >
          {action}
          <ArrowRight className="size-4" />
        </Link>
      </div>
    </Card>
  );
}

export function DashboardPage() {
  const { data: me } = useMe();
  const { data, isPending, isError, refetch } = useQuery({
    queryKey: ["student", "dashboard"],
    queryFn: () => apiFetch<DashboardData>("/api/student/dashboard"),
  });

  if (isPending) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }
  if (isError || !data) {
    return (
      <Card className="text-center">
        <p className="text-ink-soft">Couldn't load your dashboard.</p>
        <button onClick={() => refetch()} className="mt-2 font-medium text-violet">
          Try again
        </button>
      </Card>
    );
  }

  const mandatory = data.tutorials.filter((t) => t.is_mandatory);
  const optional = data.tutorials.filter((t) => !t.is_mandatory);

  return (
    <>
      <PageHeader
        title={`Welcome, ${me?.username ?? ""}`}
        subtitle={me?.section ? `Enrolled in ${me.section}` : undefined}
      />

      {data.continue && (
        <Link to={`/tutorials/${data.continue.tutorial_id}/run`} className="block">
          <Card className="mb-6 flex items-center justify-between gap-4 border-violet/30 bg-violet-tint transition-colors hover:border-violet/60">
            <div>
              <div className="text-sm font-medium text-violet">Continue where you left off</div>
              <div className="mt-0.5 text-lg font-semibold text-ink">{data.continue.title}</div>
              {data.continue.step_title && (
                <div className="mt-0.5 text-[15px] text-ink-soft">
                  Next: <span className="font-mono text-sm">{data.continue.step_id}</span>{" "}
                  — {data.continue.step_title}
                </div>
              )}
            </div>
            <ArrowRight className="size-6 shrink-0 text-violet" />
          </Card>
        </Link>
      )}

      <h2 className="mb-3 flex items-center gap-2 text-lg font-semibold text-ink">
        <ListChecks className="size-5 text-violet" /> Required
      </h2>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {mandatory.map((t) => (
          <TutorialCard key={t.tutorial_id} t={t} />
        ))}
        {mandatory.length === 0 && (
          <Card className="text-[15px] text-ink-faint">No required tutorials published yet.</Card>
        )}
      </div>

      {optional.length > 0 && (
        <>
          <h2 className="mb-3 mt-8 flex items-center gap-2 text-lg font-semibold text-ink">
            <FileCheck2 className="size-5 text-ink-faint" /> Optional
          </h2>
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {optional.map((t) => (
              <TutorialCard key={t.tutorial_id} t={t} />
            ))}
          </div>
        </>
      )}
    </>
  );
}
