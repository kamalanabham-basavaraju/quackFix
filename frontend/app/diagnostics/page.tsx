"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Save } from "lucide-react";
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
  const poll = useMutation({ mutationFn: api.pollProduck });
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
            <CardHeader><CardTitle>Manual poll</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <Button onClick={() => poll.mutate()} disabled={poll.isPending}>
                <RefreshCw className="h-4 w-4" />
                Poll Produck now
              </Button>
              {poll.data && (
                <pre className="max-h-72 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
                  {JSON.stringify(poll.data, null, 2)}
                </pre>
              )}
              {poll.error && <div className="text-sm text-destructive">{poll.error.message}</div>}
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}
