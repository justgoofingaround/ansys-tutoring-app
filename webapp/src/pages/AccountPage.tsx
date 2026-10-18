import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { KeyRound, LogOut } from "lucide-react";
import { ApiError } from "@/lib/api";
import { useMe, useLogout, useChangePassword } from "@/auth/useMe";
import { Card, CardTitle } from "@/components/Card";
import { Button } from "@/components/Button";
import { Label, FieldError } from "@/components/Input";
import { PasswordInput } from "@/components/PasswordInput";
import { PageHeader } from "@/components/PageHeader";

/** Your account: who the Hub thinks you are, and the one setting you own.
 *
 * Shared by both roles — the surrounding chrome differs, the page does not. */
export function AccountPage() {
  const { data: me } = useMe();
  const change = useChangePassword();
  const logout = useLogout();
  const navigate = useNavigate();

  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [mismatch, setMismatch] = useState(false);
  const [done, setDone] = useState(false);

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (next !== confirm) {
      setMismatch(true);
      return;
    }
    setMismatch(false);
    change.mutate(
      { current_password: current, password: next },
      {
        onSuccess: () => {
          setDone(true);
          setCurrent("");
          setNext("");
          setConfirm("");
        },
      },
    );
  }

  function errorText(e: unknown): string {
    if (e instanceof ApiError) {
      if (e.code === "wrong_password") return "That isn't your current password.";
      if (e.code === "password_unchanged") return "Choose a password different from the current one.";
      if (e.status === 422) return "The new password must be at least 8 characters.";
    }
    return "Couldn't change the password. Try again.";
  }

  return (
    <>
      <PageHeader title="Your account" subtitle="Your details, and your password." />

      <div className="grid items-start gap-4 lg:grid-cols-2">
        <Card>
          <CardTitle>Details</CardTitle>
          <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-6 gap-y-3 text-[15px]">
            <dt className="text-ink-soft">Name</dt>
            <dd className="text-ink">{me?.username}</dd>
            {me?.section && (
              <>
                <dt className="text-ink-soft">Section</dt>
                <dd className="text-ink">{me.section}</dd>
              </>
            )}
            <dt className="text-ink-soft">Role</dt>
            <dd className="text-ink capitalize">{me?.role}</dd>
          </dl>
          <Button
            variant="secondary"
            className="mt-5"
            loading={logout.isPending}
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
          >
            <LogOut className="size-4" /> Sign out
          </Button>
        </Card>

        <Card>
          <div className="flex items-center gap-2">
            <KeyRound className="size-5 text-violet" />
            <CardTitle>Change password</CardTitle>
          </div>
          <p className="mt-2 text-[14px] leading-relaxed text-ink-soft">
            Signing in elsewhere ends when you change this. Every other session is signed
            out, and this one stays.
          </p>

          <form onSubmit={submit} className="mt-4 space-y-4">
            <div>
              <Label htmlFor="current-password">Current password</Label>
              <PasswordInput
                id="current-password"
                value={current}
                onChange={(e) => {
                  setCurrent(e.target.value);
                  setDone(false);
                }}
                autoComplete="current-password"
                required
              />
            </div>
            <div>
              <Label htmlFor="new-password">New password</Label>
              <PasswordInput
                id="new-password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                autoComplete="new-password"
                minLength={8}
                required
              />
              <p className="mt-1.5 text-[13px] text-ink-faint">At least 8 characters.</p>
            </div>
            <div>
              <Label htmlFor="confirm-new-password">Confirm new password</Label>
              <PasswordInput
                id="confirm-new-password"
                value={confirm}
                onChange={(e) => {
                  setConfirm(e.target.value);
                  setMismatch(false);
                }}
                autoComplete="new-password"
                minLength={8}
                required
              />
              {mismatch && <FieldError>Those passwords don't match.</FieldError>}
            </div>

            <FieldError>{change.error ? errorText(change.error) : null}</FieldError>
            {done && (
              <p className="text-[14px] font-medium text-success">Password changed.</p>
            )}

            <Button type="submit" loading={change.isPending}>
              Change password
            </Button>
          </form>

          <p className="mt-4 text-[13px] text-ink-faint">
            Forgotten it instead? Sign out and use <strong>Forgot your password?</strong> on
            the sign-in page. The link goes to your NYU address.
          </p>
        </Card>
      </div>
    </>
  );
}
