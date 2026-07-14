import { Navigate, useLocation } from "react-router-dom";
import { useMe, homeFor } from "./useMe";
import { Splash } from "@/components/Splash";

export function RequireRole({
  role,
  children,
}: {
  role: "instructor" | "student";
  children: React.ReactNode;
}) {
  const { data: me, isPending } = useMe();
  const location = useLocation();

  if (isPending) return <Splash />;
  if (!me) return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  if (me.role !== role) return <Navigate to={homeFor(me)} replace />;
  return <>{children}</>;
}
