import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Input } from "./Input";
import { cn } from "./cn";

/** Password field with a show/hide toggle. Typing a password you cannot see is
 * the usual cause of "wrong password" on a first sign-in. */
export function PasswordInput({
  className,
  ...props
}: React.InputHTMLAttributes<HTMLInputElement>) {
  const [shown, setShown] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={shown ? "text" : "password"} className={cn("pr-10", className)} />
      <button
        type="button"
        tabIndex={-1}
        onClick={() => setShown((v) => !v)}
        aria-label={shown ? "Hide password" : "Show password"}
        title={shown ? "Hide password" : "Show password"}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-ink-faint transition-colors hover:text-ink"
      >
        {shown ? <EyeOff className="size-4" /> : <Eye className="size-4" />}
      </button>
    </div>
  );
}
