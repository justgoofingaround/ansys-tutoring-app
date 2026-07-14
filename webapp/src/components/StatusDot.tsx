import { Check, X } from "lucide-react";
import type { StepStatus } from "@/types/api";
import { cn } from "./cn";

export function StatusDot({ status }: { status: StepStatus }) {
  if (status === "completed") {
    return (
      <span className="inline-flex size-[18px] items-center justify-center rounded-full bg-success text-white">
        <Check className="size-3" strokeWidth={3} />
      </span>
    );
  }
  if (status === "struggling") {
    return (
      <span className="inline-flex size-[18px] items-center justify-center rounded-full bg-error-tint text-error">
        <X className="size-3" strokeWidth={3} />
      </span>
    );
  }
  return (
    <span
      className={cn(
        "inline-block size-[18px] rounded-full border-2",
        status === "attempted" ? "border-violet bg-violet-tint" : "border-hairline bg-surface",
      )}
    />
  );
}
