import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scheduler import run_scheduled_job_search


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run scheduled AI job search.")
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--threshold", type=int, default=None)
    parser.add_argument("--min-match-score", type=int, default=None)
    parser.add_argument("--max-matched-jobs-per-user", type=int, default=None)
    parser.add_argument("--recent-days", type=int, default=1)
    parser.add_argument("--override-hour", type=int, default=None)
    parser.add_argument("--max-evaluations", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


async def main() -> int:
    load_dotenv(".env")
    args = parse_args()
    result = await run_scheduled_job_search(
        dry_run=args.dry_run,
        limit=args.limit,
        threshold=args.threshold,
        min_match_score=args.min_match_score,
        override_hour=args.override_hour,
        recent_days=args.recent_days,
        max_evaluations=args.max_evaluations,
        max_matched_jobs_per_user=args.max_matched_jobs_per_user,
        use_template_alert=True,
        send_no_results=None,
    )
    print(result.model_dump_json(indent=2))
    if result.errors:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
