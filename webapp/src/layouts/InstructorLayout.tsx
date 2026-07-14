import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LogOut, Users, BookOpen, ListChecks, HelpCircle } from "lucide-react";
import { useMe, useLogout } from "@/auth/useMe";
import { cn } from "@/components/cn";

const navItems = [
  { to: "/instructor/class", icon: Users, label: "Class" },
  { to: "/instructor/tutorials", icon: BookOpen, label: "Tutorials" },
  { to: "/instructor/quizzes", icon: ListChecks, label: "Quizzes" },
  { to: "/instructor/faqs", icon: HelpCircle, label: "FAQs" },
];

export function InstructorLayout() {
  const { data: me } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-56 shrink-0 flex-col border-r border-hairline bg-surface">
        <div className="border-b border-hairline px-5 py-4">
          <div className="font-serif text-[17px] font-semibold text-ink">ME-UY 4214</div>
          <div className="text-sm text-ink-soft">Instructor</div>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {navItems.map(({ to, icon: Icon, label }) => (
            <NavLink
              key={to}
              to={to}
              className={({ isActive }) =>
                cn(
                  "flex h-10 items-center gap-3 rounded-(--radius-control) px-3 text-[15px] font-medium transition-colors",
                  isActive
                    ? "bg-violet-tint text-violet"
                    : "text-ink-soft hover:bg-paper hover:text-ink",
                )
              }
            >
              <Icon className="size-4" />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="flex items-center justify-between border-t border-hairline px-5 py-3">
          <span className="truncate text-sm text-ink-soft">{me?.username}</span>
          <button
            onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
            className="inline-flex size-8 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-paper hover:text-ink"
            title="Sign out"
          >
            <LogOut className="size-4" />
          </button>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-8">
        <Outlet />
      </main>
    </div>
  );
}
