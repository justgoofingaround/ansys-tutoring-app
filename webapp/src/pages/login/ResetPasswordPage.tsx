import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useResetPassword } from "@/auth/useMe";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/Button";
import { Label, FieldError } from "@/components/Input";
import { PasswordInput } from "@/components/PasswordInput";

/** Landing page for the emailed reset link. The reset revokes every existing
 * session, so it deliberately does not sign the student in — they sign in with
 * the new password, which also confirms they remember it. */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const reset = useResetPassword();
  const token = params.get("token") ?? "";

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    reset.mutate({ token, password });
  }

  if (!token) {
    return (
      <div className="mx-auto mt-24 max-w-md px-6 text-center">
        <AlertTriangle className="mx-auto size-8 text-error" />
        <h1 className="mt-3 font-serif text-[20px] font-semibold text-ink">
          This link is incomplete
        </h1>
        <p className="mt-2 text-[15px] text-ink-soft">
          Open the link from your email, or request a new one from the sign-in page.
        </p>
        <Button className="mt-5 w-full" onClick={() => navigate("/login")}>
          Back to sign in
        </Button>
      </div>
    );
  }

  if (reset.isSuccess) {
    return (
      <div className="mx-auto mt-24 max-w-md px-6 text-center">
        <CheckCircle2 className="mx-auto size-8 text-success" />
        <h1 className="mt-3 font-serif text-[20px] font-semibold text-ink">Password changed</h1>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
          You've been signed out everywhere else. Sign in with your new password.
        </p>
        <Button className="mt-5 w-full" onClick={() => navigate("/login")}>
          Go to sign in
        </Button>
      </div>
    );
  }

  const expired =
    reset.error instanceof ApiError && reset.error.code === "invalid_or_expired_token";

  return (
    <div className="mx-auto mt-24 max-w-md px-6">
      <h1 className="font-serif text-[20px] font-semibold text-ink">Choose a new password</h1>
      <form onSubmit={submit} className="mt-5 space-y-4">
        <div>
          <Label htmlFor="new-password">New password</Label>
          <PasswordInput
            id="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="new-password"
            autoFocus
            required
            minLength={8}
          />
          <p className="mt-1.5 text-[13px] text-ink-faint">At least 8 characters.</p>
        </div>
        <div>
          <Label htmlFor="confirm-password">Confirm new password</Label>
          <PasswordInput
            id="confirm-password"
            value={confirm}
            onChange={(e) => {
              setConfirm(e.target.value);
              setMismatch(false);
            }}
            autoComplete="new-password"
            required
            minLength={8}
          />
          {mismatch && <FieldError>Those passwords don't match.</FieldError>}
        </div>
        <FieldError>
          {reset.error
            ? expired
              ? "That link has expired or was already used. Request a new one from the sign-in page."
              : "Something went wrong — try again."
            : null}
        </FieldError>
        <Button type="submit" loading={reset.isPending} className="w-full">
          {reset.isPending ? "Saving…" : "Save new password"}
        </Button>
        <button
          type="button"
          onClick={() => navigate("/login")}
          className="w-full text-center text-[14px] text-violet hover:underline"
        >
          Back to sign in
        </button>
      </form>
    </div>
  );
}
