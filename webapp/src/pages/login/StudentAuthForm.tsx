import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLogin, useRegister } from "@/auth/useMe";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/Button";
import { Input, Label, FieldError } from "@/components/Input";
import { cn } from "@/components/cn";

const ERROR_TEXT: Record<string, string> = {
  bad_credentials: "Wrong username or password.",
  invalid_class_code: "That class code isn't valid — check with your instructor.",
  username_taken: "That name is taken — pick another.",
};

function errorText(e: unknown): string {
  if (e instanceof ApiError) return ERROR_TEXT[e.code] ?? `Something went wrong (${e.code}).`;
  return "Can't reach the server — is it running?";
}

export function StudentAuthForm() {
  const [tab, setTab] = useState<"signin" | "register">("signin");
  const navigate = useNavigate();
  const login = useLogin();
  const register = useRegister();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [classCode, setClassCode] = useState("");

  const pending = login.isPending || register.isPending;
  const error = tab === "signin" ? login.error : register.error;

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const onSuccess = () => navigate("/dashboard");
    if (tab === "signin") {
      login.mutate({ username, password }, { onSuccess });
    } else {
      register.mutate({ class_code: classCode.trim().toUpperCase(), username, password }, { onSuccess });
    }
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
            onClick={() => setTab(key)}
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
        {tab === "register" && (
          <div>
            <Label htmlFor="class-code">Class code</Label>
            <Input
              id="class-code"
              value={classCode}
              onChange={(e) => setClassCode(e.target.value.toUpperCase())}
              placeholder="SEC-XXXXXX"
              className="font-mono tracking-wider"
              autoComplete="off"
              required
            />
          </div>
        )}
        <div>
          <Label htmlFor="username">{tab === "register" ? "Display name" : "Username"}</Label>
          <Input
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            autoComplete="username"
            required
            minLength={2}
          />
          {tab === "register" && (
            <p className="mt-1.5 text-[13px] leading-snug text-ink-faint">
              Your display name is what your instructor sees — logs use an anonymous token.
            </p>
          )}
        </div>
        <div>
          <Label htmlFor="password">Password</Label>
          <Input
            id="password"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={tab === "register" ? "new-password" : "current-password"}
            required
            minLength={tab === "register" ? 8 : undefined}
          />
        </div>
        <FieldError>{error ? errorText(error) : null}</FieldError>
        <Button type="submit" loading={pending} className="w-full">
          {tab === "signin" ? (pending ? "Signing in…" : "Sign in") : pending ? "Creating account…" : "Create account"}
        </Button>
      </form>
    </div>
  );
}
