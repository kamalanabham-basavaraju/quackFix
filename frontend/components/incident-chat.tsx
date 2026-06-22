"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import ReactMarkdown from "react-markdown";
import { Copy, Download, ExternalLink, SendHorizontal } from "lucide-react";

import { api } from "@/lib/api";
import { Conversation, Execution } from "@/lib/types";
import { formatDate, wsBase } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Textarea } from "@/components/ui/textarea";
import { StatusBadge } from "@/components/status";

const stages = [
  "queued",
  "running",
  "fetching_produck_ticket",
  "searching_parcle",
  "analyzing",
  "generating_fix",
  "validating",
  "creating_pr",
  "completed",
];

export function IncidentChat({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [incident, setIncident] = useState("");
  const [pendingPrompt, setPendingPrompt] = useState("");
  const [toast, setToast] = useState("");
  const conversation = useQuery({
    queryKey: ["conversation", conversationId],
    queryFn: () => api.conversation(conversationId!),
    enabled: Boolean(conversationId),
    refetchInterval: 5000,
  });
  const activeExecution = conversation.data?.executions.at(-1);
  const isProduckTicket = conversation.data?.category === "produck";

  const refreshExecution = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["conversation", conversationId] });
    queryClient.invalidateQueries({ queryKey: ["conversations"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  }, [conversationId, queryClient]);

  useExecutionSocket(activeExecution?.id, refreshExecution);

  const submit = useMutation({
    mutationFn: (prompt: string) =>
      api.submitIncident({
        incident: prompt,
        conversation_id: conversationId,
        severity: "medium",
        tags: ["frontend"],
      }),
    onMutate: (prompt) => {
      setToast("");
      setPendingPrompt(prompt);
    },
    onSuccess: (payload) => {
      setIncident("");
      setPendingPrompt("");
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["conversation", payload.conversation.id] });
      if (!conversationId) router.push(`/incidents/${payload.conversation.id}`);
    },
    onError: (error) => {
      setPendingPrompt("");
      setToast(error.message);
    },
  });
  const triggerProduck = useMutation({
    mutationFn: () => api.triggerProduckConversation(conversationId!),
    onSuccess: (payload) => {
      queryClient.invalidateQueries({ queryKey: ["conversations"] });
      queryClient.invalidateQueries({ queryKey: ["conversation", payload.conversation.id] });
      queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    },
    onError: (error) => setToast(error.message),
  });

  const data = conversation.data;
  const canTriggerProduck =
    Boolean(conversationId && isProduckTicket) &&
    !triggerProduck.isPending &&
    !["queued", "running"].includes(activeExecution?.status || "");
  const sendIncident = () => {
    const prompt = incident.trim();
    if (!prompt || submit.isPending) return;
    submit.mutate(prompt);
  };
  return (
    <div className="grid h-full min-h-0 grid-cols-[minmax(0,1fr)_360px]">
      <section className="flex min-h-0 min-w-0 flex-col">
        <header className="flex h-16 items-center justify-between border-b px-6">
          <div>
            <h1 className="font-heading text-lg font-semibold">{data?.title || "New incident"}</h1>
            <p className="text-xs text-muted-foreground">
              {isProduckTicket
                ? "Produck ticket preview and execution history are persisted."
                : "Messages, execution metadata, and audit trail are persisted."}
            </p>
          </div>
          {activeExecution && <StatusBadge status={activeExecution.status} />}
        </header>
        <div className="scrollbar-thin min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-6 py-5">
          {!data?.messages.length && (
            <div className="mx-auto mt-24 max-w-2xl text-center">
              <h2 className="font-heading text-3xl font-semibold tracking-tight">What should Quackfix repair?</h2>
              <p className="mt-3 text-muted-foreground">
                Submit an incident and Quackfix will call the existing LangGraph backend, document the run, and return
                branch and PR details.
              </p>
            </div>
          )}
          <div className="mx-auto flex max-w-4xl flex-col gap-4">
            {isProduckTicket && (
              <div className="rounded-lg border border-primary/30 bg-primary/5 p-4">
                <div className="text-sm font-medium">Produck ticket waiting for approval</div>
                <p className="mt-1 text-sm text-muted-foreground">
                  This ticket was fetched into history only. Quackfix will not change code or answer it until you approve.
                </p>
                <Button className="mt-3" onClick={() => triggerProduck.mutate()} disabled={!canTriggerProduck}>
                  {triggerProduck.isPending ? "Starting..." : "Fix / answer ticket"}
                </Button>
              </div>
            )}
            {data?.messages.map((message) => (
              <div key={message.id} className={message.role === "user" ? "ml-auto max-w-[80%]" : "mr-auto max-w-[86%]"}>
                <div className="mb-1 text-xs text-muted-foreground">{message.role} - {formatDate(message.timestamp)}</div>
                <div className={message.role === "user" ? "rounded-lg bg-primary px-4 py-3 text-primary-foreground" : "rounded-lg border bg-card px-4 py-3"}>
                  <ReactMarkdown className="prose prose-sm max-w-none dark:prose-invert prose-pre:bg-muted prose-code:font-mono">
                    {message.content}
                  </ReactMarkdown>
                </div>
              </div>
            ))}
            {pendingPrompt && (
              <>
                <div className="ml-auto max-w-[80%]">
                  <div className="mb-1 text-xs text-muted-foreground">user - sending</div>
                  <div className="rounded-lg bg-primary px-4 py-3 text-primary-foreground">{pendingPrompt}</div>
                </div>
                <div className="mr-auto max-w-[86%]">
                  <div className="mb-1 text-xs text-muted-foreground">assistant - queued</div>
                  <div className="rounded-lg border bg-card px-4 py-3">Analyzing incident...</div>
                </div>
              </>
            )}
          </div>
        </div>
        <div className="border-t p-4">
          {toast && <div className="mb-3 rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">{toast}</div>}
          <div className="mx-auto flex max-w-4xl gap-3">
            <Textarea
              placeholder="Users cannot update their profile after the latest release."
              value={incident}
              onChange={(event) => setIncident(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  sendIncident();
                }
              }}
            />
            <Button className="h-auto self-stretch px-5" disabled={!incident.trim() || submit.isPending} onClick={sendIncident}>
              <SendHorizontal className="h-4 w-4" />
            </Button>
          </div>
        </div>
      </section>
      <aside className="scrollbar-thin min-h-0 overflow-auto border-l bg-card/60 p-4">
        <LivePanel execution={activeExecution} />
        <ExecutionDetails execution={activeExecution} />
      </aside>
    </div>
  );
}

function useExecutionSocket(executionId: string | undefined, onUpdate: () => void) {
  useEffect(() => {
    if (!executionId) return;
    const socket = new WebSocket(`${wsBase()}/ws/executions/${executionId}`);
    socket.onmessage = onUpdate;
    const interval = window.setInterval(() => {
      if (socket.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
    return () => {
      window.clearInterval(interval);
      socket.close();
    };
  }, [executionId, onUpdate]);
}

function LivePanel({ execution }: { execution?: Execution }) {
  const current = execution?.stage || "queued";
  const currentIndex = Math.max(stages.indexOf(current), 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Live Agent Thinking</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {stages.map((stage, index) => (
          <div key={stage} className="flex items-center gap-3 text-sm">
            <div className={`h-2.5 w-2.5 rounded-full ${index <= currentIndex ? "bg-primary" : "bg-muted"}`} />
            <span className={index <= currentIndex ? "text-foreground" : "text-muted-foreground"}>
              {stage.replaceAll("_", " ")}
            </span>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function ExecutionDetails({ execution }: { execution?: Execution }) {
  const exportJson = () => {
    if (!execution) return;
    const blob = new Blob([JSON.stringify(execution, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `execution-${execution.id}.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  return (
    <Card className="mt-4">
      <CardHeader>
        <CardTitle>Resolution</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        {!execution && <p className="text-muted-foreground">No execution yet.</p>}
        {execution && (
          <>
            <Field label="Branch" value={execution.branch_name} code />
            <Field label="Commit" value={execution.commit_hash} code />
            {execution.pull_request_url && (
              <a className="inline-flex items-center gap-2 text-primary" href={execution.pull_request_url} target="_blank">
                Pull request <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => navigator.clipboard.writeText(execution.summary || "")}>
                <Copy className="h-3.5 w-3.5" /> Copy
              </Button>
              <Button variant="outline" size="sm" onClick={exportJson}>
                <Download className="h-3.5 w-3.5" /> JSON
              </Button>
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function Field({ label, value, code }: { label: string; value?: string | null; code?: boolean }) {
  return (
    <div>
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className={code ? "break-all font-mono text-xs" : ""}>{value || "Pending"}</div>
    </div>
  );
}
