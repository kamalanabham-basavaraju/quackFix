"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { BarChart3, Bot, Moon, Plus, Search, Settings2, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import { api } from "@/lib/api";
import { Conversation } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { formatDate } from "@/lib/utils";

export function AppShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { theme, setTheme } = useTheme();
  const [search, setSearch] = useState("");
  const conversations = useQuery({
    queryKey: ["conversations", search],
    queryFn: () => api.conversations({ q: search }),
  });
  const items = useMemo(() => conversations.data || [], [conversations.data]);

  return (
    <div className="flex h-screen min-h-0 overflow-hidden bg-background">
      <aside className="flex min-h-0 w-80 shrink-0 flex-col border-r bg-card">
        <div className="flex h-16 items-center justify-between border-b px-4">
          <Link href="/" className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground">
              <Bot className="h-5 w-5" />
            </div>
            <div>
              <div className="font-heading text-lg font-semibold">Quackfix</div>
              <div className="text-xs text-muted-foreground">AI Incident Portal</div>
            </div>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Toggle theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
        <div className="space-y-3 border-b p-4">
          <Button className="w-full" onClick={() => router.push("/")}>
            <Plus className="h-4 w-4" />
            New Incident
          </Button>
          <div className="relative">
            <Search className="absolute left-3 top-2.5 h-4 w-4 text-muted-foreground" />
            <Input className="pl-9" placeholder="Search incidents" value={search} onChange={(event) => setSearch(event.target.value)} />
          </div>
        </div>
        <nav className="grid grid-cols-2 gap-2 border-b p-4">
          <Link className={navClass(pathname === "/dashboard")} href="/dashboard">
            <BarChart3 className="h-4 w-4" />
            Dashboard
          </Link>
          <Link className={navClass(pathname === "/diagnostics")} href="/diagnostics">
            <Settings2 className="h-4 w-4" />
            Diagnostics
          </Link>
        </nav>
        <div className="scrollbar-thin flex-1 overflow-auto p-3">
          {items.map((conversation: Conversation) => {
            const active = pathname === `/incidents/${conversation.id}`;
            return (
              <Link
                key={conversation.id}
                href={`/incidents/${conversation.id}`}
                className={`mb-2 block rounded-md border p-3 transition-colors ${active ? "bg-muted" : "hover:bg-muted/70"}`}
              >
                {conversation.category === "produck" && (
                  <div className="mb-2 inline-flex rounded-full bg-primary/10 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-primary">
                    Produck
                  </div>
                )}
                <div className="line-clamp-2 text-sm font-medium">{conversation.title}</div>
                <div className="mt-2 text-xs text-muted-foreground">{formatDate(conversation.updated_at)}</div>
              </Link>
            );
          })}
          {!items.length && (
            <div className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
              No incident history yet.
            </div>
          )}
        </div>
      </aside>
      <main className="min-h-0 min-w-0 flex-1 overflow-hidden">{children}</main>
    </div>
  );
}

function navClass(active: boolean) {
  return `inline-flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm ${
    active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted"
  }`;
}
