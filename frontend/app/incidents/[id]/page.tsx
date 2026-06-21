"use client";

import { useParams } from "next/navigation";

import { IncidentChat } from "@/components/incident-chat";
import { AppShell } from "@/components/shell";

export default function IncidentPage() {
  const params = useParams<{ id: string }>();
  return (
    <AppShell>
      <IncidentChat conversationId={params.id} />
    </AppShell>
  );
}
