import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ChevronDown, ChevronUp, Plus, Save, Trash2, TriangleAlert } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import type { ValidationFinding } from "@/types/api";
import { PageHeader } from "@/components/PageHeader";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Input, Label } from "@/components/Input";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";
import { FindingsList } from "./TutorialLibraryPage";

interface EditableQuestion {
  text: string;
  options: string[];
  correct_index: number;
  concept_tag: string;
  explanation: string;
}

interface EditableQuiz {
  quiz_id: string;
  tutorial_id: string;
  title: string;
  questions: EditableQuestion[];
}

/** The editor posts the authoring shape, so question_id and position are
 * dropped — positions are re-derived from array order on save. */
function toEditable(loaded: {
  quiz_id: string;
  tutorial_id: string;
  title: string;
  questions: {
    text: string;
    options: string[];
    correct_index?: number;
    concept_tag?: string;
    explanation?: string;
  }[];
}): EditableQuiz {
  return {
    quiz_id: loaded.quiz_id,
    tutorial_id: loaded.tutorial_id,
    title: loaded.title,
    questions: loaded.questions.map((q) => ({
      text: q.text,
      options: [...q.options],
      correct_index: q.correct_index ?? 0,
      concept_tag: q.concept_tag ?? "",
      explanation: q.explanation ?? "",
    })),
  };
}

export function QuizEditorPage() {
  const { quizId = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const { data: loaded, isPending, error: loadError } = useQuery({
    queryKey: ["instructor", "quiz-content", quizId],
    queryFn: () => apiFetch<Parameters<typeof toEditable>[0]>(
      `/api/instructor/quizzes/${quizId}/content`,
    ),
  });

  const [quiz, setQuiz] = useState<EditableQuiz | null>(null);
  const [selected, setSelected] = useState(0);
  const [dirty, setDirty] = useState(false);
  const [findings, setFindings] = useState<ValidationFinding[] | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    if (loaded && !quiz) setQuiz(toEditable(loaded));
  }, [loaded, quiz]);

  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const save = useMutation({
    // Raw fetch: a 422 carries {detail: {findings: [...]}}, and apiFetch keeps
    // only string details, so the findings would be lost.
    mutationFn: async () => {
      const res = await fetch(`/api/instructor/quizzes/${quizId}/content`, {
        method: "POST",
        credentials: "same-origin",
      cache: "no-store",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(quiz),
      });
      const body = await res.json().catch(() => null);
      if (!res.ok) {
        throw {
          findings: (body?.detail?.findings as ValidationFinding[] | undefined) ?? [
            { severity: "error", where: "quiz", message: `Save failed (${res.status}).` },
          ],
        };
      }
      return body as { warnings: ValidationFinding[] };
    },
    onSuccess: (res) => {
      setDirty(false);
      setSavedAt(Date.now());
      setFindings(res.warnings?.length ? res.warnings : null);
      qc.invalidateQueries({ queryKey: ["instructor", "quiz-stats"] });
      qc.invalidateQueries({ queryKey: ["instructor", "quiz-content", quizId] });
    },
    onError: (e: { findings?: ValidationFinding[] }) =>
      setFindings(e.findings ?? [{ severity: "error", where: "quiz", message: "Save failed." }]),
  });

  function update(next: EditableQuiz) {
    setQuiz(next);
    setDirty(true);
    setSavedAt(null);
  }

  function updateQuestion(idx: number, next: EditableQuestion) {
    if (!quiz) return;
    update({ ...quiz, questions: quiz.questions.map((q, i) => (i === idx ? next : q)) });
  }

  function moveQuestion(idx: number, delta: number) {
    if (!quiz) return;
    const target = idx + delta;
    if (target < 0 || target >= quiz.questions.length) return;
    const questions = [...quiz.questions];
    [questions[idx], questions[target]] = [questions[target], questions[idx]];
    update({ ...quiz, questions });
    setSelected(target);
  }

  function deleteQuestion(idx: number) {
    if (!quiz) return;
    if (quiz.questions.length === 1) {
      setFindings([
        { severity: "error", where: "quiz", message: "A quiz needs at least one question." },
      ]);
      return;
    }
    if (!window.confirm("Delete this question? Past submissions keep their scores.")) return;
    update({ ...quiz, questions: quiz.questions.filter((_, i) => i !== idx) });
    setSelected((s) => Math.max(0, Math.min(s, quiz.questions.length - 2)));
  }

  function addQuestion() {
    if (!quiz) return;
    update({
      ...quiz,
      questions: [
        ...quiz.questions,
        {
          text: "New question?",
          options: ["", ""],
          correct_index: 0,
          concept_tag: "",
          explanation: "",
        },
      ],
    });
    setSelected(quiz.questions.length);
  }

  if (loadError) {
    // Without this the page spun forever on a 404 — which is what a server
    // started before this endpoint existed returns.
    const notFound = loadError instanceof ApiError && loadError.status === 404;
    return (
      <>
        <PageHeader title="Quiz editor" subtitle={quizId} />
        <Card className="border-error/30">
          <CardTitle>Couldn't open this quiz</CardTitle>
          <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
            {notFound
              ? "The server has no quiz with this id, or it is running an older build that predates the quiz editor — restart it and try again."
              : "The quiz could not be loaded. Try reloading the page; if it keeps failing, sign out and back in."}
          </p>
          {/* The exact failure, so a report says what went wrong rather than
            * "it does not work" — a stale cached error and a 403 look identical
            * from the outside. */}
          <p className="mt-2 font-mono text-[12px] text-ink-faint">
            {loadError instanceof ApiError
              ? `HTTP ${loadError.status} · ${loadError.code}`
              : String((loadError as Error)?.message ?? loadError)}
          </p>
          <div className="mt-4 flex gap-2">
            <Button onClick={() => window.location.reload()}>Reload</Button>
            <Button variant="secondary" onClick={() => navigate("/instructor/quizzes")}>
              <ArrowLeft className="size-4" /> Back to quizzes
            </Button>
          </div>
        </Card>
      </>
    );
  }

  if (isPending || !quiz) {
    return (
      <div className="flex justify-center py-16">
        <Spinner />
      </div>
    );
  }

  const q = quiz.questions[selected];

  return (
    <>
      <PageHeader
        title={quiz.title}
        subtitle={`${quiz.questions.length} question${quiz.questions.length === 1 ? "" : "s"} · ${quiz.tutorial_id}`}
        actions={
          <div className="flex items-center gap-2">
            {dirty && (
              <span className="flex items-center gap-1.5 text-[13px] text-warning">
                <TriangleAlert className="size-4" /> Unsaved changes
              </span>
            )}
            {savedAt && !dirty && (
              <span className="text-[13px] text-success">Saved — students see it now</span>
            )}
            <Button variant="ghost" onClick={() => navigate("/instructor/quizzes")}>
              <ArrowLeft className="size-4" /> Quizzes
            </Button>
            <Button loading={save.isPending} disabled={!dirty} onClick={() => save.mutate()}>
              <Save className="size-4" /> Save
            </Button>
          </div>
        }
      />

      <Card className="mb-4">
        <p className="text-[13px] text-ink-faint">
          Saving replaces the quiz immediately — quizzes have no draft step. Past submissions
          keep the score they were given.
        </p>
      </Card>

      {findings && (
        <Card className="mb-4 border-error/30">
          <CardTitle>Could not save</CardTitle>
          <FindingsList findings={findings} />
        </Card>
      )}

      <div className="grid items-start gap-4 xl:grid-cols-[300px_1fr]">
        <Card>
          <div className="flex items-center justify-between">
            <CardTitle>Questions</CardTitle>
            <Badge tone="violet">{quiz.questions.length}</Badge>
          </div>
          <ul className="mt-3 space-y-0.5">
            {quiz.questions.map((question, idx) => (
              <li key={idx} className="group flex items-center gap-1">
                <button
                  onClick={() => setSelected(idx)}
                  className={cn(
                    "min-w-0 flex-1 truncate rounded-(--radius-control) px-2 py-1.5 text-left text-[14px]",
                    selected === idx
                      ? "bg-violet-tint text-violet"
                      : "text-ink-soft hover:bg-paper hover:text-ink",
                  )}
                >
                  <span className="mr-1.5 font-mono text-[11px] text-ink-faint">{idx + 1}</span>
                  {question.text || "(empty)"}
                </button>
                <div className="flex shrink-0 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    onClick={() => moveQuestion(idx, -1)}
                    title="Move up"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-ink"
                  >
                    <ChevronUp className="size-3.5" />
                  </button>
                  <button
                    onClick={() => moveQuestion(idx, 1)}
                    title="Move down"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-ink"
                  >
                    <ChevronDown className="size-3.5" />
                  </button>
                  <button
                    onClick={() => deleteQuestion(idx)}
                    title="Delete question"
                    className="inline-flex size-6 items-center justify-center text-ink-faint hover:text-error"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
          <Button variant="secondary" className="mt-3 w-full" onClick={addQuestion}>
            <Plus className="size-4" /> Add question
          </Button>
        </Card>

        <div className="space-y-4">
          <Card>
            <CardTitle>Quiz</CardTitle>
            <div className="mt-3">
              <Label htmlFor="quiz-title">Title</Label>
              <Input
                id="quiz-title"
                value={quiz.title}
                onChange={(e) => update({ ...quiz, title: e.target.value })}
              />
            </div>
          </Card>

          <Card>
            <CardTitle>Question {selected + 1}</CardTitle>
            <div className="mt-3 space-y-4">
              <div>
                <Label htmlFor="q-text">Question</Label>
                <textarea
                  id="q-text"
                  value={q.text}
                  onChange={(e) => updateQuestion(selected, { ...q, text: e.target.value })}
                  rows={2}
                  className="w-full rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-[15px] text-ink focus:outline-2 focus:outline-violet"
                />
              </div>

              <div>
                <Label>Options — select the correct answer</Label>
                <div className="space-y-2">
                  {q.options.map((opt, oi) => (
                    <div key={oi} className="flex items-center gap-2">
                      <input
                        type="radio"
                        name="correct"
                        checked={q.correct_index === oi}
                        onChange={() => updateQuestion(selected, { ...q, correct_index: oi })}
                        title="Mark as the correct answer"
                        className="size-4 accent-violet"
                      />
                      <Input
                        value={opt}
                        onChange={(e) => {
                          const options = [...q.options];
                          options[oi] = e.target.value;
                          updateQuestion(selected, { ...q, options });
                        }}
                      />
                      <Button
                        variant="ghost"
                        title="Remove option"
                        disabled={q.options.length <= 2}
                        onClick={() => {
                          const options = q.options.filter((_, i) => i !== oi);
                          // Keep the answer pointing at the same option.
                          const correct =
                            q.correct_index === oi
                              ? 0
                              : q.correct_index > oi
                                ? q.correct_index - 1
                                : q.correct_index;
                          updateQuestion(selected, { ...q, options, correct_index: correct });
                        }}
                      >
                        <Trash2 className="size-4" />
                      </Button>
                    </div>
                  ))}
                  <Button
                    variant="secondary"
                    onClick={() =>
                      updateQuestion(selected, { ...q, options: [...q.options, ""] })
                    }
                  >
                    <Plus className="size-4" /> Add option
                  </Button>
                </div>
              </div>

              <div>
                <Label htmlFor="q-explanation">Explanation</Label>
                <textarea
                  id="q-explanation"
                  value={q.explanation}
                  onChange={(e) =>
                    updateQuestion(selected, { ...q, explanation: e.target.value })
                  }
                  rows={3}
                  className="w-full rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-[15px] text-ink focus:outline-2 focus:outline-violet"
                />
                <p className="mt-1.5 text-[13px] text-ink-faint">
                  Shown to the student after they commit an answer.
                </p>
              </div>

              <div>
                <Label htmlFor="q-concept">Concept tag</Label>
                <Input
                  id="q-concept"
                  value={q.concept_tag}
                  onChange={(e) =>
                    updateQuestion(selected, { ...q, concept_tag: e.target.value })
                  }
                  placeholder="e.g. meshing"
                />
                <p className="mt-1.5 text-[13px] text-ink-faint">
                  Groups questions in the by-concept results.
                </p>
              </div>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
