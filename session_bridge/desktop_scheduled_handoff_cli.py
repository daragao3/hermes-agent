"""Local operator CLI for guarded Desktop scheduled-task owner transfer."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from hermes_state import SessionDB

from .desktop_scheduled_catalog import CatalogConflict
from .desktop_scheduled_handoff import CONFIRMATION, DesktopScheduledHandoff
from .desktop_surface_discovery import (
    catalog_root_for_user_data,
    default_user_data_dirs,
    detect_live_user_data_root,
    discover_scheduled_catalogs,
)
from .store import SessionBridgeStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plan or apply a two-phase Claude Desktop scheduled-task owner transfer"
    )
    parser.add_argument("--source-root-id", required=True)
    parser.add_argument("--target-root-id", required=True)
    parser.add_argument("--task-id", action="append", required=True, dest="task_ids")
    parser.add_argument("--recover-committed-run", help="Restore the exact missing set from this committed handoff receipt")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm", choices=(CONFIRMATION,))
    parser.add_argument(
        "--state-db", type=Path, default=Path.home() / ".hermes" / "state.db"
    )
    parser.add_argument(
        "--prompt-root",
        type=Path,
        default=Path.home() / ".claude" / "scheduled-tasks",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        default=Path.home() / "hermes-state-backups" / "scheduled-catalog-handoffs",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.apply and args.confirm != CONFIRMATION:
        print(json.dumps({"error": "confirmation_required", "expected": CONFIRMATION}))
        return 2
    catalogs = discover_scheduled_catalogs()
    live = detect_live_user_data_root(default_user_data_dirs())
    live_target = catalog_root_for_user_data(catalogs, live.root_id)
    database = SessionDB(args.state_db, read_only=not args.apply)
    try:
        handoff = DesktopScheduledHandoff(
            SessionBridgeStore(database),
            catalogs=catalogs,
            prompt_root=args.prompt_root,
            backup_root=args.backup_root,
            live_target=live_target,
            live_status=live.status,
        )
        if args.apply:
            payload = handoff.apply(
                source_root_id=args.source_root_id,
                target_root_id=args.target_root_id,
                task_ids=args.task_ids,
                confirmation=args.confirm,
                recover_committed_run=args.recover_committed_run,
            )
        else:
            payload = handoff.plan(
                source_root_id=args.source_root_id,
                target_root_id=args.target_root_id,
                task_ids=args.task_ids,
                recover_committed_run=args.recover_committed_run,
            )
            payload.pop("plan", None)
            payload["status"] = "planned"
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=list))
        return 0
    except (CatalogConflict, OSError, ValueError) as exc:
        print(json.dumps({"error": type(exc).__name__, "detail": str(exc)}))
        return 1
    finally:
        database.close()


if __name__ == "__main__":
    raise SystemExit(main())
