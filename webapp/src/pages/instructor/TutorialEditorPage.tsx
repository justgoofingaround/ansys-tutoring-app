import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft, ChevronDown, ChevronUp, Plus, Save, Send, Trash2, TriangleAlert,
} from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { LibraryTutorial, TutorialDoc, TutorialStep, ValidationFinding } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Label, FieldError } from "@/components/Input";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";
import { FindingsList } from "./TutorialLibraryPage";

/* ── step helpers ───────────────────────────────────────────────────── */

/** Fields the form edits directly. Everything else on a step — selector,
 * action, verify, launches, source_image — is UIA-coupled and only reachable
 * through the Advanced box, because a wrong value there breaks the desktop
 * guide rather than just reading badly. */
const PLAIN_FIELDS = ["step_id", "app", "title", "description", "hints"] as const;

const APP_PREFIX: Record<string, string> = {
  workbench: "wb",
  mechanical: "me",
  spaceclaim: "sc",
  discovery: "di",
};

/** Build a step_id matching the validator's '{app}_{NN}_{slug}' convention and
 * not already in use; ids are permanent once saved, since progress and events
 * key on them. */
function newStepId(doc: TutorialDoc, app: string, title: string): string {
  const used = new Set(
    (doc.sections ?? []).flatMap((s) => (s.steps ?? []).map((st) => st.step_id)),
  );
  const prefix = APP_PREFIX[app] ?? "wb";
  const slug =
    title.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "").slice(0, 24) ||
    "step";
  for (let n = 1; n < 100; n++) {
    const id = `${prefix}_${String(n).padStart(2, "0")}_${slug}`;
    if (!used.has(id)) return id;
  }
  return `${prefix}_99_${slug}_${Date.now().toString().slice(-4)}`;
}

function advancedPart(step: TutorialStep): Record<string, unknown> {
  const rest: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(step)) {
    if (!(PLAIN_FIELDS as readonly string[]).includes(k)) rest[k] = v;
  }
  return rest;
}

/* ── outline ────────────────────────────────────────────────────────── */

function Outline({
  doc,
  selected,
  onSelect,
  onMove,
  onDelete,
  onAdd,
}: {
  doc: TutorialDoc;
  selected: string | null;
  onSelect: (id: string) => void;
  onMove: (sectionIdx: number, stepIdx: number, delta: number) => void;
  onDelete: (sectionIdx: number, stepIdx: number) => void;
  onAdd: (sectionIdx: number) => void;
}) {
  return (
    <div className="space-y-4">
      {(doc.sections ?? []).map((section, si) => (
        <div key={si}>
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-[13px] font-semibold tracking-wide text-ink-faint uppercase">
              {section.section || `Section ${si + 1}`}
            </h3>
            <button
              onClick={() => onAdd(si)}
              title="Add a step to this section"
              className="inline-flex size-7 items-center justify-center rounded-(--radius-control) text-ink-faint hover:bg-paper hover:text-ink"
            >
              <Plus className="size-4" />
            </button>
          </div>
          <ul className="mt-1 space-y-0.5">
            {(section.steps ?? []).map((step, idx) => (
              <li key={step.step_id} className="group flex items-center gap-1">
                <button
                  onClick={() => onSelect(step.step_id)}
                  className={cn(
                    "min-w-0 flex-1 truncate rounded-(--radius-control) px-2 py-1.5 text-left text-[14px]",
                    selected === step.step_id
                      ? "bg-violet-tint text-violet"
                      : "text-ink-soft hover:bg-paper hover:text-ink",
                  )}
                >
                  <span className="mr-1.5 font-mono text-[11px] text-ink-faint">
                    {idx + 1}
                  </span>
                  {step.title || step.step_id}
                </button>
                <div className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    onClick={() => onMove(si, idx, -1)}
                    title="Move up"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-ink"
                  >
                    <ChevronUp className="size-3.5" />
                  </button>
                  <button
                    onClick={() => onMove(si, idx, 1)}
                    title="Move down"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-ink"
                  >
                    <ChevronDown className="size-3.5" />
                  </button>
                  <button
                    onClick={() => onDelete(si, idx)}
                    title="Delete step"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-error"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

/* ── step form ──────────────────────────────────────────────────────── */

function StepForm({
  step,
  onChange,
}: {
  step: TutorialStep;
  onChange: (next: TutorialStep) => void;
}) {
  const [advanced, setAdvanced] = useState(false);
  const [advancedText, setAdvancedText] = useState(() =>
    JSON.stringify(advancedPart(step), null, 2),
  );
  const [advancedError, setAdvancedError] = useState<string | null>(null);

  // Reset the advanced box when a different step is selected.
  useEffect(() => {
    setAdvancedText(JSON.stringify(advancedPart(step), null, 2));
    setAdvancedError(null);
  }, [step.step_id]); // eslint-disable-line react-hooks/exhaustive-deps

  const hints = step.hints ?? [];

  function commitAdvanced(text: string) {
    try {
      const parsed = JSON.parse(text);
      if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
        setAdvancedError("Must be a JSON object, e.g. { \"highlight\": \"none\" }");
        return;
      }
      setAdvancedError(null);
      const plain: Record<string, unknown> = {};
      for (const k of PLAIN_FIELDS) if (k in step) plain[k] = (step as never)[k];
      onChange({ ...(plain as unknown as TutorialStep), ...parsed });
    } catch (e) {
      setAdvancedError(e instanceof Error ? e.message : "Invalid JSON");
    }
  }

  return (
    <Card>
      <div className="flex items-center justify-between gap-3">
        <CardTitle>Step</CardTitle>
        <code className="rounded-(--radius-control) border border-hairline bg-paper px-2 py-0.5 font-mono text-[12px] text-ink-soft">
          {step.step_id}
        </code>
      </div>
      <p className="mt-1 text-[13px] text-ink-faint">
        The step id is fixed — student progress is recorded against it.
      </p>

      <div className="mt-4 space-y-4">
        <div>
          <Label htmlFor="step-title">Title</Label>
          <Input
            id="step-title"
            value={step.title ?? ""}
            onChange={(e) => onChange({ ...step, title: e.target.value })}
          />
        </div>
        <div>
          <Label htmlFor="step-desc">Description</Label>
          <textarea
            id="step-desc"
            value={step.description ?? ""}
            onChange={(e) => onChange({ ...step, description: e.target.value })}
            rows={4}
            className="w-full rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-[15px] text-ink placeholder:text-ink-faint focus:outline-2 focus:outline-violet"
          />
          <p className="mt-1.5 text-[13px] text-ink-faint">
            What the student does. Keep exact menu paths and values.
          </p>
        </div>

        <div>
          <Label>Hints</Label>
          <div className="space-y-2">
            {hints.map((hint, i) => (
              <div key={i} className="flex gap-2">
                <Input
                  value={hint}
                  onChange={(e) => {
                    const next = [...hints];
                    next[i] = e.target.value;
                    onChange({ ...step, hints: next });
                  }}
                />
                <Button
                  variant="ghost"
                  onClick={() => onChange({ ...step, hints: hints.filter((_, j) => j !== i) })}
                  title="Remove hint"
                >
                  <Trash2 className="size-4" />
                </Button>
              </div>
            ))}
            <Button variant="secondary" onClick={() => onChange({ ...step, hints: [...hints, ""] })}>
              <Plus className="size-4" /> Add hint
            </Button>
          </div>
          <p className="mt-1.5 text-[13px] text-ink-faint">
            The first hint shows under the description in the student panel.
          </p>
        </div>

        <div className="border-t border-hairline pt-3">
          <button
            onClick={() => setAdvanced((v) => !v)}
            className="flex items-center gap-1.5 text-[14px] font-medium text-ink-soft hover:text-ink"
          >
            {advanced ? <ChevronUp className="size-4" /> : <ChevronDown className="size-4" />}
            Advanced (selector, action, verify)
          </button>
          {advanced && (
            <div className="mt-2">
              <p className="mb-2 text-[13px] text-ink-faint">
                These control what the desktop guide highlights and how it checks the step.
                Changing them can stop the guide working — edit only if you know the
                selectors.
              </p>
              <textarea
                value={advancedText}
                onChange={(e) => setAdvancedText(e.target.value)}
                onBlur={(e) => commitAdvanced(e.target.value)}
                spellCheck={false}
                rows={14}
                className="w-full rounded-(--radius-control) border border-hairline bg-paper px-3 py-2 font-mono text-[13px] text-ink focus:outline-2 focus:outline-violet"
              />
              <FieldError>{advancedError}</FieldError>
            </div>
          )}
        </div>
      </div>
    </Card>
  );
}

/* ── the page ───────────────────────────────────────────────────────── */

export function TutorialEditorPage() {
  const { tutorialId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: library } = useQuery({
    queryKey: ["instructor", "library"],
    queryFn: () => apiFetch<LibraryTutorial[]>("/api/instructor/tutorials"),
  });
  const meta = library?.find((t) => t.tutorial_id === tutorialId);

  const [version, setVersion] = useState<number | null>(null);
  const loadVersion = version ?? meta?.published_version ?? meta?.versions?.[0]?.version ?? null;

  const { data: loaded, isPending, error: loadError } = useQuery({
    enabled: loadVersion != null,
    queryKey: ["instructor", "tutorial-content", tutorialId, loadVersion],
    queryFn: () =>
      apiFetch<{ version: number; content: TutorialDoc }>(
        `/api/instructor/tutorials/${tutorialId}/versions/${loadVersion}/content`,
      ),
  });

  const [doc, setDoc] = useState<TutorialDoc | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [dirty, setDirty] = useState(false);
  const [findings, setFindings] = useState<ValidationFinding[] | null>(null);
  const [saved, setSaved] = useState<number | null>(null);
  const loadedKey = useRef<string>("");

  useEffect(() => {
    if (!loaded) return;
    const key = `${tutorialId}@${loaded.version}`;
    if (loadedKey.current === key) return;
    loadedKey.current = key;
    setDoc(loaded.content);
    setDirty(false);
    setSaved(null);
    setFindings(null);
    setSelected(loaded.content.sections?.[0]?.steps?.[0]?.step_id ?? null);
  }, [loaded, tutorialId]);

  // Browser-level guard; react-router's own block needs a data router config.
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const save = useMutation({
    // Raw fetch rather than apiFetch: a 422 carries {detail: {findings: [...]}},
    // and apiFetch keeps only string details, so the findings would be lost.
    mutationFn: async () => {
      const res = await fetch(`/api/instructor/tutorials/${tutorialId}/content`, {
        method: "POST",
        credentials: "same-origin",
      cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(doc),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        const found = body?.detail?.findings as ValidationFinding[] | undefined;
        throw { findings: found ?? [
          { severity: "error", where: "file", message: `Save failed (${res.status}).` },
        ] };
      }
      return body as { version: number; warnings: ValidationFinding[] };
    },
    onSuccess: (res) => {
      setDirty(false);
      setSaved(res.version);
      setFindings(res.warnings?.length ? res.warnings : null);
      qc.invalidateQueries({ queryKey: ["instructor", "library"] });
    },
    onError: (e: { findings?: ValidationFinding[] }) => {
      setFindings(e.findings ?? [
        { severity: "error", where: "file", message: "Save failed." },
      ]);
    },
  });

  const publish = useMutation({
    mutationFn: (v: number) =>
      apiFetch(`/api/instructor/tutorials/${tutorialId}/publish`, { json: { version: v } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["instructor", "library"] }),
  });

  const selectedStep = useMemo(() => {
    if (!doc || !selected) return null;
    for (const section of doc.sections ?? []) {
      const found = (section.steps ?? []).find((s) => s.step_id === selected);
      if (found) return found;
    }
    return null;
  }, [doc, selected]);

  function update(next: TutorialDoc) {
    setDoc(next);
    setDirty(true);
    setSaved(null);
  }

  function updateStep(nextStep: TutorialStep) {
    if (!doc) return;
    update({
      ...doc,
      sections: (doc.sections ?? []).map((section) => ({
        ...section,
        steps: (section.steps ?? []).map((s) => (s.step_id === nextStep.step_id ? nextStep : s)),
      })),
    });
  }

  function moveStep(si: number, idx: number, delta: number) {
    if (!doc) return;
    const sections = structuredClone(doc.sections ?? []);
    const steps = sections[si].steps ?? [];
    const target = idx + delta;
    if (target < 0 || target >= steps.length) return;
    [steps[idx], steps[target]] = [steps[target], steps[idx]];
    // runtime_steps carries the order the desktop guide runs, so it has to move too.
    const runtime = Array.isArray(doc.runtime_steps) ? [...doc.runtime_steps] : null;
    if (runtime) {
      const a = runtime.indexOf(steps[target].step_id);
      const b = runtime.indexOf(steps[idx].step_id);
      if (a >= 0 && b >= 0) [runtime[a], runtime[b]] = [runtime[b], runtime[a]];
    }
    update({ ...doc, sections, ...(runtime ? { runtime_steps: runtime } : {}) });
  }

  function deleteStep(si: number, idx: number) {
    if (!doc) return;
    const step = (doc.sections?.[si].steps ?? [])[idx];
    const ok = window.confirm(
      [
        `Delete "${step.title || step.step_id}"?`,
        "",
        "Students who already completed this step keep that history, but it stops counting towards the tutorial.",
      ].join("\n"),
    );
    if (!ok) return;
    const sections = structuredClone(doc.sections ?? []);
    sections[si].steps = (sections[si].steps ?? []).filter((_, i) => i !== idx);
    const runtime = Array.isArray(doc.runtime_steps)
      ? doc.runtime_steps.filter((id) => id !== step.step_id)
      : null;
    update({ ...doc, sections, ...(runtime ? { runtime_steps: runtime } : {}) });
    if (selected === step.step_id) setSelected(sections[si].steps?.[0]?.step_id ?? null);
  }

  function addStep(si: number) {
    if (!doc) return;
    const sections = structuredClone(doc.sections ?? []);
    const app = sections[si].app || sections[si].steps?.[0]?.app || "workbench";
    const step: TutorialStep = {
      step_id: newStepId(doc, app, "new step"),
      app,
      title: "New step",
      description: "",
      highlight: "none",
      verify: { type: "manual", prompt: "Did you complete this step?" },
      hints: [],
    };
    sections[si].steps = [...(sections[si].steps ?? []), step];
    // Append to runtime_steps or the guide will skip it entirely.
    const runtime = Array.isArray(doc.runtime_steps)
      ? [...doc.runtime_steps, step.step_id]
      : null;
    update({ ...doc, sections, ...(runtime ? { runtime_steps: runtime } : {}) });
    setSelected(step.step_id);
  }

  if (loadError) {
    const notFound = loadError instanceof ApiError && loadError.status === 404;
    return (
      <>
        <PageHeader title="Tutorial editor" subtitle={tutorialId} />
        <Card className="border-error/30">
          <CardTitle>Couldn't open this tutorial</CardTitle>
          <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
            {notFound
              ? "That version does not exist, or the server is running an older build that predates the editor — restart it and try again."
              : "The tutorial could not be loaded. Try reloading the page; if it keeps failing, sign out and back in."}
          </p>
          <p className="mt-2 font-mono text-[12px] text-ink-faint">
            {loadError instanceof ApiError
              ? `HTTP ${loadError.status} · ${loadError.code}`
              : String((loadError as Error)?.message ?? loadError)}
          </p>
          <div className="mt-4 flex gap-2">
            <Button onClick={() => window.location.reload()}>Reload</Button>
            <Button variant="secondary" onClick={() => navigate("/instructor/tutorials")}>
              <ArrowLeft className="size-4" /> Back to the library
            </Button>
          </div>
        </Card>
      </>
    );
  }

  if (isPending || !doc) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  const isPublished = meta?.published_version === loaded?.version;

  return (
    <>
      <PageHeader
        title={doc.title || tutorialId}
        subtitle={`Editing version ${loaded?.version}${isPublished ? " (published)" : " (draft)"}`}
        actions={
          <div className="flex items-center gap-2">
            {dirty && (
              <span className="flex items-center gap-1.5 text-[13px] text-warning">
                <TriangleAlert className="size-4" /> Unsaved changes
              </span>
            )}
            <Button variant="ghost" onClick={() => navigate("/instructor/tutorials")}>
              <ArrowLeft className="size-4" /> Library
            </Button>
            <Button variant="secondary" loading={save.isPending} onClick={() => save.mutate()}>
              <Save className="size-4" /> Save draft
            </Button>
            <Button
              disabled={dirty || saved == null || publish.isPending}
              loading={publish.isPending}
              onClick={() => saved != null && publish.mutate(saved)}
              title={dirty ? "Save your changes first" : "Make this version live for students"}
            >
              <Send className="size-4" /> Publish
            </Button>
          </div>
        }
      />

      {saved != null && !dirty && (
        <Card className="mb-4 border-success/30">
          <p className="text-[15px] text-ink">
            Saved as version {saved}.{" "}
            {meta?.published_version === saved
              ? "It is live for students."
              : "Students still see version " +
                (meta?.published_version ?? "—") +
                " until you publish it."}
          </p>
        </Card>
      )}

      {findings && (
        <Card className="mb-4 border-error/30">
          <CardTitle>Could not save</CardTitle>
          <FindingsList findings={findings} />
        </Card>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-[320px_1fr]">
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Steps</CardTitle>
            <Badge tone="violet">{(doc.sections ?? []).reduce((n, s) => n + (s.steps?.length ?? 0), 0)}</Badge>
          </div>
          <div className="mt-3">
            <Outline
              doc={doc}
              selected={selected}
              onSelect={setSelected}
              onMove={moveStep}
              onDelete={deleteStep}
              onAdd={addStep}
            />
          </div>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardTitle>Tutorial</CardTitle>
            <div className="mt-3 space-y-4">
              <div>
                <Label htmlFor="tut-title">Title</Label>
                <Input
                  id="tut-title"
                  value={doc.title ?? ""}
                  onChange={(e) => update({ ...doc, title: e.target.value })}
                />
              </div>
              <div>
                <Label htmlFor="tut-problem">Problem</Label>
                <textarea
                  id="tut-problem"
                  value={doc.problem ?? ""}
                  onChange={(e) => update({ ...doc, problem: e.target.value })}
                  rows={3}
                  className="w-full rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-[15px] text-ink focus:outline-2 focus:outline-violet"
                />
              </div>
              {meta && meta.versions.length > 1 && (
                <div>
                  <Label htmlFor="version-pick">Open a different version</Label>
                  <select
                    id="version-pick"
                    value={loadVersion ?? ""}
                    onChange={(e) => {
                      if (dirty && !window.confirm("Discard unsaved changes?")) return;
                      setVersion(Number(e.target.value));
                    }}
                    className="h-10 w-full rounded-(--radius-control) border border-hairline bg-surface px-3 text-[15px] text-ink"
                  >
                    {meta.versions.map((v) => (
                      <option key={v.version} value={v.version}>
                        Version {v.version}
                        {v.version === meta.published_version ? " (published)" : ""}
                      </option>
                    ))}
                  </select>
                  <p className="mt-1.5 text-[13px] text-ink-faint">
                    Open an older version and save it to roll an edit back.
                  </p>
                </div>
              )}
            </div>
          </Card>

          {selectedStep ? (
            <StepForm step={selectedStep} onChange={updateStep} />
          ) : (
            <Card>
              <p className="text-[15px] text-ink-faint">Select a step to edit it.</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
