"use client";

import { useState, useRef, useEffect } from "react";
import { api } from "@/lib/api";
import type { ChatMessage, Source } from "@/types";

function getClientIdFromToken(): string {
  if (typeof window === "undefined") return "default";
  const token = localStorage.getItem("token");
  if (!token) return "default";
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.client_id || "default";
  } catch {
    return "default";
  }
}

function MessageText({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <span className="block break-words text-sm leading-relaxed">
      {lines.map((line, i) => (
        <span key={i}>
          {line}
          {i < lines.length - 1 && <br />}
        </span>
      ))}
    </span>
  );
}

/** Animate a chunk character-by-character at ~15ms/char to simulate ChatGPT effect. */
function animateChunk(text: string, onChar: (ch: string) => void): Promise<void> {
  return new Promise((resolve) => {
    let i = 0;
    function next() {
      if (i >= text.length) { resolve(); return; }
      onChar(text[i++]);
      setTimeout(next, 15);
    }
    next();
  });
}

/** Consume an SSE stream from /chat/{clientId}/stream and call handlers per event. */
async function streamChat(
  clientId: string,
  message: string,
  sessionId: string | undefined,
  onToken: (text: string) => void,
  onDone: (sessionId: string, sources: Source[]) => void,
  departmentCode: string = "",
) {
  const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;

  // Call backend DIRECTLY — bypasses Next.js rewrite proxy which buffers SSE responses
  const backendUrl = process.env.NEXT_API_URL || "http://localhost:8000";
  const res = await fetch(`${backendUrl}/api/chat/${clientId}/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ message, session_id: sessionId, department_code: departmentCode }),
  });

  if (!res.ok || !res.body) {
    throw new Error(`Request failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let streamError: string | null = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // SSE events are separated by \n\n
    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const part of parts) {
      const line = part.trim();
      if (!line.startsWith("data: ")) continue;
      try {
        const event = JSON.parse(line.slice(6));
        if (event.type === "token") {
          // Animate each chunk character-by-character for smooth ChatGPT-like effect
          await animateChunk(event.text as string, onToken);
        } else if (event.type === "error") {
          // Capture the backend error message to throw after stream ends
          streamError = (event.content as string) || "Sorry, something went wrong. Please try again.";
        } else if (event.type === "done") {
          onDone(event.session_id as string, (event.sources as Source[]) ?? []);
        }
      } catch {
        // malformed chunk — skip
      }
    }
  }

  // After stream ends, if the backend reported an error, throw so the catch block shows it
  if (streamError) {
    throw new Error(streamError);
  }
}

export default function ChatTestPage() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [clientId, setClientId] = useState("default");
  const [departmentCode, setDepartmentCode] = useState<string>("");
  const messagesEndRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const token = typeof window !== "undefined" ? localStorage.getItem("token") : null;
    let id = "default";
    let dc = "";
    if (token) {
      try {
        const payload = JSON.parse(atob(token.split(".")[1]));
        id = payload.client_id || "default";
        dc = payload.department_code || "";
      } catch {}
    }
    setClientId(id);
    setDepartmentCode(dc);

    api.getMyProfile().then((profile) => {
      const s = (profile.client as unknown as { settings?: { welcome_message?: string } })?.settings;
      const welcome = s?.welcome_message ?? "Hello! How can I help you today?";
      setMessages([{ role: "assistant", content: welcome }]);
    }).catch(() => {
      setMessages([{ role: "assistant", content: "Hello! How can I help you today?" }]);
    });
  }, []);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function handleSend(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim() || loading) return;

    const userMessage = input.trim();
    setInput("");

    // Add user message + empty assistant placeholder
    setMessages((prev) => [
      ...prev,
      { role: "user", content: userMessage },
      { role: "assistant", content: "" },
    ]);
    setLoading(true);

    try {
      await streamChat(
        clientId,
        userMessage,
        sessionId,
        (chunk) => {
          // Append token to the last (assistant) message
          setMessages((prev) => {
            const last = prev[prev.length - 1];
            return [
              ...prev.slice(0, -1),
              { ...last, content: last.content + chunk },
            ];
          });
        },
        (sid, sources) => {
          setSessionId(sid);
          // Attach sources to the last assistant message
          if (sources.length > 0) {
            setMessages((prev) => {
              const last = prev[prev.length - 1];
              return [...prev.slice(0, -1), { ...last, sources }];
            });
          }
        },
        departmentCode,
      );
    } catch (err) {
      const errMsg = err instanceof Error ? err.message : "Sorry, something went wrong. Please try again.";
      setMessages((prev) => {
        const last = prev[prev.length - 1];
        return [
          ...prev.slice(0, -1),
          { ...last, content: errMsg },
        ];
      });
    } finally {
      setLoading(false);
    }
  }

  function clearChat() {
    setMessages([]);
    setSessionId(undefined);
    api.getMyProfile().then((profile) => {
      const s = (profile.client as unknown as { settings?: { welcome_message?: string } })?.settings;
      const welcome = s?.welcome_message ?? "Hello! How can I help you today?";
      setMessages([{ role: "assistant", content: welcome }]);
    }).catch(() => {});
  }

  // The last message is the streaming assistant message if loading=true and content may be empty
  const isStreaming = loading;

  return (
    <div className="flex h-full flex-col">
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-2xl font-bold">Test Chat</h1>
        <div className="flex items-center gap-3">
          <span className="text-sm text-gray-500">
            Client: <span className="font-medium text-gray-700">{clientId}</span>
          </span>
          <button
            onClick={clearChat}
            className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm hover:bg-gray-50"
          >
            Clear
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl bg-white p-4 shadow-sm">
        <div className="space-y-4">
          {messages.map((msg, i) => {
            const isLastAssistant =
              isStreaming && i === messages.length - 1 && msg.role === "assistant";
            return (
              <div
                key={i}
                className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
              >
                <div
                  className={`max-w-[75%] rounded-2xl px-4 py-3 ${
                    msg.role === "user"
                      ? "bg-blue-600 text-white"
                      : "bg-gray-100 text-gray-800"
                  }`}
                >
                  {/* Show typing dots only while waiting for first token */}
                  {isLastAssistant && msg.content === "" ? (
                    <div className="flex gap-1 py-0.5">
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.1s]" />
                      <span className="h-2 w-2 animate-bounce rounded-full bg-gray-400 [animation-delay:0.2s]" />
                    </div>
                  ) : (
                    <>
                      <MessageText text={msg.content} />
                      {/* Blinking cursor while still streaming */}
                      {isLastAssistant && (
                        <span className="ml-0.5 inline-block h-3.5 w-0.5 animate-pulse bg-gray-500 align-middle" />
                      )}
                    </>
                  )}

                  {msg.sources && msg.sources.length > 0 && (
                    <div className="mt-2 border-t border-gray-200 pt-2">
                      <p className="text-xs font-medium text-gray-400">Sources:</p>
                      {msg.sources.map((s: Source, j: number) => (
                        <p key={j} className="text-xs text-gray-400">
                          {s.filename}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>
      </div>

      <form onSubmit={handleSend} className="mt-4 flex gap-3">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Type a message..."
          className="flex-1 rounded-xl border border-gray-300 px-4 py-3 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
        />
        <button
          type="submit"
          disabled={loading || !input.trim()}
          className="rounded-xl bg-blue-600 px-6 py-3 font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Send
        </button>
      </form>
    </div>
  );
}
