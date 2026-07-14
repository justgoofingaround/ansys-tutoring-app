import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpenCheck, Compass, Send, ShieldCheck, Square } from "lucide-react";
import { apiFetch, ApiError } from "@/lib/api";
import { streamSse } from "@/lib/sse";
import type { DashboardData } from "@/types/api";
import { useMe } from "@/auth/useMe";
import { Card, CardTitle } from "@/components/Card";
import { Button } from "@/components/Button";
import { Spinner } from "@/components/Spinner";
import { cn } from "@/components/cn";

/* ── minimal markdown-lite renderer ─────────────────────────────────── */

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Bold, inline code, [n] citation chips, line breaks. Input is escaped
 * first, so the produced HTML contains only our own tags. */
function renderAnswer(text: string): string {
  let html = escapeHtml(text);
  html = html.replace(/`([^`]+)`/g, "<code class='chat-code'>$1</code>");
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(
    /\[(\d+)\]/g,
    "<sup class='chat-cite'>$1</sup>",
  );
  html = html.replace(/\n/g, "<br/>");
  return html;
}

/* ── message bubbles ────────────────────────────────────────────────── */

interface ChatMessage {
  id: number;
  role: "me" | "ai";
  text: string;
  sources?: string[];
  error?: string;
  streaming?: boolean;
}

function Bubble({ msg }: { msg: ChatMessage }) {
  const mine = msg.role === "me";
  return (
    <div className={cn("flex", mine ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-(--radius-card) border px-4 py-3",
          mine ? "border-violet/20 bg-violet-tint" : "border-hairline bg-surface",
        )}
      >
        <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold tracking-wide text-ink-faint">
          {mine ? "ME" : (
            <>
              <Compass className="size-3 text-violet" /> COMPASS
            </>
          )}
        </div>
        {msg.error ? (
          <p className="text-sm text-error">{msg.error}</p>
        ) : (
          <div className="chat-answer text-[15px] leading-relaxed text-ink">
            <span dangerouslySetInnerHTML={{ __html: renderAnswer(msg.text) }} />
            {msg.streaming && (
              <span className="ml-0.5 inline-block h-4 w-[2px] animate-pulse bg-violet align-text-bottom" />
            )}
          </div>
        )}
        {msg.sources && msg.sources.length > 0 && (
          <ol className="mt-3 space-y-1 border-t border-hairline pt-2">
            {msg.sources.map((s, i) => (
              <li key={i} className="flex gap-1.5 text-[12px] text-ink-soft">
                <span className="font-mono text-ink-faint">[{i + 1}]</span>
                {s}
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

/* ── consent gate ───────────────────────────────────────────────────── */

function ConsentGate() {
  const qc = useQueryClient();
  const grant = useMutation({
    mutationFn: () => apiFetch("/api/chatbot/consent", { json: { granted: true } }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
  });
  return (
    <Card className="mx-auto max-w-lg">
      <div className="flex items-center gap-2">
        <ShieldCheck className="size-5 text-violet" />
        <CardTitle>Before you use Compass</CardTitle>
      </div>
      <p className="mt-3 text-[15px] leading-relaxed text-ink-soft">
        Compass answers Ansys questions from locally indexed documentation —
        nothing leaves NYU's network. To help improve the course, your questions
        and Compass's answers are logged for your instructor,{" "}
        <strong className="text-ink">under an anonymous session token, never your name or NetID</strong>.
      </p>
      <p className="mt-2 text-[13px] text-ink-faint">
        You can withdraw consent any time; Compass simply stops working.
      </p>
      <Button className="mt-4 w-full" loading={grant.isPending} onClick={() => grant.mutate()}>
        I understand — enable Compass
      </Button>
    </Card>
  );
}

/* ── the chat page ──────────────────────────────────────────────────── */

const SUGGESTIONS = [
  "Why would a mesh generation fail?",
  "What's the difference between Total and Directional Deformation?",
  "How do I apply a force to a face in Mechanical?",
];

export function ChatPage() {
  const { data: me } = useMe();
  const [params] = useSearchParams();
  const { data: dash } = useQuery({
    queryKey: ["student", "dashboard"],
    queryFn: () => apiFetch<DashboardData>("/api/student/dashboard"),
  });

  const [context, setContext] = useState<string>(params.get("tutorial") ?? "");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const bottomRef = useRef<HTMLDivElement>(null);

  // rAF-batched token appends: tokens land in a ref buffer; one animation
  // frame flushes them into React state, so a fast stream doesn't force a
  // render per token.
  const pending = useRef("");
  const rafId = useRef(0);
  const streamMsgId = useRef(0);

  function flushTokens() {
    rafId.current = 0;
    const chunk = pending.current;
    if (!chunk) return;
    pending.current = "";
    setMessages((ms) =>
      ms.map((m) => (m.id === streamMsgId.current ? { ...m, text: m.text + chunk } : m)),
    );
  }

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => () => abortRef.current?.abort(), []);

  async function send(question: string) {
    if (!question.trim() || busy) return;
    setInput("");
    setBusy(true);
    const meId = nextId.current++;
    const aiId = nextId.current++;
    streamMsgId.current = aiId;
    setMessages((ms) => [
      ...ms,
      { id: meId, role: "me", text: question },
      { id: aiId, role: "ai", text: "", streaming: true },
    ]);
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      await streamSse(
        "/api/chatbot/query",
        { question, tutorial_id: context || null, stream: true },
        (e) => {
          if (e.event === "token") {
            pending.current += e.data.t as string;
            if (!rafId.current) rafId.current = requestAnimationFrame(flushTokens);
          } else if (e.event === "sources") {
            flushTokens();
            const sources = e.data.sources as string[];
            setMessages((ms) => ms.map((m) => (m.id === aiId ? { ...m, sources } : m)));
          } else if (e.event === "error") {
            setMessages((ms) =>
              ms.map((m) =>
                m.id === aiId
                  ? { ...m, error: `Compass isn't reachable right now (${e.data.detail}). Try again later or ask your instructor.` }
                  : m,
              ),
            );
          }
        },
        ac.signal,
      );
    } catch (err) {
      if ((err as Error).name !== "AbortError") {
        const detail = err instanceof ApiError ? err.code : String(err);
        setMessages((ms) =>
          ms.map((m) => (m.id === aiId ? { ...m, error: `Request failed (${detail}).` } : m)),
        );
      }
    } finally {
      flushTokens();
      setMessages((ms) => ms.map((m) => (m.id === aiId ? { ...m, streaming: false } : m)));
      setBusy(false);
      abortRef.current = null;
    }
  }

  function stop() {
    abortRef.current?.abort();
  }

  if (!me) return <Spinner className="mx-auto my-16 size-6" />;
  if (!me.chatbot_consent) return <ConsentGate />;

  return (
    <div className="mx-auto flex h-[calc(100vh-8.5rem)] max-w-[760px] flex-col">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h1 className="flex items-center gap-2 font-serif text-[22px] font-semibold text-ink">
          <Compass className="size-5 text-violet" /> Compass
        </h1>
        <label className="flex items-center gap-2 text-sm text-ink-soft">
          <BookOpenCheck className="size-4 text-ink-faint" />
          <select
            value={context}
            onChange={(e) => setContext(e.target.value)}
            className="h-9 rounded-(--radius-control) border border-hairline bg-surface px-2 text-sm text-ink focus:outline-2 focus:outline-violet"
          >
            <option value="">General question</option>
            {(dash?.tutorials ?? []).map((t) => (
              <option key={t.tutorial_id} value={t.tutorial_id}>
                About: {t.title}
              </option>
            ))}
          </select>
        </label>
      </div>

      <div className="flex-1 space-y-3 overflow-y-auto rounded-(--radius-card) border border-hairline bg-paper p-4">
        {messages.length === 0 && (
          <div className="mx-auto mt-10 max-w-md text-center">
            <p className="text-[15px] text-ink-soft">
              Ask anything about Ansys — answers come from locally indexed
              documentation and always cite their sources.
            </p>
            <div className="mt-4 space-y-2">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  onClick={() => send(s)}
                  className="block w-full rounded-(--radius-control) border border-hairline bg-surface px-4 py-2.5 text-left text-sm text-ink hover:border-ink-faint"
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m) => (
          <Bubble key={m.id} msg={m} />
        ))}
        <div ref={bottomRef} />
      </div>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask Compass about Ansys…"
          className="h-11 flex-1 rounded-(--radius-control) border border-hairline bg-surface px-4 text-[15px] text-ink placeholder:text-ink-faint focus:outline-2 focus:outline-violet"
        />
        {busy ? (
          <Button type="button" variant="secondary" onClick={stop}>
            <Square className="size-4" /> Stop
          </Button>
        ) : (
          <Button type="submit" disabled={!input.trim()}>
            <Send className="size-4" /> Send
          </Button>
        )}
      </form>
      <p className="mt-1.5 text-center text-[12px] text-ink-faint">
        Logged under your anonymous token ({me.opaque_token}) to improve the course.
      </p>
    </div>
  );
}
