import { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight, Check, Lightbulb, PartyPopper } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type { StepStatus, TutorialContent, TutorialDetailData } from "@/types/api";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { ProgressBar } from "@/components/ProgressBar";
import { StatusDot } from "@/components/StatusDot";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

/** "mock_server/data/images/tut1/x.png" -> served at "/tutorial-images/tut1/x.png" */
function imageUrl(sourceImage: string | null | undefined): string | null {
  if (!sourceImage) return null;
  const prefix = "mock_server/data/images/";
  const norm = sourceImage.replace(/\\/g, "/");
  return norm.startsWith(prefix) ? `/tutorial-images/${norm.slice(prefix.length)}` : null;
}

interface RunStep {
  step_id: string;
  section: string;
  app: string;
  title: string;
  description: string;
  hint: string | null;
  image: string | null;
}

export function RunPage() {
  const { tutorialId = "" } = useParams();
  const qc = useQueryClient();

  const content = useQuery({
    queryKey: ["student", "tutorial-content", tutorialId],
    queryFn: () => apiFetch<TutorialContent>(`/api/tutorials/${tutorialId}`),
    staleTime: 5 * 60_000,
  });
  const detail = useQuery({
    queryKey: ["student", "tutorial", tutorialId],
    queryFn: () => apiFetch<TutorialDetailData>(`/api/student/tutorials/${tutorialId}`),
    // Light polling: ticks arriving from elsewhere (the desktop guide, another
    // tab) show up without a reload.
    refetchInterval: 5000,
  });

  // Flatten to the runtime order the desktop guide uses.
  const steps: RunStep[] = useMemo(() => {
    const data = content.data;
    if (!data) return [];
    const byId = new Map<string, RunStep>();
    const docOrder: string[] = [];
    for (const sec of data.sections) {
      for (const st of sec.steps) {
        byId.set(st.step_id, {
          step_id: st.step_id,
          section: sec.section,
          app: st.app,
          title: st.title,
          description: st.description,
          hint: st.hints?.[0] ?? null,
          image: imageUrl(st.source_image),
        });
        docOrder.push(st.step_id);
      }
    }
    const order = data.runtime_steps?.length ? data.runtime_steps : docOrder;
    return order.map((sid) => byId.get(sid)).filter((s): s is RunStep => s !== undefined);
  }, [content.data]);

  const statuses: Record<string, StepStatus> = useMemo(() => {
    const out: Record<string, StepStatus> = {};
    for (const sec of detail.data?.sections ?? []) {
      for (const st of sec.steps) out[st.step_id] = st.status;
    }
    return out;
  }, [detail.data]);

  const [index, setIndex] = useState(0);
  const [autoPositioned, setAutoPositioned] = useState(false);

  // On first load, jump to the first incomplete step.
  useEffect(() => {
    if (autoPositioned || steps.length === 0 || !detail.data) return;
    const firstOpen = steps.findIndex((s) => statuses[s.step_id] !== "completed");
    setIndex(firstOpen === -1 ? steps.length - 1 : firstOpen);
    setAutoPositioned(true);
  }, [autoPositioned, steps, statuses, detail.data]);

  const mark = useMutation({
    mutationFn: (stepId: string) =>
      apiFetch("/api/events/action_events", {
        json: [
          {
            tutorial_id: tutorialId,
            step_id: stepId,
            action_type: "step_completed",
            timestamp: Date.now() / 1000,
          },
        ],
      }),
    onSuccess: (_data, stepId) => {
      // Optimistic tick: update the cached detail immediately.
      qc.setQueryData<TutorialDetailData>(["student", "tutorial", tutorialId], (old) =>
        old
          ? {
              ...old,
              sections: old.sections.map((sec) => ({
                ...sec,
                steps: sec.steps.map((s) =>
                  s.step_id === stepId ? { ...s, status: "completed" as const } : s,
                ),
              })),
              steps_completed: old.steps_completed + (statuses[stepId] === "completed" ? 0 : 1),
            }
          : old,
      );
      qc.invalidateQueries({ queryKey: ["student", "dashboard"] });
      qc.invalidateQueries({ queryKey: ["student", "tutorial", tutorialId] });
      setIndex((i) => Math.min(i + 1, steps.length - 1));
    },
  });

  if (content.isPending || detail.isPending) {
    return (
      <div className="flex justify-center py-24">
        <Spinner />
      </div>
    );
  }
  if (content.isError || detail.isError || steps.length === 0) {
    return (
      <Card className="text-center">
        <p className="text-ink-soft">Couldn't load this tutorial.</p>
        <Link to={`/tutorials/${tutorialId}`} className="mt-2 inline-block font-medium text-violet">
          Back to overview
        </Link>
      </Card>
    );
  }

  const completedCount = steps.filter((s) => statuses[s.step_id] === "completed").length;
  const allDone = completedCount === steps.length;
  const step = steps[Math.min(index, steps.length - 1)];
  const stepDone = statuses[step.step_id] === "completed";

  return (
    <>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Link
          to={`/tutorials/${tutorialId}`}
          className="inline-flex items-center gap-1 text-sm font-medium text-ink-soft hover:text-ink"
        >
          <ArrowLeft className="size-4" /> {detail.data?.title}
        </Link>
        <div className="w-64">
          <ProgressBar total={steps.length} completed={completedCount} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[300px_1fr]">
        {/* ── steps rail: live tick marks ── */}
        <Card className="max-h-[75vh] overflow-y-auto p-3">
          <ul>
            {steps.map((s, i) => (
              <li key={s.step_id}>
                <button
                  onClick={() => setIndex(i)}
                  className={cn(
                    "flex w-full items-center gap-2.5 rounded-(--radius-control) px-2 py-2 text-left transition-colors",
                    i === index ? "bg-violet-tint" : "hover:bg-paper",
                  )}
                >
                  <StatusDot status={statuses[s.step_id] ?? "not_started"} />
                  <span
                    className={cn(
                      "min-w-0 flex-1 truncate text-sm",
                      i === index ? "font-medium text-ink" : "text-ink-soft",
                      statuses[s.step_id] === "completed" && i !== index && "text-ink-faint",
                    )}
                  >
                    {s.title}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </Card>

        {/* ── current step panel ── */}
        <div className="space-y-4">
          {allDone && (
            <Card className="flex items-center gap-3 border-success/30 bg-success-tint">
              <PartyPopper className="size-6 shrink-0 text-success" />
              <div>
                <div className="font-semibold text-success">All {steps.length} steps complete!</div>
                <div className="text-sm text-ink-soft">
                  {detail.data?.needs_report ? (
                    <>
                      Now generate the report in Mechanical and{" "}
                      <Link to={`/tutorials/${tutorialId}`} className="font-medium text-violet">
                        upload it for checking
                      </Link>
                      {detail.data?.quiz ? (
                        <>
                          , then{" "}
                          <Link to={`/tutorials/${tutorialId}/quiz`} className="font-medium text-violet">
                            take the quiz
                          </Link>
                        </>
                      ) : null}
                      .
                    </>
                  ) : detail.data?.quiz ? (
                    <>
                      Now{" "}
                      <Link to={`/tutorials/${tutorialId}/quiz`} className="font-medium text-violet">
                        take the quiz
                      </Link>{" "}
                      to finish the tutorial.
                    </>
                  ) : (
                    "Nice work."
                  )}
                </div>
              </div>
            </Card>
          )}

          <Card>
            <div className="mb-1 flex items-center justify-between gap-2">
              <span className="text-sm text-violet">
                Step {index + 1} of {steps.length} · {step.section}
              </span>
              <div className="flex items-center gap-1.5">
                <Badge>{step.app}</Badge>
                <code className="font-mono text-xs text-ink-faint">{step.step_id}</code>
              </div>
            </div>
            <CardTitle className="font-serif text-[22px]">{step.title}</CardTitle>
            <p className="mt-2 text-[15px] leading-relaxed text-ink">{step.description}</p>
            {step.hint && (
              <p className="mt-3 flex items-start gap-2 text-sm italic text-ink-soft">
                <Lightbulb className="mt-0.5 size-4 shrink-0 text-warning" />
                {step.hint}
              </p>
            )}
            {step.image && (
              <img
                src={step.image}
                alt={`Reference for ${step.title}`}
                className="mt-4 max-h-80 rounded-(--radius-control) border border-hairline"
              />
            )}

            <div className="mt-6 flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => setIndex((i) => Math.max(0, i - 1))}
                disabled={index === 0}
              >
                <ArrowLeft className="size-4" /> Prev
              </Button>
              {stepDone ? (
                <span className="inline-flex h-10 items-center gap-2 rounded-(--radius-control) border border-success/30 bg-success-tint px-4 text-[15px] font-medium text-success">
                  <Check className="size-4" strokeWidth={3} /> Completed
                </span>
              ) : (
                <Button onClick={() => mark.mutate(step.step_id)} loading={mark.isPending}>
                  <Check className="size-4" strokeWidth={3} /> Mark step complete
                </Button>
              )}
              <Button
                variant="secondary"
                onClick={() => setIndex((i) => Math.min(steps.length - 1, i + 1))}
                disabled={index === steps.length - 1}
              >
                Next <ArrowRight className="size-4" />
              </Button>
            </div>
            <p className="mt-3 text-[13px] text-ink-faint">
              Do the action in Ansys on this PC, then mark it complete — your progress
              syncs to your dashboard instantly. The desktop guide overlay tracks these
              same steps.
            </p>
          </Card>
        </div>
      </div>
    </>
  );
}
