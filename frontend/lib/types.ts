export type Message = {
  id: string;
  conversation_id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: string;
};

export type Execution = {
  id: string;
  conversation_id: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  stage: string;
  started_at: string;
  completed_at: string | null;
  summary: string | null;
  branch_name: string | null;
  commit_hash: string | null;
  pull_request_url: string | null;
  incident_record_path: string | null;
  files_modified: string[];
  documentation_updated: boolean;
  validation: Record<string, unknown>;
  raw_response: Record<string, unknown>;
  error: string | null;
};

export type Conversation = {
  id: string;
  title: string;
  severity: string;
  category: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
  messages: Message[];
  executions: Execution[];
};

export type Dashboard = {
  total_incidents: number;
  successful_resolutions: number;
  failed_resolutions: number;
  open_prs: number;
  average_resolution_seconds: number;
  incidents_by_day: { date: string; count: number }[];
  success_rate: { name: string; value: number }[];
  resolution_duration: { execution_id: string; seconds: number }[];
};

export type ProduckPollResult = {
  checked_at: string | null;
  fetched: number;
  added: number;
  updated: number;
  skipped_processed: number;
  failures: number;
  conversations: Conversation[];
};
