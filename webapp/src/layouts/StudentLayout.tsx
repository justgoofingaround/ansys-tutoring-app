import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LogOut, MessageCircle, LayoutDashboard } from "lucide-react";
import { useMe, useLogout } from "@/auth/useMe";
import { cn } from "@/components/cn";

function TopNavLink({ to, icon, label }: { to: string; icon: React.ReactNode; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          "inline-flex h-9 items-center gap-2 rounded-(--radius-control) px-3 text-[15px] font-medium transition-colors",
          isActive ? "bg-violet-tint text-violet" : "text-ink-soft hover:bg-paper hover:text-ink",
        )
      }
    >
      {icon}
      {label}
    </NavLink>
  );
}

export function StudentLayout() {
  const { data: me } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-hairline bg-surface">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-6">
          <span className="font-serif text-[17px] font-semibold text-ink">
            ME-UY 4214 <span className="text-ink-faint">·</span>{" "}
            <span className="text-ink-soft">Tutoring Hub</span>
          </span>
          <nav className="flex items-center gap-1">
            <TopNavLink to="/dashboard" icon={<LayoutDashboard className="size-4" />} label="Dashboard" />
            <TopNavLink to="/chat" icon={<MessageCircle className="size-4" />} label="Compass" />
          </nav>
          <div className="ml-auto flex items-center gap-3">
            <span className="text-sm text-ink-soft">{me?.username}</span>
            <button
              onClick={() => logout.mutate(undefined, { onSuccess: () => navigate("/login") })}
              className="inline-flex size-9 items-center justify-center rounded-(--radius-control) text-ink-faint transition-colors hover:bg-paper hover:text-ink"
              title="Sign out"
            >
              <LogOut className="size-4" />
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
