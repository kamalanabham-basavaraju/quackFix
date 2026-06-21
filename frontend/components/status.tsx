import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export function StatusBadge({ status }: { status?: string | null }) {
  const value = status || "unknown";
  return (
    <Badge
      className={cn(
        value === "completed" && "border-primary/40 bg-primary/10 text-primary",
        value === "failed" && "border-destructive/40 bg-destructive/10 text-destructive",
        ["queued", "running"].includes(value) && "border-yellow-500/40 bg-yellow-500/10 text-yellow-600",
      )}
    >
      {value.replaceAll("_", " ")}
    </Badge>
  );
}
