import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, BarChart3, CheckCircle2, Download, FileCheck, GraduationCap,
  ListChecks, MonitorPlay, RefreshCw, Users,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { ActivityItem, ProgressMatrix, QuizStats, Section } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Label } from "@/components/Input";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

export function timeAgo(ts: number): string {
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/* ── stat tiles ─────────────────────────────────────────────────────── */

function Tile({ icon: Icon, label, value }: { icon: typeof Users; label: string; value: string }) {
  return (
    <Card className="flex items-center gap-3 py-4">
      <div className="flex size-10 items-center justify-center rounded-(--radius-control) bg-violet-tint">
        <Icon className="size-5 text-violet" />
      </div>
      <div>
        <div className="font-serif text-2xl font-semibold leading-tight text-ink">{value}</div>
        <div className="text-[13px] text-ink-soft">{label}</div>
      </div>
    </Card>
  );
}

/* ── completion matrix ──────────────────────────────────────────────── */

const STATUS_DOT: Record<string, string> = {
  completed: "bg-success",
  in_progress: "bg-violet",
  not_started: "bg-hairline",
};

function MatrixCard({ matrix }: { matrix: ProgressMatrix }) {
  return (
    <Card>
      <CardTitle>Completion matrix</CardTitle>
      {matrix.students.length === 0 ? (
        <p className="mt-2 py-4 text-[15px] text-ink-faint">
          No students registered yet — share a class code.
        </p>
      ) : (
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-hairline text-left text-[13px] text-ink-soft">
                <th className="py-2 pr-3 font-medium">Student</th>
                {matrix.tutorials.map((t) => (
                  <th key={t.tutorial_id} className="px-3 py-2 font-medium">
                    {t.title.split("—")[0].trim()}
                    {t.is_mandatory && <span className="ml-1 text-violet">*</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {matrix.students.map((s) => (
                <tr key={s.opaque_token} className="border-b border-hairline last:border-b-0">
                  <td className="py-2.5 pr-3">
                    <div className="font-medium text-ink">{s.username}</div>
                    <div className="font-mono text-[11px] text-ink-faint">{s.opaque_token}</div>
                  </td>
                  {matrix.tutorials.map((t) => {
                    const c = s.cells[t.tutorial_id];
                    return (
                      <td key={t.tutorial_id} className="px-3 py-2.5">
                        <div className="flex items-center gap-2">
                          <span className={cn("size-2.5 shrink-0 rounded-full", STATUS_DOT[c.status])} />
                          <span className="font-mono text-[13px] text-ink">{c.percent}%</span>
                          <span className="flex gap-1 text-[11px] text-ink-faint">
                            {c.report_ok && (
                              <span title="Report passed" className="text-success">R✓</span>
                            )}
                            {c.quiz_attempts != null && c.quiz_attempts > 0 && (
                              <span title={`Best quiz score ${Math.round((c.quiz_best ?? 0) * 100)}%`}>
                                Q{Math.round((c.quiz_best ?? 0) * 100)}
                              </span>
                            )}
                          </span>
                        </div>
                        <div className="mt-0.5 text-[11px] text-ink-faint">
                          {c.steps_completed}/{c.steps_total} steps
                        </div>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="mt-2 text-[12px] text-ink-faint">* mandatory tutorial</p>
    </Card>
  );
}

/* ── quiz score distribution ────────────────────────────────────────── */

function DistributionCard({ stats }: { stats: QuizStats[] }) {
  return (
    <Card>
      <div className="flex items-center gap-2">
        <BarChart3 className="size-5 text-violet" />
        <CardTitle>Quiz score distribution</CardTitle>
      </div>
      {stats.length === 0 || stats.every((s) => s.students === 0) ? (
        <p className="mt-2 py-4 text-[15px] text-ink-faint">No quiz submissions yet.</p>
      ) : (
        <div className="mt-4 space-y-6">
          {stats.filter((s) => s.students > 0).map((s) => {
            const max = Math.max(...s.histogram.map((b) => b.count), 1);
            return (
              <div key={s.quiz_id}>
                <div className="mb-2 flex items-baseline justify-between">
                  <span className="text-sm font-medium text-ink">{s.title}</span>
                  <span className="text-[13px] text-ink-soft">
                    {s.students} student{s.students === 1 ? "" : "s"} · avg {s.avg_pct}%
                  </span>
                </div>
                <div className="flex h-24 items-end gap-1.5">
                  {s.histogram.map((b) => (
                    <div key={b.correct} className="flex flex-1 flex-col items-center gap-1">
                      <span className="text-[11px] text-ink-soft">{b.count > 0 ? b.count : ""}</span>
                      <div
                        className={cn(
                          "w-full rounded-t-sm",
                          b.count > 0 ? "bg-violet" : "bg-hairline",
                        )}
                        style={{ height: `${Math.max((b.count / max) * 72, 3)}px` }}
                      />
                      <span className="font-mono text-[11px] text-ink-faint">{b.correct}</span>
                    </div>
                  ))}
                </div>
                <div className="mt-1 text-center text-[11px] text-ink-faint">
                  correct answers (best attempt) out of {s.total_questions}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

/* ── activity feed ──────────────────────────────────────────────────── */

const KIND_ICON = {
  event: MonitorPlay,
  report: FileCheck,
  quiz: ListChecks,
} as const;

function activityText(e: ActivityItem): string {
  if (e.kind === "report") {
    return `report ${e.detail} (${e.score}/${e.total})`;
  }
  if (e.kind === "quiz") {
    return `quiz submitted — ${Math.round((e.score ?? 0) * 100)}%`;
  }
  const map: Record<string, string> = {
    step_completed: "completed",
    step_started: "started",
    verify_failed: "stuck on",
    hint_shown: "hint on",
  };
  return `${map[e.detail] ?? e.detail} ${e.step_id ?? ""}`;
}

function ActivityCard({ feed }: { feed: ActivityItem[] }) {
  return (
    <Card>
      <div className="flex items-center gap-2">
        <Activity className="size-5 text-violet" />
        <CardTitle>Recent activity</CardTitle>
      </div>
      {feed.length === 0 ? (
        <p className="mt-2 py-4 text-[15px] text-ink-faint">Nothing yet.</p>
      ) : (
        <ul className="mt-2 max-h-105 overflow-y-auto">
          {feed.map((e, i) => {
            const Icon = KIND_ICON[e.kind];
            return (
              <li key={i} className="flex items-start gap-2.5 border-b border-hairline py-2.5 text-sm last:border-b-0">
                <Icon className={cn("mt-0.5 size-4 shrink-0",
                  e.kind === "event" && e.detail === "verify_failed" ? "text-error" : "text-ink-faint")} />
                <div className="min-w-0">
                  <span className="font-medium text-ink">{e.username}</span>{" "}
                  <span className="text-ink-soft">{activityText(e)}</span>
                  <div className="text-[12px] text-ink-faint">
                    {e.tutorial_title} · {timeAgo(e.timestamp)}
                  </div>
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

/* ── sections (class codes) ─────────────────────────────────────────── */

function SectionRow({ section }: { section: Section }) {
  const qc = useQueryClient();
  const regen = useMutation({
    mutationFn: () =>
      apiFetch<Section>(`/api/instructor/sections/${section.id}/regenerate-code`, { json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "sections"] }),
  });

  return (
    <div className="flex items-center justify-between gap-4 border-b border-hairline py-3 last:border-b-0">
      <div>
        <div className="font-medium text-ink">{section.name}</div>
        <div className="text-sm text-ink-soft">
          {section.student_count} student{section.student_count === 1 ? "" : "s"} registered
        </div>
      </div>
      <div className="flex items-center gap-2">
        <code className="rounded-(--radius-control) border border-hairline bg-paper px-3 py-1 font-mono text-[15px] tracking-wider text-ink">
          {section.class_code}
        </code>
        <button
          onClick={() => regen.mutate()}
          title="Regenerate class code"
          className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-paper hover:text-ink"
        >
          {regen.isPending ? <Spinner className="size-4" /> : <RefreshCw className="size-4" />}
        </button>
      </div>
    </div>
  );
}

function SectionsCard() {
  const { data: sections, isPending } = useQuery({
    queryKey: ["instructor", "sections"],
    queryFn: () => apiFetch<Section[]>("/api/instructor/sections"),
  });
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const create = useMutation({
    mutationFn: () => apiFetch<Section>("/api/instructor/sections", { json: { name } }),
    onSuccess: () => {
      setName("");
      qc.invalidateQueries({ queryKey: ["instructor", "sections"] });
    },
  });

  return (
    <Card>
      <div className="flex items-center justify-between">
        <CardTitle>Sections</CardTitle>
        <Badge tone="violet">class codes</Badge>
      </div>
      <div className="mt-1">
        {isPending ? (
          <div className="flex justify-center py-6">
            <Spinner />
          </div>
        ) : sections && sections.length > 0 ? (
          sections.map((s) => <SectionRow key={s.id} section={s} />)
        ) : (
          <p className="py-4 text-[15px] text-ink-faint">
            No sections yet — create the first one below.
          </p>
        )}
      </div>
      <form
        className="mt-3 flex items-end gap-2 border-t border-hairline pt-3"
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) create.mutate();
        }}
      >
        <div className="flex-1">
          <Label htmlFor="section-name">New section</Label>
          <Input
            id="section-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Section A — Fall 2026"
          />
        </div>
        <Button type="submit" loading={create.isPending}>
          Create
        </Button>
      </form>
    </Card>
  );
}

/* ── the page ───────────────────────────────────────────────────────── */

export function ClassDashboardPage() {
  const { data: matrix } = useQuery({
    queryKey: ["instructor", "progress"],
    queryFn: () => apiFetch<ProgressMatrix>("/api/instructor/progress"),
    refetchInterval: 30_000,
  });
  const { data: feed } = useQuery({
    queryKey: ["instructor", "activity"],
    queryFn: () => apiFetch<ActivityItem[]>("/api/instructor/activity?limit=50"),
    refetchInterval: 30_000,
  });
  const { data: quizStats } = useQuery({
    queryKey: ["instructor", "quiz-stats"],
    queryFn: () => apiFetch<QuizStats[]>("/api/instructor/quiz-stats"),
    refetchInterval: 60_000,
  });

  if (!matrix) {
    return (
      <div className="flex justify-center py-16">
        <Spinner className="size-6" />
      </div>
    );
  }

  const t = matrix.tiles;
  return (
    <>
      <PageHeader
        title="Class"
        subtitle="Cohort progress across every published tutorial."
        actions={
          <div className="flex items-center gap-1.5">
            <span className="mr-1 text-[13px] text-ink-faint">Export CSV (token-only):</span>
            {(["action_events", "quiz_submissions", "report_submissions"] as const).map((table) => (
              <a
                key={table}
                href={`/api/instructor/export/${table}.csv`}
                download
                className="inline-flex h-8 items-center gap-1 rounded-(--radius-control) border border-hairline bg-surface px-2.5 font-mono text-[12px] text-ink-soft hover:border-ink-faint hover:text-ink"
              >
                <Download className="size-3.5" /> {table.split("_")[0]}
              </a>
            ))}
          </div>
        }
      />
      <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Tile icon={Users} label="Students" value={String(t.students)} />
        <Tile icon={CheckCircle2} label="Avg completion" value={`${t.avg_completion}%`} />
        <Tile icon={FileCheck} label="Reports passed" value={String(t.reports_passed)} />
        <Tile
          icon={GraduationCap}
          label="Quiz average"
          value={t.quiz_avg != null ? `${t.quiz_avg}%` : "—"}
        />
      </div>
      <div className="grid items-start gap-4 xl:grid-cols-[1fr_380px]">
        <div className="min-w-0 space-y-4">
          <MatrixCard matrix={matrix} />
          <DistributionCard stats={quizStats ?? []} />
        </div>
        <div className="space-y-4">
          <SectionsCard />
          <ActivityCard feed={feed ?? []} />
        </div>
      </div>
    </>
  );
}
