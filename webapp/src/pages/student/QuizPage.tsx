import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, Check, ChevronRight, RotateCcw, X } from "lucide-react";
import { apiFetch } from "@/lib/api";
import type {
  QuizCheckResult,
  QuizData,
  QuizSubmissionResult,
  TutorialDetailData,
} from "@/types/api";
import { Card, CardTitle } from "@/components/Card";
import { Badge } from "@/components/Badge";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

/* ── one selectable option row ──────────────────────────────────────── */

function OptionRow({
  text,
  index,
  selected,
  checked,
  onSelect,
}: {
  text: string;
  index: number;
  selected: boolean;
  checked: QuizCheckResult | null;
  onSelect: () => void;
}) {
  const isCorrect = checked !== null && index === checked.correct_index;
  const isWrongChoice = checked !== null && selected && !checked.correct;
  return (
    <button
      onClick={onSelect}
      disabled={checked !== null}
      className={cn(
        "flex w-full items-center gap-3 rounded-(--radius-control) border px-4 py-3 text-left text-[15px] transition-colors",
        checked === null &&
          (selected
            ? "border-violet bg-violet-tint text-ink"
            : "border-hairline bg-surface text-ink hover:border-ink-faint"),
        isCorrect && "border-success bg-success-tint text-ink",
        isWrongChoice && "border-error bg-error-tint text-ink",
        checked !== null && !isCorrect && !isWrongChoice && "border-hairline bg-surface text-ink-faint",
        checked !== null && "cursor-default",
      )}
    >
      <span
        className={cn(
          "flex size-6 shrink-0 items-center justify-center rounded-full border font-mono text-[13px]",
          checked === null && (selected ? "border-violet text-violet" : "border-hairline text-ink-faint"),
          isCorrect && "border-success bg-success text-white",
          isWrongChoice && "border-error bg-error text-white",
          checked !== null && !isCorrect && !isWrongChoice && "border-hairline text-ink-faint",
        )}
      >
        {isCorrect ? <Check className="size-4" /> : isWrongChoice ? <X className="size-4" /> : String.fromCharCode(65 + index)}
      </span>
      <span>{text}</span>
    </button>
  );
}

/* ── result screen ──────────────────────────────────────────────────── */

function ConceptBar({ tag, correct, total }: { tag: string; correct: number; total: number }) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-mono text-[13px] text-ink">{tag}</span>
        <span className="text-[13px] text-ink-soft">
          {correct}/{total}
        </span>
      </div>
      <div className="flex h-2 gap-0.5 overflow-hidden rounded-full">
        {Array.from({ length: total }, (_, i) => (
          <div
            key={i}
            className={cn("h-full flex-1", i < correct ? "bg-success" : "bg-hairline")}
          />
        ))}
      </div>
    </div>
  );
}

function ResultScreen({
  quiz,
  result,
  tutorialId,
  onRetake,
}: {
  quiz: QuizData;
  result: QuizSubmissionResult;
  tutorialId: string;
  onRetake: () => void;
}) {
  const questionText = new Map(quiz.questions.map((q) => [q.question_id, q.text]));
  const pct = Math.round(result.score * 100);
  return (
    <div className="mx-auto max-w-2xl space-y-4">
      <Card className="text-center">
        <div className="font-serif text-[15px] text-ink-soft">Attempt {result.attempt}</div>
        <div className="mt-1 font-serif text-5xl font-semibold text-ink">
          {result.correct_count}
          <span className="text-ink-faint"> / {result.total}</span>
        </div>
        <div className={cn("mt-2 text-sm font-medium", pct === 100 ? "text-success" : "text-ink-soft")}>
          {pct === 100 ? "Perfect score" : `${pct}% correct`}
        </div>
      </Card>

      <Card>
        <CardTitle>By concept</CardTitle>
        <div className="mt-3 space-y-3">
          {Object.entries(result.by_concept).map(([tag, c]) => (
            <ConceptBar key={tag} tag={tag} correct={c.correct} total={c.total} />
          ))}
        </div>
      </Card>

      <Card>
        <CardTitle>Question review</CardTitle>
        <ul className="mt-2 divide-y divide-hairline">
          {result.per_question.map((p) => (
            <li key={p.question_id} className="flex gap-3 py-3">
              <span
                className={cn(
                  "mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full text-white",
                  p.correct ? "bg-success" : "bg-error",
                )}
              >
                {p.correct ? <Check className="size-3.5" /> : <X className="size-3.5" />}
              </span>
              <div className="min-w-0">
                <div className="text-sm text-ink">{questionText.get(p.question_id)}</div>
                {!p.correct && (
                  <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">{p.explanation}</p>
                )}
              </div>
            </li>
          ))}
        </ul>
      </Card>

      <div className="flex justify-center gap-2">
        <Button variant="secondary" onClick={onRetake}>
          <RotateCcw className="size-4" /> Retake quiz
        </Button>
        <Link
          to={`/tutorials/${tutorialId}`}
          className="inline-flex h-10 items-center gap-2 rounded-(--radius-control) bg-violet px-4 text-[15px] font-medium text-white transition-colors hover:bg-violet-hover"
        >
          Back to tutorial
        </Link>
      </div>
    </div>
  );
}

/* ── the quiz flow ──────────────────────────────────────────────────── */

export function QuizPage() {
  const { tutorialId = "" } = useParams();
  const qc = useQueryClient();

  const { data: detail } = useQuery({
    queryKey: ["student", "tutorial", tutorialId],
    queryFn: () => apiFetch<TutorialDetailData>(`/api/student/tutorials/${tutorialId}`),
  });
  const quizId = detail?.quiz?.quiz_id;

  const { data: quiz, isPending } = useQuery({
    queryKey: ["quiz", quizId],
    queryFn: () => apiFetch<QuizData>(`/api/quizzes/${quizId}`),
    enabled: !!quizId,
  });

  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<number[]>([]);
  const [selected, setSelected] = useState<number | null>(null);
  const [checked, setChecked] = useState<QuizCheckResult | null>(null);
  const [result, setResult] = useState<QuizSubmissionResult | null>(null);

  const check = useMutation({
    mutationFn: (choice: number) =>
      apiFetch<QuizCheckResult>(`/api/quizzes/${quizId}/check`, {
        json: { question_id: quiz!.questions[index].question_id, choice_index: choice },
      }),
    onSuccess: setChecked,
  });

  const submit = useMutation({
    mutationFn: (all: number[]) =>
      apiFetch<QuizSubmissionResult>(`/api/quizzes/${quizId}/submissions`, {
        json: { answers: all },
      }),
    onSuccess: (r) => {
      setResult(r);
      // Dashboard + detail percent/status include the quiz milestone now.
      qc.invalidateQueries({ queryKey: ["student"] });
    },
  });

  function restart() {
    setIndex(0);
    setAnswers([]);
    setSelected(null);
    setChecked(null);
    setResult(null);
  }

  if (detail && detail.quiz === null) {
    return (
      <Card className="mx-auto max-w-lg text-center">
        <CardTitle>No quiz for this tutorial</CardTitle>
        <Link to={`/tutorials/${tutorialId}`} className="mt-3 inline-block text-sm font-medium text-violet">
          Back to tutorial
        </Link>
      </Card>
    );
  }
  if (isPending || !quiz) return <Spinner className="mx-auto my-16 size-6" />;

  if (result) {
    return <ResultScreen quiz={quiz} result={result} tutorialId={tutorialId} onRetake={restart} />;
  }

  const q = quiz.questions[index];
  const isLast = index === quiz.questions.length - 1;

  function next() {
    const all = [...answers, selected!];
    setAnswers(all);
    if (isLast) {
      submit.mutate(all);
    } else {
      setIndex(index + 1);
      setSelected(null);
      setChecked(null);
    }
  }

  return (
    <div className="mx-auto max-w-2xl">
      <Link
        to={`/tutorials/${tutorialId}`}
        className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-ink-soft hover:text-ink"
      >
        <ArrowLeft className="size-4" /> {detail?.title ?? "Tutorial"}
      </Link>

      <div className="mb-4 flex items-center justify-between">
        <h1 className="font-serif text-[22px] font-semibold text-ink">{quiz.title}</h1>
        <span className="font-mono text-sm text-ink-soft">
          {index + 1} / {quiz.questions.length}
        </span>
      </div>
      <div className="mb-6 flex h-1.5 gap-1 overflow-hidden rounded-full">
        {quiz.questions.map((qq, i) => (
          <div
            key={qq.question_id}
            className={cn(
              "h-full flex-1 rounded-full",
              i < index ? "bg-violet" : i === index ? "bg-violet/40" : "bg-hairline",
            )}
          />
        ))}
      </div>

      <Card>
        <div className="mb-1 flex items-center gap-2">
          <Badge className="font-mono">{q.concept_tag}</Badge>
        </div>
        <p className="text-[17px] leading-relaxed text-ink">{q.text}</p>
        <div className="mt-4 space-y-2">
          {q.options.map((opt, i) => (
            <OptionRow
              key={i}
              text={opt}
              index={i}
              selected={selected === i}
              checked={checked}
              onSelect={() => checked === null && setSelected(i)}
            />
          ))}
        </div>

        {checked && (
          <div
            className={cn(
              "mt-4 rounded-(--radius-control) border px-4 py-3",
              checked.correct ? "border-success/40 bg-success-tint" : "border-error/40 bg-error-tint",
            )}
          >
            <div className={cn("text-sm font-semibold", checked.correct ? "text-success" : "text-error")}>
              {checked.correct ? "Correct" : "Not quite"}
            </div>
            <p className="mt-1 text-sm leading-relaxed text-ink-soft">{checked.explanation}</p>
          </div>
        )}

        <div className="mt-5 flex justify-end">
          {checked === null ? (
            <Button
              disabled={selected === null}
              loading={check.isPending}
              onClick={() => check.mutate(selected!)}
            >
              Check answer
            </Button>
          ) : (
            <Button loading={submit.isPending} onClick={next}>
              {isLast ? "See results" : "Next question"} <ChevronRight className="size-4" />
            </Button>
          )}
        </div>
      </Card>
    </div>
  );
}
