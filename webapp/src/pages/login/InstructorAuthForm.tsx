import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useLogin } from "@/auth/useMe";
import { ApiError } from "@/lib/api";
import { Button } from "@/components/Button";
import { Input, Label, FieldError } from "@/components/Input";

export function InstructorAuthForm() {
  const navigate = useNavigate();
  const login = useLogin();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    login.mutate({ username, password }, { onSuccess: () => navigate("/instructor/class") });
  }

  const errorMsg = login.error
    ? login.error instanceof ApiError && login.error.code === "bad_credentials"
      ? "Wrong username or password."
      : "Can't reach the server — is it running?"
    : null;

  return (
    <form onSubmit={submit} className="space-y-4">
      <div>
        <Label htmlFor="i-username">Username</Label>
        <Input
          id="i-username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
      </div>
      <div>
        <Label htmlFor="i-password">Password</Label>
        <Input
          id="i-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete="current-password"
          required
        />
      </div>
      <FieldError>{errorMsg}</FieldError>
      <Button type="submit" loading={login.isPending} className="w-full">
        {login.isPending ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
