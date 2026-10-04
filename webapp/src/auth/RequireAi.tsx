import { Navigate } from "react-router-dom";
import { useMe } from "./useMe";
import { Splash } from "@/components/Splash";

/** Route guard for AI-backed pages (Compass). Mirrors RequireRole, but keys off
 * the server's master AI switch (Settings.enable_ai, surfaced as me.ai_enabled).
 * With AI disabled the backend does not mount /api/chatbot/* at all, so the page
 * would only be able to error — send the student back to the dashboard instead. */
export function RequireAi({ children }: { children: React.ReactNode }) {
  const { data: me, isPending } = useMe();

  if (isPending) return <Splash />;
  if (!me?.ai_enabled) return <Navigate to="/dashboard" replace />;
  return <>{children}</>;
}
