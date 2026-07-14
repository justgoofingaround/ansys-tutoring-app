import { cn } from "./cn";

export function Spinner({ className }: { className?: string }) {
  return (
    <span
      className={cn(
        "inline-block size-5 animate-spin rounded-full border-2 border-hairline border-t-violet",
        className,
      )}
      role="status"
      aria-label="Loading"
    />
  );
}
