"""Seed Parcle memory with the Employee Portal's canonical documentation files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.config import settings
from app.services.container import build_services
from app.services.parcle_ingestion import ParcleIngestionService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-path",
        type=Path,
        default=settings.employee_portal_path,
        help="Employee Portal root (defaults to EMPLOYEE_PORTAL_PATH)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate files without writing to Parcle")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    services = build_services()
    result = ParcleIngestionService(services.parcle, args.project_path).ingest(args.dry_run)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()
