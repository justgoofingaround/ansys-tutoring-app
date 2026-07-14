import { useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { GraduationCap, ClipboardList } from "lucide-react";
import { useMe, homeFor } from "@/auth/useMe";
import { Splash } from "@/components/Splash";
import { cn } from "@/components/cn";
import { SchematicBackdrop } from "./SchematicBackdrop";
import { StudentAuthForm } from "./StudentAuthForm";
import { InstructorAuthForm } from "./InstructorAuthForm";

type Role = "student" | "instructor";

export function LoginPage() {
  const { data: me, isPending } = useMe();
  const location = useLocation();
  const expired = new URLSearchParams(location.search).get("expired") === "1";
  const [role, setRole] = useState<Role>(
    () => (localStorage.getItem("login-role") as Role) || "student",
  );

  useEffect(() => {
    localStorage.setItem("login-role", role);
  }, [role]);

  if (isPending) return <Splash />;
  if (me) return <Navigate to={homeFor(me)} replace />;

  return (
    <div className="flex min-h-screen">
      {/* ── left: drafted schematic on deep ink-violet ── */}
      <div className="relative hidden w-[42%] flex-col justify-between overflow-hidden bg-violet-deep lg:flex">
        <div className="absolute inset-0">
          <SchematicBackdrop />
        </div>
        <div className="relative z-10 mt-auto p-10">
          <div className="font-serif text-2xl font-semibold text-white">ME-UY 4214</div>
          <div className="mt-1 text-[15px] text-white/70">Finite Element Analysis</div>
          <div className="mt-4 text-xs text-white/40">
            NYU Tandon · runs entirely on NYU infrastructure
          </div>
        </div>
      </div>

      {/* ── right: paper panel with the forms ── */}
      <div className="flex flex-1 items-center justify-center bg-paper px-6 py-12">
        <div className="w-full max-w-[400px]">
          <h1 className="font-serif text-[32px] font-semibold leading-tight text-ink">
            Sign in to the tutoring hub
          </h1>
          <p className="mt-2 text-[15px] text-ink-soft">
            Step-by-step Ansys tutorials, quizzes, and help — for the FEA lab.
          </p>

          {expired && (
            <p className="mt-4 rounded-(--radius-control) border border-hairline bg-surface px-3 py-2 text-sm text-ink-soft">
              Session expired — sign in again.
            </p>
          )}

          {/* role toggle with sliding thumb */}
          <div
            role="tablist"
            aria-label="I am a"
            className="relative mt-8 grid h-12 grid-cols-2 rounded-(--radius-control) border border-hairline bg-surface p-1"
          >
            <span
              className={cn(
                "absolute inset-y-1 w-[calc(50%-4px)] rounded-[5px] bg-violet transition-transform duration-200 ease-out",
                role === "student" ? "translate-x-1" : "translate-x-[calc(100%+3px)]",
              )}
            />
            {(
              [
                { key: "student", label: "Student", Icon: GraduationCap },
                { key: "instructor", label: "Instructor", Icon: ClipboardList },
              ] as const
            ).map(({ key, label, Icon }) => (
              <button
                key={key}
                role="tab"
                aria-selected={role === key}
                onClick={() => setRole(key)}
                className={cn(
                  "relative z-10 inline-flex items-center justify-center gap-2 rounded-[5px] text-[15px] font-medium transition-colors duration-200",
                  role === key ? "text-white" : "text-ink-soft hover:text-ink",
                )}
              >
                <Icon className="size-4" />
                {label}
              </button>
            ))}
          </div>

          {/* form area cross-fades between roles */}
          <div key={role} className="mt-6 animate-[form-in_150ms_ease-out]">
            {role === "student" ? <StudentAuthForm /> : <InstructorAuthForm />}
          </div>
        </div>
      </div>

      <style>{`
        @keyframes form-in {
          from { opacity: 0; transform: translateY(4px); }
          to   { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
