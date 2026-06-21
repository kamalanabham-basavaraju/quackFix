"use client";

import { useQuery } from "@tanstack/react-query";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { AppShell } from "@/components/shell";
import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export default function DashboardPage() {
  const dashboard = useQuery({ queryKey: ["dashboard"], queryFn: api.dashboard, refetchInterval: 15000 });
  const data = dashboard.data;
  return (
    <AppShell>
      <div className="scrollbar-thin h-full overflow-auto p-6">
        <div className="mb-6">
          <h1 className="font-heading text-2xl font-semibold">Incident Dashboard</h1>
          <p className="text-sm text-muted-foreground">Operational health across Quackfix incident executions.</p>
        </div>
        <div className="grid grid-cols-4 gap-4">
          <Metric title="Total incidents" value={data?.total_incidents ?? 0} />
          <Metric title="Successful" value={data?.successful_resolutions ?? 0} />
          <Metric title="Failed" value={data?.failed_resolutions ?? 0} />
          <Metric title="Avg duration" value={`${Math.round(data?.average_resolution_seconds ?? 0)}s`} />
        </div>
        <div className="mt-6 grid grid-cols-2 gap-4">
          <Card>
            <CardHeader><CardTitle>Incidents by day</CardTitle></CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={data?.incidents_by_day || []}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="date" fontSize={12} />
                  <YAxis fontSize={12} />
                  <Tooltip />
                  <Area dataKey="count" stroke="#2f9e5b" fill="#2f9e5b" fillOpacity={0.18} />
                </AreaChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Success rate</CardTitle></CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={data?.success_rate || []} dataKey="value" nameKey="name" outerRadius={92}>
                    {(data?.success_rate || []).map((entry, index) => (
                      <Cell key={entry.name} fill={["#2f9e5b", "#c84343", "#6f7771"][index]} />
                    ))}
                  </Pie>
                  <Tooltip />
                </PieChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
          <Card className="col-span-2">
            <CardHeader><CardTitle>Resolution duration</CardTitle></CardHeader>
            <CardContent className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data?.resolution_duration || []}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                  <XAxis dataKey="execution_id" hide />
                  <YAxis fontSize={12} />
                  <Tooltip />
                  <Bar dataKey="seconds" fill="#2f9e5b" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        </div>
      </div>
    </AppShell>
  );
}

function Metric({ title, value }: { title: string; value: string | number }) {
  return (
    <Card>
      <CardHeader><CardTitle className="text-sm text-muted-foreground">{title}</CardTitle></CardHeader>
      <CardContent><div className="font-heading text-3xl font-semibold">{value}</div></CardContent>
    </Card>
  );
}
