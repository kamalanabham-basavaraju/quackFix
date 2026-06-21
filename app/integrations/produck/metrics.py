from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ProduckMetrics:
    polls: int = 0
    tickets_fetched: int = 0
    tickets_processed: int = 0
    duplicates_skipped: int = 0
    failures: int = 0
    workflow_runs: int = 0
    dead_letters: list[dict[str, str]] = field(default_factory=list)

    def snapshot(self) -> dict[str, object]:
        return {
            "polls": self.polls,
            "tickets_fetched": self.tickets_fetched,
            "tickets_processed": self.tickets_processed,
            "duplicates_skipped": self.duplicates_skipped,
            "failures": self.failures,
            "workflow_runs": self.workflow_runs,
            "dead_letters": self.dead_letters[-20:],
        }
