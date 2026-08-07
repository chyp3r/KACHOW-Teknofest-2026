"""Exports low-confidence and clarify-sourced router decisions as JSONL.

The evaluation gold set (``evaluation/datasets/intents.jsonl``) is static --
it only grows when someone hand-writes a new case. Production traffic is the
other half of the picture: the router's own ``runs`` table (see
``app.observability.run_recorder``) already records every decision's
message, resolved intent, source and confidence, but nothing turns that into
a shape a human can review and fold back into the gold set. This script is
that bridge, not an automatic one -- it exports candidates, it does not
relabel or retrain anything.

    docker compose run --rm backend python scripts/export_router_traces.py \
        --since 7d --max-confidence 0.6 --out router_traces.jsonl

Needs the `db` service reachable (unlike scripts/build_prototypes.py, don't
pass --no-deps).

Deliberately no automatic retraining loop here: a human reviews the export,
assigns a gold ``expected.intent`` to the cases worth keeping, and appends
them to ``evaluation/datasets/intents.jsonl`` by hand, the same way every
other gold-set case got there. ``scripts/fit_router.py`` is then rerun
explicitly. Auto-labeling production traffic with the router's own guesses
and feeding that straight back into its own training set would let a
confident, wrong pattern reinforce itself silently -- exactly the failure
mode a human-in-the-loop gold set exists to catch.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.infrastructure.database.session import AsyncSessionLocal  # noqa: E402
from app.observability.model.run_model import RunModel  # noqa: E402

#: Sources that mean "the router did not confidently commit on its own" --
#: the same population `evaluation/harness/intent_suite.py`'s
#: `_ESCALATION_SOURCES` treats as escalated. These are exactly the decisions
#: worth a human's attention: a "fused" decision at 0.97 confidence needs no
#: review, a "clarify" or a low-confidence "model" one might.
_REVIEW_WORTHY_SOURCES = frozenset(
    {"clarify", "model", "model_failed", "context_default"}
)


def _parse_since(value: str) -> datetime:
    """Parse a duration like "7d"/"24h"/"30m" into an absolute UTC timestamp."""
    unit = value[-1]
    amount = float(value[:-1])
    if unit == "d":
        delta = timedelta(days=amount)
    elif unit == "h":
        delta = timedelta(hours=amount)
    elif unit == "m":
        delta = timedelta(minutes=amount)
    else:
        raise ValueError(f"Unrecognised --since unit in {value!r} (use d/h/m)")
    return datetime.now(timezone.utc) - delta


async def _export(
    *, since: datetime, max_confidence: Optional[float], out_path: Path
) -> int:
    async with AsyncSessionLocal() as session:
        query = select(RunModel).where(RunModel.created_at >= since).order_by(
            RunModel.created_at.desc()
        )
        result = await session.execute(query)
        runs = result.scalars().all()

    written = 0
    with out_path.open("w", encoding="utf-8") as handle:
        for run in runs:
            review_worthy = run.source in _REVIEW_WORTHY_SOURCES or (
                max_confidence is not None and run.confidence <= max_confidence
            )
            if not review_worthy:
                continue

            handle.write(
                json.dumps(
                    {
                        "run_id": run.id,
                        "created_at": run.created_at.isoformat(),
                        "message": run.input_text,
                        "document_attached": run.document_id is not None,
                        "observed_intent": run.intent,
                        "source": run.source,
                        "confidence": run.confidence,
                        "evidence": run.evidence,
                        "alternatives": run.alternatives,
                        "clarification": run.clarification,
                        # Left blank on purpose -- a human fills this in
                        # (see this module's docstring) before the row is
                        # worth appending to evaluation/datasets/intents.jsonl.
                        "expected_intent": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            written += 1

    return written


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export low-confidence/clarify router decisions as review candidates."
    )
    parser.add_argument(
        "--since", default="7d", help="How far back to look, e.g. 7d/24h/30m (default: 7d)."
    )
    parser.add_argument(
        "--max-confidence",
        type=float,
        default=0.6,
        help="Also include decisions at or below this confidence, whatever their source.",
    )
    parser.add_argument("--out", type=Path, default=Path("router_traces.jsonl"))
    args = parser.parse_args(argv)

    since = _parse_since(args.since)
    written = await _export(since=since, max_confidence=args.max_confidence, out_path=args.out)
    print(f"{written} vaka yazıldı: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
