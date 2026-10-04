import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { apiFetch, ApiError } from "@/lib/api";
import type { Me } from "@/types/api";

async function fetchMe(): Promise<Me | null> {
  try {
    return await apiFetch<Me>("/api/auth/me");
  } catch (e) {
    if (e instanceof ApiError && e.status === 401) return null;
    throw e;
  }
}

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: fetchMe, staleTime: 60_000 });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { username: string; password: string }) =>
      apiFetch<Me>("/api/auth/login", { json: body }),
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });
}

/** Registration no longer signs the student in — the server returns 202 and
 * mails a confirmation link, so there is no Me to cache here. */
export function useRegister() {
  return useMutation({
    mutationFn: (body: { email: string; password: string }) =>
      apiFetch<{ status: string; email: string }>("/api/auth/register", { json: body }),
  });
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (body: { email: string }) =>
      apiFetch<{ status: string }>("/api/auth/forgot", { json: body }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (body: { token: string; password: string }) =>
      apiFetch<{ status: string }>("/api/auth/reset", { json: body }),
  });
}

export function useResendVerification() {
  return useMutation({
    mutationFn: (body: { email: string }) =>
      apiFetch<{ status: string }>("/api/auth/resend", { json: body }),
  });
}

/** Opening the emailed link both confirms the address and starts the session. */
export function useVerifyEmail() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (token: string) =>
      apiFetch<Me>(`/api/auth/verify?token=${encodeURIComponent(token)}`, { method: "GET" }),
    onSuccess: (me) => qc.setQueryData(["me"], me),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ ok: boolean }>("/api/auth/logout", { json: {} }),
    onSuccess: () => {
      qc.setQueryData(["me"], null);
      qc.removeQueries({ predicate: (q) => q.queryKey[0] !== "me" });
    },
  });
}

export function homeFor(me: Me): string {
  return me.role === "instructor" ? "/instructor/class" : "/dashboard";
}
