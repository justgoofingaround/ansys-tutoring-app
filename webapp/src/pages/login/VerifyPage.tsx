import { useEffect, useRef } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { AlertTriangle } from "lucide-react";
import { useVerifyEmail } from "@/auth/useMe";
import { Splash } from "@/components/Splash";
import { Button } from "@/components/Button";

/** Landing page for the emailed confirmation link. Confirming also signs the
 * student in, so a success goes straight to the dashboard. */
export function VerifyPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const verify = useVerifyEmail();
  const token = params.get("token") ?? "";
  // StrictMode mounts effects twice in dev; the token is single-use, so a
  // second call would always fail — fire exactly once.
  const fired = useRef(false);

  useEffect(() => {
    if (fired.current) return;
    fired.current = true;
    if (!token) return;
    verify.mutate(token, { onSuccess: () => navigate("/dashboard", { replace: true }) });
  }, [token, verify, navigate]);

  if (token && (verify.isPending || verify.isIdle)) return <Splash />;

  return (
    <div className="mx-auto mt-24 max-w-md px-6 text-center">
      <AlertTriangle className="mx-auto size-8 text-error" />
      <h1 className="mt-3 font-serif text-[20px] font-semibold text-ink">
        This link didn't work
      </h1>
      <p className="mt-2 text-[15px] leading-relaxed text-ink-soft">
        Confirmation links can only be used once and expire after 48 hours. Register again to get
        a fresh one, or ask your instructor to confirm your account.
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
