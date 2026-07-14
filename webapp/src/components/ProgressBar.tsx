import { cn } from "./cn";

/** Segmented per-step progress — one thin segment per step, filled when
 * complete. The signature element of the step-driven domain. Falls back to
 * a continuous bar when there are too many segments to read. */
export function ProgressBar({
  total,
  completed,
  className,
}: {
  total: number;
  completed: number;
  className?: string;
}) {
  if (total <= 0) return null;
  if (total > 40) {
    const pct = Math.round((completed / total) * 100);
    return (
      <div className={cn("h-1.5 w-full overflow-hidden rounded-full bg-hairline", className)}>
        <div className="h-full rounded-full bg-violet" style={{ width: `${pct}%` }} />
      </div>
    );
  }
  return (
    <div className={cn("flex w-full gap-[3px]", className)} aria-label={`${completed} of ${total} steps complete`}>
      {Array.from({ length: total }, (_, i) => (
        <span
          key={i}
          className={cn(
            "h-1.5 flex-1 rounded-[2px]",
            i < completed ? "bg-violet" : "bg-hairline",
          )}
        />
      ))}
    </div>
  );
}
