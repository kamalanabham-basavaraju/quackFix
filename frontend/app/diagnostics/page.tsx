"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { ExternalLink, RefreshCw, Save } from "lucide-react";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";

export default function DiagnosticsPage() {
  const queryClient = useQueryClient();
  const setting = useQuery({ queryKey: ["produck-fetch"], queryFn: api.produckState });
  const targetRepo = useQuery({ queryKey: ["target-repo"], queryFn: api.targetRepo });
  const [repoPath, setRepoPath] = useState("");
  useEffect(() => {
    if (targetRepo.data?.employee_portal_path) setRepoPath(targetRepo.data.employee_portal_path);
  }, [targetRepo.data?.employee_portal_path]);
  const setFetch = useMutation({
    mutationFn: api.setProduckFetch,
    onMutate: async (enabled) => {
      await queryClient.cancelQueries({ queryKey: ["produck-fetch"] });
      const previous = queryClient.getQueryData(["produck-fetch"]);
      queryClient.setQueryData(["produck-fetch"], { enabled, updated_at: new Date().toISOString() });
      return { previous };
    },
    onError: (_error, _enabled, context) => {
      if (context?.previous) queryClient.setQueryData(["produck-fetch"], context.previous);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["produck-fetch"] }),
  });
  const saveRepo = useMutation({
    mutationFn: api.setTargetRepo,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["target-repo"] }),
  });
  const poll = useMutation({
    mutationFn: api.pollProduck,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["conversations"] }),
  });
  const enabled = Boolean((setting.data as { enabled?: boolean } | undefined)?.enabled);
  return (
    <AppShell>
      <div className="scrollbar-thin h-full overflow-auto p-6">
        <div className="mb-6">
          <h1 className="font-heading text-2xl font-semibold">Diagnostics</h1>
          <p className="text-sm text-muted-foreground">Connector controls and operational probes.</p>
        </div>
        <div className="grid max-w-4xl gap-4">
          <Card>
            <CardHeader><CardTitle>Target repository</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <div>
                <div className="text-sm font-medium">EMPLOYEE_PORTAL_PATH</div>
                <div className="text-sm text-muted-foreground">
                  This path is sent to the LangGraph backend for incident runs. In Docker, use the mounted container path.
                </div>
              </div>
              <div className="flex gap-2">
                <Input
                  value={repoPath}
                  onChange={(event) => setRepoPath(event.target.value)}
                  placeholder="/workspace/employee-portal"
                />
                <Button onClick={() => saveRepo.mutate(repoPath)} disabled={saveRepo.isPending || !repoPath.trim()}>
                  <Save className="h-4 w-4" />
                  Save
                </Button>
              </div>
              {saveRepo.isSuccess && <div className="text-sm text-primary">Repository path saved.</div>}
              {saveRepo.error && <div className="text-sm text-destructive">{saveRepo.error.message}</div>}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Produck fetch switch</CardTitle></CardHeader>
            <CardContent className="flex items-center justify-between">
              <div>
                <div className="text-sm font-medium">Automatic Produck polling</div>
                <div className="text-sm text-muted-foreground">
                  When enabled, Quackfix asks LangGraph to poll open Produck tickets every 2 minutes.
                </div>
              </div>
              <div className="flex items-center gap-3">
                <span className="text-sm text-muted-foreground">{enabled ? "On" : "Off"}</span>
                <Switch checked={enabled} disabled={setFetch.isPending} onCheckedChange={(checked) => setFetch.mutate(checked)} />
              </div>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Manual Produck inbox</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <Button onClick={() => poll.mutate()} disabled={poll.isPending}>
                <RefreshCw className={`h-4 w-4 ${poll.isPending ? "animate-spin" : ""}`} />
                {poll.isPending ? "Fetching tickets..." : "Fetch Produck tickets"}
              </Button>
              <p className="text-sm text-muted-foreground">
                Fetching only adds Produck tickets to the left-side history. Quackfix will not fix or answer a ticket
                until you open it and choose the action.
              </p>
              {poll.data && (
                <div className="space-y-3">
                  <div className="rounded-md border bg-muted/40 p-3 text-sm">
                    Found {poll.data.fetched} open ticket{poll.data.fetched === 1 ? "" : "s"}. Added {poll.data.added}, updated{" "}
                    {poll.data.updated}, skipped {poll.data.skipped_processed}, failures {poll.data.failures}.
                  </div>
                  <div className="space-y-2">
                    {poll.data.conversations.map((conversation) => (
                      <Link
                        key={conversation.id}
                        href={`/incidents/${conversation.id}`}
                        className="flex items-center justify-between rounded-md border p-3 transition-colors hover:bg-muted"
                      >
                        <div>
                          <div className="text-sm font-medium">{conversation.title}</div>
                          <div className="text-xs text-muted-foreground">Saved to persistent history</div>
                        </div>
                        <ExternalLink className="h-4 w-4 text-muted-foreground" />
                      </Link>
                    ))}
                    {!poll.data.conversations.length && (
                      <div className="rounded-md border border-dashed p-3 text-sm text-muted-foreground">
                        No new actionable Produck tickets were returned.
                      </div>
                    )}
                  </div>
                </div>
              )}
              {poll.error && <div className="text-sm text-destructive">{poll.error.message}</div>}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
