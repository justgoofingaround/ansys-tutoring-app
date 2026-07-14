import { ApiError } from "./api";

export interface SseEvent {
  event: string;
  data: Record<string, unknown>;
}

/** POST-body SSE: fetch + ReadableStream parser (EventSource can't POST).
 * Calls onEvent for every `event:`/`data:` block; resolves when the stream
 * ends; throws ApiError on a non-2xx response, AbortError on signal. */
export async function streamSse(
  path: string,
  body: unknown,
  onEvent: (e: SseEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (res.status === 401) {
    window.dispatchEvent(new CustomEvent("session-expired"));
  }
  if (!res.ok) {
    let code = `http_${res.status}`;
    try {
      const errBody = await res.json();
      if (typeof errBody.detail === "string") code = errBody.detail;
    } catch {
      /* non-JSON error body */
    }
    throw new ApiError(res.status, code);
  }
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let sep;
    while ((sep = buf.indexOf("\n\n")) !== -1) {
      const block = buf.slice(0, sep);
      buf = buf.slice(sep + 2);
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event: ")) event = line.slice(7).trim();
        else if (line.startsWith("data: ")) data += line.slice(6);
      }
      if (data) onEvent({ event, data: JSON.parse(data) });
    }
  }
}
