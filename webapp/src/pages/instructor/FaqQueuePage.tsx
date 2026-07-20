import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, CheckCircle2, HelpCircle, RefreshCw, Sparkles, Trash2, XCircle,
} from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { FaqCandidate, PublishedFaq } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";
import { timeAgo } from "./ClassDashboardPage";

const STATUS_TONE: Record<FaqCandidate["status"], string> = {
  candidate: "text-warning",
  drafted: "text-violet",
  approved: "text-success",
  rejected: "text-ink-faint",
};

function CandidateCard({ cand }: { cand: FaqCandidate }) {
  const qc = useQueryClient();
  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["instructor", "faq-candidates"] });
    qc.invalidateQueries({ queryKey: ["instructor", "faqs"] });
  };
  const [question, setQuestion] = useState(cand.draft_question ?? "");
  const [answer, setAnswer] = useState(cand.draft_answer ?? "");
  const [evidenceOpen, setEvidenceOpen] = useState(false);

  const draft = useMutation({
    mutationFn: () =>
      apiFetch<FaqCandidate>(`/api/instructor/faqs/candidates/${cand.id}/draft`, { json: {} }),
    onSuccess: (d) => {
      setQuestion(d.draft_question ?? "");
      setAnswer(d.draft_answer ?? "");
      invalidate();
    },
  });
  const approve = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/faqs/candidates/${cand.id}/approve`, {
        json: { question, answer },
      }),
    onSuccess: invalidate,
  });
  const reject = useMutation({
    mutationFn: () =>
      apiFetch(`/api/instructor/faqs/candidates/${cand.id}/reject`, { json: {} }),
    onSuccess: invalidate,
  });

  const done = cand.status === "approved" || cand.status === "rejected";
  return (
    <Card className={cn(done && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-2">
        <AlertTriangle className="size-4 text-warning" />
        <span className="font-medium text-ink">{cand.step_title ?? cand.step_id}</span>
        <Badge className="font-mono">{cand.step_id}</Badge>
        <span className={cn("ml-auto text-[13px] font-semibold uppercase tracking-wide", STATUS_TONE[cand.status])}>
          {cand.status}
        </span>
      </div>
      <p className="mt-1.5 text-sm text-ink-soft">
        <strong className="text-ink">
          {cand.distinct_students}/{cand.cohort_size} students
        </strong>{" "}
        ({Math.round(cand.failure_rate * 100)}%) failed check{" "}
        <code className="font-mono text-[13px]">{cand.failed_check || "manual"}</code>
      </p>
      <button
        onClick={() => setEvidenceOpen(!evidenceOpen)}
        className="mt-1 text-[13px] font-medium text-violet"
      >
        {evidenceOpen ? "Hide" : "Show"} step context
      </button>
      {evidenceOpen && (
        <div className="mt-2 rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 text-[13px] text-ink-soft">
          <p>{cand.step_description}</p>
          {cand.step_hints.length > 0 && (
            <p className="mt-1 italic">Hints: {cand.step_hints.join(" · ")}</p>
          )}
        </div>
      )}

      {!done && (
        <>
          <div className="mt-3 space-y-2">
            <input
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="FAQ question (what would a confused student ask?)"
              className="h-10 w-full rounded-(--radius-control) border border-hairline bg-surface px-3 text-sm text-ink placeholder:text-ink-faint focus:outline-2 focus:outline-violet"
            />
            <textarea
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Answer (2-4 concrete sentences)"
              rows={3}
              className="w-full rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:outline-2 focus:outline-violet"
            />
          </div>
          {cand.draft_model && (
            <p className="mt-1 text-[12px] text-ink-faint">
              Draft by {cand.draft_model} — edit before approving.
            </p>
          )}
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              variant="secondary"
              loading={draft.isPending}
              onClick={() => draft.mutate()}
            >
              <Sparkles className="size-4" />
              {cand.status === "drafted" ? "Redraft with AI" : "Draft with AI"}
            </Button>
            <Button
              className="ml-auto"
              disabled={!question.trim() || !answer.trim()}
              loading={approve.isPending}
              onClick={() => approve.mutate()}
            >
              <CheckCircle2 className="size-4" /> Approve &amp; publish
            </Button>
            <Button variant="destructive" loading={reject.isPending} onClick={() => reject.mutate()}>
              <XCircle className="size-4" /> Reject
            </Button>
          </div>
          {draft.isError && (
            <p className="mt-2 text-[13px] text-error">
              Drafting failed (is Ollama running?) — you can still write the FAQ by hand.
            </p>
          )}
        </>
      )}
    </Card>
  );
}

function PublishedList() {
  const qc = useQueryClient();
  const { data: faqs } = useQuery({
    queryKey: ["instructor", "faqs"],
    queryFn: () => apiFetch<PublishedFaq[]>("/api/instructor/faqs"),
  });
  const unpublish = useMutation({
    mutationFn: (id: number) =>
      apiFetch(`/api/instructor/faqs/${id}`, { method: "DELETE", headers: { "X-Requested-With": "fetch" } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "faqs"] }),
  });

  return (
    <Card>
      <CardTitle>Published FAQs</CardTitle>
      <p className="mt-1 text-[13px] text-ink-faint">
        Students see these on the matching step (web + desktop guide).
      </p>
      {!faqs || faqs.length === 0 ? (
        <p className="py-4 text-[15px] text-ink-faint">Nothing published yet.</p>
      ) : (
        <ul className="mt-2">
          {faqs.map((f) => (
            <li key={f.faq_id} className="border-b border-hairline py-3 last:border-b-0">
              <div className="flex items-start gap-2">
                <HelpCircle className="mt-0.5 size-4 shrink-0 text-violet" />
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium text-ink">{f.question}</div>
                  <p className="mt-0.5 text-[13px] leading-relaxed text-ink-soft">{f.answer}</p>
                  <div className="mt-1 font-mono text-[11px] text-ink-faint">
                    {f.tutorial_id} · {f.step_id ?? "tutorial-level"} · {timeAgo(f.created_at)}
                  </div>
                </div>
                <button
                  title="Unpublish"
                  onClick={() => unpublish.mutate(f.faq_id)}
                  className="text-ink-faint hover:text-error"
                >
                  <Trash2 className="size-4" />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function FaqQueuePage() {
  const qc = useQueryClient();
  const { data: candidates, isPending } = useQuery({
    queryKey: ["instructor", "faq-candidates"],
    queryFn: () => apiFetch<FaqCandidate[]>("/api/instructor/faqs/candidates"),
  });
  const refresh = useMutation({
    mutationFn: () => apiFetch<{ open_candidates: number }>("/api/instructor/faqs/refresh", { json: {} }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "faq-candidates"] }),
  });

  const open = (candidates ?? []).filter((c) => c.status === "candidate" || c.status === "drafted");
  const closed = (candidates ?? []).filter((c) => c.status === "approved" || c.status === "rejected");

  return (
    <>
      <PageHeader
        title="FAQ review"
        subtitle="Mined from verify_failed events; nothing publishes without your approval."
        actions={
          <Button variant="secondary" loading={refresh.isPending} onClick={() => refresh.mutate()}>
            <RefreshCw className="size-4" /> Mine new candidates
          </Button>
        }
      />
      <div className="grid items-start gap-4 xl:grid-cols-[1fr_420px]">
        <div className="space-y-4">
          {isPending ? (
            <div className="flex justify-center py-16">
              <Spinner className="size-6" />
            </div>
          ) : open.length === 0 ? (
            <Card>
              <p className="py-4 text-[15px] text-ink-faint">
                No open candidates. Click "Mine new candidates" after students have been
                working — steps where ≥30% of the class fails a check show up here.
              </p>
            </Card>
          ) : (
            open.map((c) => <CandidateCard key={c.id} cand={c} />)
          )}
          {closed.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-ink-faint">
                {closed.length} reviewed candidate{closed.length === 1 ? "" : "s"}
              </summary>
              <div className="mt-3 space-y-3">
                {closed.map((c) => (
                  <CandidateCard key={c.id} cand={c} />
                ))}
              </div>
            </details>
          )}
        </div>
        <PublishedList />
      </div>
    </>
  );
}
