import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { MailCheck } from "lucide-react";
import {
  useForgotPassword,
  useLogin,
  useRegister,
  useResendVerification,
} from "@/auth/useMe";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/Button";
import { Input, Label, FieldError } from "@/components/Input";
import { PasswordInput } from "@/components/PasswordInput";
import { cn } from "@/components/cn";

const ERROR_TEXT: Record<string, string> = {
  bad_credentials: "Wrong email or password.",
  not_on_roster:
    "That address isn't on the class list — check you used your NYU email, or ask your instructor to add you.",
  already_claimed:
    "An account already exists for that address. Sign in instead, or use the confirmation link you were sent.",
  email_not_verified: "Confirm your email first — open the link we sent you.",
};

function errorText(e: unknown): string {
  if (e instanceof ApiError) return ERROR_TEXT[e.code] ?? `Something went wrong (${e.code}).`;
  return "Can't reach the server — is it running?";
}

/** Shared "we've emailed you" panel — same shape for confirmation and reset. */
function SentPanel({
  title,
  body,
  onResend,
  resending,
  resent,
}: {
  title: string;
  body: React.ReactNode;
  onResend: () => void;
  resending: boolean;
  resent: boolean;
}) {
  return (
    <div className="mt-5 space-y-3">
      <div className="flex items-center gap-2 text-ink">
        <MailCheck className="size-5 text-violet" />
        <span className="text-[15px] font-medium">{title}</span>
      </div>
      <p className="text-[15px] leading-relaxed text-ink-soft">{body}</p>
      <p className="text-[13px] text-ink-faint">
        The link only opens on the NYU network, so use a lab computer or connect to the VPN.
      </p>
      <Button variant="secondary" className="w-full" loading={resending} onClick={onResend}>
        {resent ? "Sent again" : "Send it again"}
      </Button>
    </div>
  );
}

export function StudentAuthForm() {
  const [tab, setTab] = useState<"signin" | "register">("signin");
  const [forgotMode, setForgotMode] = useState(false);
  const navigate = useNavigate();
  const login = useLogin();
  const register = useRegister();
  const resend = useResendVerification();
  const forgot = useForgotPassword();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [sent, setSent] = useState<
    null | { kind: "verify" | "reset"; email: string; mailed: boolean }
  >(null);

  const pending = login.isPending || register.isPending || forgot.isPending;
  const error = forgotMode ? forgot.error : tab === "signin" ? login.error : register.error;

  function switchTab(key: "signin" | "register") {
    setTab(key);
    setForgotMode(false);
    setSent(null);
    setMismatch(false);
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const addr = email.trim();
    if (forgotMode) {
      forgot.mutate(
        { email: addr },
        { onSuccess: () => setSent({ kind: "reset", email: addr, mailed: true }) },
      );
      return;
    }
    if (tab === "signin") {
      login.mutate({ username: addr, password }, { onSuccess: () => navigate("/dashboard") });
      return;
    }
    if (password !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    register.mutate(
      { email: addr, password },
      {
        // status "created" = the account exists but the server could not send
        // the email, so say that instead of promising a message.
        onSuccess: (res) =>
          setSent({ kind: "verify", email: addr, mailed: res.status === "verification_sent" }),
      },
    );
  }

  if (sent) {
    const isReset = sent.kind === "reset";

    if (!sent.mailed) {
      return (
        <div className="mt-5 space-y-3">
          <div className="flex items-center gap-2 text-ink">
            <MailCheck className="size-5 text-warning" />
            <span className="text-[15px] font-medium">Account created</span>
          </div>
          <p className="text-[15px] leading-relaxed text-ink-soft">
            Your account for <strong className="text-ink">{sent.email}</strong> is set up, but we
            couldn't send the confirmation email just now. Ask your instructor to confirm your
            account — they can do it from the class list — then sign in with the password you
            just chose.
          </p>
          <Button variant="secondary" className="w-full" onClick={() => setSent(null)}>
            Back to sign in
          </Button>
        </div>
      );
    }
    return (
      <div>
        <SentPanel
          title={isReset ? "Check your email" : "Confirm your email"}
          body={
            isReset ? (
              <>
                If an account exists for <strong className="text-ink">{sent.email}</strong>, we've
                sent a link to choose a new password. It expires in 2 hours.
              </>
            ) : (
              <>
                We sent a confirmation link to <strong className="text-ink">{sent.email}</strong>.
                Open it to finish setting up your account — it works once and expires in 48 hours.
              </>
            )
          }
          onResend={() =>
            isReset ? forgot.mutate({ email: sent.email }) : resend.mutate({ email: sent.email })
          }
          resending={isReset ? forgot.isPending : resend.isPending}
          resent={isReset ? forgot.isSuccess : resend.isSuccess}
        />
        <button
          onClick={() => {
            setSent(null);
            setForgotMode(false);
          }}
          className="mt-4 text-[14px] text-violet hover:underline"
        >
          Back to sign in
        </button>
      </div>
    );
  }

  return (
    <div>
      <div className="flex gap-5 border-b border-hairline">
        {(
          [
            { key: "signin", label: "Sign in" },
            { key: "register", label: "First time? Register" },
          ] as const
        ).map(({ key, label }) => (
          <button
            key={key}
            onClick={() => switchTab(key)}
            className={cn(
              "-mb-px border-b-2 pb-2 text-[15px] font-medium transition-colors",
              tab === key
                ? "border-violet text-violet"
                : "border-transparent text-ink-soft hover:text-ink",
            )}
          >
            {label}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="mt-5 space-y-4">
        {forgotMode && (
          <p className="text-[15px] leading-relaxed text-ink-soft">
            Enter your NYU email and we'll send you a link to choose a new password.
          </p>
        )}

        <div>
          <Label htmlFor="email">NYU email</Label>
          <Input
            id="email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="netid@nyu.edu"
            autoComplete="email"
            autoFocus
            required
          />
          {tab === "register" && !forgotMode && (
            <p className="mt-1.5 text-[13px] leading-snug text-ink-faint">
              Use the address your instructor has for you — only students on the class list can
              register. Your instructor sees your name; logs use an anonymous token.
            </p>
          )}
        </div>

        {!forgotMode && (
          <div>
            <Label htmlFor="password">Password</Label>
            <PasswordInput
              id="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={tab === "register" ? "new-password" : "current-password"}
              required
              minLength={tab === "register" ? 8 : undefined}
            />
            {tab === "register" && (
              <p className="mt-1.5 text-[13px] text-ink-faint">At least 8 characters.</p>
            )}
          </div>
        )}

        {tab === "register" && !forgotMode && (
          <div>
            <Label htmlFor="confirm">Confirm password</Label>
            <PasswordInput
              id="confirm"
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
        )}

        <FieldError>{error ? errorText(error) : null}</FieldError>

        <Button type="submit" loading={pending} className="w-full">
          {forgotMode
            ? pending
              ? "Sending…"
              : "Send reset link"
            : tab === "signin"
              ? pending
                ? "Signing in…"
                : "Sign in"
              : pending
                ? "Creating account…"
                : "Create account"}
        </Button>

        {tab === "signin" && (
          <button
            type="button"
            onClick={() => setForgotMode((v) => !v)}
            className="w-full text-center text-[14px] text-violet hover:underline"
          >
            {forgotMode ? "Back to sign in" : "Forgot your password?"}
          </button>
        )}
      </form>
    </div>
  );
}
