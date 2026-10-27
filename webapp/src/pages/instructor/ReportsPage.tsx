import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, ChevronDown, Clock, Download, MessageSquare, RotateCcw,
  XCircle,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import { Card } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { PageHeader } from "@/components/PageHeader";
import { cn } from "@/components/cn";

interface ReportCheck {
  name: string;
  ok: boolean;
  message: string;
}

interface Submission {
  submission_id: number;
  student: string;
  section: string | null;
  tutorial_id: string;
  tutorial_title: string;
  filename: string;
  status: "checked" | "pending" | "claimed" | "failed";
  ok: boolean;
  score: number;
  total: number;
  checks: ReportCheck[];
  feedback: string;
  llm_review: { summary?: string } | null;
  submitted_at: number;
  checked_at: number | null;
  instructor_feedback: string | null;
  instructor_feedback_at: number | null;
}

interface CheckerStatus {
  pending: number;
  in_progress: number;
  failed: number;
  needs_review: number;
  checker_last_seen: number | null;
  now: number;
}

// A running checker claims a waiting report within seconds, so a queue that
// has not moved in this long means the desktop is off rather than busy.
const CHECKER_STALE_S = 150;

const FILTERS = [
  { key: "", label: "All" },
  { key: "queued", label: "Waiting" },
  { key: "checked", label: "Checked" },
  { key: "failed", label: "Failed" },
] as const;

function when(ts: number | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString(undefined, {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
  });
}

function StatusBadge({ s }: { s: Submission }) {
  if (s.status === "pending" || s.status === "claimed") {
    return (
      <Badge tone="warning">
        <Clock className="size-3.5" /> {s.status === "claimed" ? "Checking" : "Queued"}
      </Badge>
    );
  }
  if (s.status === "failed") {
    return (
      <Badge tone="error">
        <AlertTriangle className="size-3.5" /> Could not read
      </Badge>
    );
  }
  return s.ok ? (
    <Badge tone="success">
      <CheckCircle2 className="size-3.5" /> Passed
    </Badge>
  ) : (
    <Badge tone="warning">
      <XCircle className="size-3.5" /> Needs fixes
    </Badge>
  );
}

function Row({ s }: { s: Submission }) {
  const [open, setOpen] = useState(false);
  const [note, setNote] = useState(s.instructor_feedback ?? "");
  const [saved, setSaved] = useState(false);
  const qc = useQueryClient();

  const leaveFeedback = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/reports/${s.submission_id}/feedback`, {
        json: { feedback: note },
      }),
    onSuccess: () => {
      setSaved(true);
      qc.invalidateQueries({ queryKey: ["instructor", "reports"] });
    },
  });
  const recheck = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/reports/${s.submission_id}/recheck`, { json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "reports"] }),
  });

  return (
    <div className="border-b border-hairline last:border-b-0">
      <div className="flex flex-wrap items-center gap-3 px-4 py-3">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 items-center gap-3 text-left"
        >
          <ChevronDown
            className={cn("size-4 shrink-0 text-ink-faint transition-transform", open && "rotate-180")}
          />
          <div className="min-w-0">
            <div className="truncate text-[15px] font-medium text-ink">{s.student}</div>
            <div className="truncate text-[13px] text-ink-soft">
              {s.tutorial_title}
              {s.section ? ` · ${s.section}` : ""}
            </div>
          </div>
        </button>

        {s.instructor_feedback && (
          <Badge tone="violet">
            <MessageSquare className="size-3.5" /> Feedback sent
          </Badge>
        )}
        <StatusBadge s={s} />
        <span className="w-16 text-right text-sm tabular-nums text-ink-soft">
          {s.status === "checked" ? `${s.score}/${s.total}` : ""}
        </span>
        <span className="w-32 text-right text-[13px] text-ink-faint">{when(s.submitted_at)}</span>

        <a href={`/api/instructor/reports/${s.submission_id}/file`} download={s.filename}>
          <Button variant="secondary" className="h-8 px-2.5 text-[13px]">
            <Download className="size-3.5" /> Open
          </Button>
        </a>
      </div>

      {open && (
        <div className="space-y-3 bg-paper px-4 pb-4 pt-1 text-sm">
          <div className="text-[13px] text-ink-faint">
            <code className="font-mono">{s.filename}</code> · submitted {when(s.submitted_at)}
            {s.checked_at ? ` · checked ${when(s.checked_at)}` : ""}
          </div>

          {s.checks.length > 0 && (
            <ul className="space-y-1.5">
              {s.checks.map((c) => (
                <li key={c.name} className="flex items-start gap-2">
                  {c.ok ? (
                    <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                  ) : (
                    <XCircle className="mt-0.5 size-4 shrink-0 text-warning" />
                  )}
                  <span className="text-ink">
                    <span className="font-medium">{c.name}</span>
                    {c.message ? ` — ${c.message}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          )}

          {s.feedback && (
            <p className="whitespace-pre-wrap leading-relaxed text-ink-soft">{s.feedback}</p>
          )}

          {s.llm_review?.summary && (
            <div className="rounded-(--radius-control) border border-hairline bg-surface px-3 py-2">
              <div className="text-xs font-semibold uppercase tracking-wide text-ink-faint">
                AI review (the rubric above is authoritative)
              </div>
              <p className="mt-1 whitespace-pre-wrap leading-relaxed text-ink-soft">
                {s.llm_review.summary}
              </p>
            </div>
          )}

          <div className="rounded-(--radius-control) border border-hairline bg-surface p-3">
            <label
              htmlFor={`feedback-${s.submission_id}`}
              className="text-xs font-semibold uppercase tracking-wide text-ink-faint"
            >
              Your feedback to {s.student}
            </label>
            <textarea
              id={`feedback-${s.submission_id}`}
              value={note}
              onChange={(e) => {
                setNote(e.target.value);
                setSaved(false);
              }}
              rows={3}
              placeholder="What the rubric can't say: judgement about the mesh, the boundary conditions, the write-up."
              className="mt-2 w-full resize-y rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 text-sm text-ink outline-none focus:border-violet"
            />
            <div className="mt-2 flex items-center gap-3">
              <Button
                className="h-8 px-3 text-[13px]"
                loading={leaveFeedback.isPending}
                onClick={() => leaveFeedback.mutate()}
              >
                {s.instructor_feedback ? "Update feedback" : "Send feedback"}
              </Button>
              {saved && <span className="text-[13px] text-success">Sent. The student sees it now.</span>}
              {!saved && s.instructor_feedback_at && (
                <span className="text-[13px] text-ink-faint">
                  Last sent {when(s.instructor_feedback_at)}
                </span>
              )}
            </div>
          </div>

          <Button
            variant="secondary"
            className="h-8 px-2.5 text-[13px]"
            loading={recheck.isPending}
            onClick={() => recheck.mutate()}
          >
            <RotateCcw className="size-3.5" /> Check again
          </Button>
        </div>
      )}
    </div>
  );
}

export function ReportsPage() {
  const [filter, setFilter] = useState<string>("");

  const reports = useQuery({
    queryKey: ["instructor", "reports", filter],
    queryFn: () =>
      apiFetch<Submission[]>(`/api/instructor/reports${filter ? `?status=${filter}` : ""}`),
    // A queued report is checked elsewhere, so results arrive without the
    // instructor doing anything: keep the list honest while they watch it.
    refetchInterval: 10_000,
  });

  const status = useQuery({
    queryKey: ["instructor", "checker-status"],
    queryFn: () => apiFetch<CheckerStatus>("/api/agent/status"),
    refetchInterval: 10_000,
  });

  const queueLine = () => {
    const s = status.data;
    if (!s) return null;
    if (s.pending === 0 && s.in_progress === 0) {
      return s.checker_last_seen
        ? `Checker last active ${when(s.checker_last_seen)}. Nothing waiting.`
        : "Reports are checked on this server.";
    }
    return `${s.pending + s.in_progress} waiting to be checked${
      s.checker_last_seen ? `, checker last active ${when(s.checker_last_seen)}` : ""
    }.`;
  };

  // The one failure that needs saying out loud: students have uploaded and
  // the desktop that grades is not running, so nothing is happening and the
  // queue line alone is too quiet to notice.
  const s = status.data;
  const stalled =
    s !== undefined &&
    s.pending + s.in_progress > 0 &&
    (s.checker_last_seen === null || s.now - s.checker_last_seen > CHECKER_STALE_S);

  return (
    <>
      <PageHeader
        title="Reports"
        subtitle="What students submitted, and how it scored against the rubric."
      />

      {stalled && (
        <div className="mb-4 flex items-start gap-3 rounded-(--radius-control) border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-900 dark:bg-amber-950/40">
          <AlertTriangle className="mt-0.5 size-4 shrink-0 text-amber-600 dark:text-amber-500" />
          <div className="text-[13px] leading-relaxed text-ink-soft">
            <span className="font-medium text-ink">
              {s!.pending + s!.in_progress} report
              {s!.pending + s!.in_progress === 1 ? " is" : "s are"} waiting, and the
              checker on your desktop has not picked
              {s!.pending + s!.in_progress === 1 ? " it" : " them"} up.
            </span>{" "}
            Start that machine, or run <code>tools\report_checker.py</code> on it, and
            these will be checked within seconds. Nothing is lost while it waits.
          </div>
        </div>
      )}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button
            key={f.key}
            onClick={() => setFilter(f.key)}
            className={cn(
              "h-8 rounded-(--radius-control) px-3 text-sm font-medium transition-colors",
              filter === f.key
                ? "bg-violet-tint text-violet"
                : "text-ink-soft hover:bg-paper hover:text-ink",
            )}
          >
            {f.label}
          </button>
        ))}
        <span className="ml-auto text-[13px] text-ink-faint">{queueLine()}</span>
      </div>

      <Card className="p-0">
        {reports.isPending ? (
          <div className="flex justify-center py-12">
            <Spinner />
          </div>
        ) : reports.isError ? (
          <p className="px-4 py-10 text-center text-ink-soft">Couldn't load submissions.</p>
        ) : reports.data.length === 0 ? (
          <p className="px-4 py-10 text-center text-ink-soft">
            {filter ? "Nothing in this state." : "No reports submitted yet."}
          </p>
        ) : (
          reports.data.map((s) => <Row key={s.submission_id} s={s} />)
        )}
      </Card>
    </>
  );
}
