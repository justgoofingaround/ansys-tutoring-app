import { forwardRef } from "react";
import { cn } from "./cn";
import { Spinner } from "./Spinner";

type Variant = "primary" | "secondary" | "ghost" | "destructive";

const variants: Record<Variant, string> = {
  primary:
    "bg-violet text-white hover:bg-violet-hover focus-visible:outline-violet border border-transparent",
  secondary:
    "bg-surface text-ink border border-hairline hover:border-ink-faint focus-visible:outline-violet",
  ghost:
    "bg-transparent text-ink-soft hover:bg-violet-tint hover:text-ink border border-transparent",
  destructive:
    "bg-surface text-error border border-error/40 hover:bg-error-tint focus-visible:outline-error",
};

export interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  loading?: boolean;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "primary", loading, className, children, disabled, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex h-10 items-center justify-center gap-2 rounded-(--radius-control) px-4 text-[15px] font-medium",
        "transition-colors duration-150 focus-visible:outline-2 focus-visible:outline-offset-2",
        "disabled:cursor-not-allowed disabled:opacity-55",
        variants[variant],
        className,
      )}
      {...props}
    >
      {loading && <Spinner className="size-4 border-white/40 border-t-white" />}
      {children}
    </button>
  );
});
