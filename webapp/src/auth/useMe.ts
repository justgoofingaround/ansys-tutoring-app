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

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: { class_code: string; username: string; password: string }) =>
      apiFetch<Me>("/api/auth/register", { json: body }),
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
