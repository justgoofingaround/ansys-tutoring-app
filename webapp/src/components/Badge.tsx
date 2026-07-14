import { cn } from "./cn";

type Tone = "neutral" | "violet" | "success" | "warning" | "error";

const tones: Record<Tone, string> = {
  neutral: "bg-paper text-ink-soft border-hairline",
  violet: "bg-violet-tint text-violet border-violet/20",
  success: "bg-success-tint text-success border-success/20",
  warning: "bg-warning-tint text-warning border-warning/20",
  error: "bg-error-tint text-error border-error/20",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}
