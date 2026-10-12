import { useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2 } from "lucide-react";
import { useVerifyEmail } from "@/auth/useMe";
import { Splash } from "@/components/Splash";
import { Button } from "@/components/Button";

/** Landing page for the emailed confirmation link. Confirming does not sign the
 * student in — it ends on "you can sign in now", and they do that themselves. */
export function VerifyPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const verify = useVerifyEmail();
  const token = params.get("token") ?? "";
  // StrictMode mounts effects twice in dev — fire exactly once.
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    if (!token) return;
    verify.mutate(token);
  }, [token, verify]);

  if (token && (verify.isPending || verify.isIdle)) return <Splash />;

  if (verify.isSuccess) {
    const email = verify.data.email;
    const next = email ? `/login?confirmed=1&email=${encodeURIComponent(email)}` : "/login";
    return (
      <div className="mx-auto mt-24 max-w-md px-6 text-center">
        <CheckCircle2 className="mx-auto size-8 text-success" />
        <h1 className="mt-3 font-serif text-[20px] font-semibold text-ink">
          Email confirmed
        </h1>
        <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
          {email ? (
            <>
              <strong className="text-ink">{email}</strong> is confirmed. Sign in with that
              address and the password you chose.
            </>
          ) : (
            "Your account is confirmed. Sign in with your NYU email and the password you chose."
          )}
        </p>
        <Button className="mt-5 w-full" onClick={() => navigate(next, { replace: true })}>
          Go to sign in
        </Button>
      </div>
    );
  }

  return (
    <div className="mx-auto mt-24 max-w-md px-6 text-center">
      <AlertTriangle className="mx-auto size-8 text-error" />
      <h1 className="mt-3 font-serif text-[20px] font-semibold text-ink">
        This link didn't work
      </h1>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
        Confirmation links expire after 48 hours. Register again to get a fresh one, or ask
        your instructor to confirm your account.
      </p>
      <Button className="mt-5 w-full" onClick={() => navigate("/login")}>
        Back to sign in
      </Button>
      <p className="mt-3 text-[13px] text-ink-faint">
        Already confirmed? <Link to="/login" className="text-violet">Sign in</Link>.
      </p>
    </div>
  );
}
