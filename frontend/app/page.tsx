"use client";

import { AppShell } from "@/components/shell";
import { IncidentChat } from "@/components/incident-chat";

export default function HomePage() {
  return (
    <AppShell>
      <IncidentChat />
    </AppShell>
  );
}
