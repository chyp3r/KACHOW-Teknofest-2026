"""Measure the real wall-clock cost of a single live mevzuat-mcp round trip.

Chat's dynamic legislation escalation (``use_live_legislation``, see
``app.ai.tools.document_tools``'s guarded ``search_legislation_live``) only
reaches mevzuat.gov.tr when the local corpus was weak -- but every reach
still costs whatever ``resolve_and_fetch`` costs, and that call shape is
exactly what both the assistant's live tool (``mevzuat_tools.py``) and this
escalation use. ``MCPClient.connect()`` opens a brand-new stdio subprocess
per call (no pooling, see ``app/mcp/client.py``), so a single lookup can
already be 2-3 sequential subprocess spawns (KANUN-filtered search, an
unfiltered retry, then the content fetch) -- this script puts real numbers
on that cost instead of guessing.

The product-owner gate this feeds: chat-only, opt-in, local-miss-only
escalation ships now; whether document analysis or draft generation should
also get a per-request live path (today they don't -- document analysis
only reads the boot-warmed ``CURATED_LEGISLATION`` in-memory index, no
per-request network cost) is a decision that should be grounded in this
script's p95, not assumed. `retrieve_mevzuat_node`'s own node budget is 25s
and isn't guaranteed to survive a cold multi-law fetch -- treat a p95
meaningfully above ~8-10s here as the signal that those surfaces should
wait for connection pooling (``MCPClient``/``MCPManager`` don't have any
today) before adopting a per-request live path.

Requires an actually-installed ``mevzuat-mcp`` reachable via
``settings.MEVZUAT_MCP_COMMAND``/``MEVZUAT_MCP_ARGS`` (it is deliberately
not part of the backend image -- pulls playwright + a browser binary, see
``config.py``'s own comment) and a live path to mevzuat.gov.tr.

Usage:
    python scripts/measure_mevzuat_mcp_latency.py
    python scripts/measure_mevzuat_mcp_latency.py --repeat 20
    python scripts/measure_mevzuat_mcp_latency.py --repeat 10 --outside-curated-only
"""

import argparse
import asyncio
import os
import sys
import time

sys.path.append(os.path.join(os.path.dirname(__file__), "..", "backend"))

from app.ai.retrieval.mcp_mevzuat import CURATED_LEGISLATION  # noqa: E402
from app.mcp.mevzuat_client import resolve_and_fetch  # noqa: E402
from app.mcp.registry import MEVZUAT_SERVER, is_registered, register_servers  # noqa: E402

#: Well-known KANUN numbers outside the boot-warmed curated 7 -- exercising
#: only 2646/3071/4982/657/6698/7201/5070 would understate real-world
#: latency, since a chat user asking about a law already in that set would
#: never trigger this escalation in the first place (search_legislation's
#: local corpus already covers it).
OUTSIDE_CURATED: tuple[tuple[str, str], ...] = (
    ("5237", "Türk Ceza Kanunu"),
    ("2577", "İdari Yargılama Usulü Kanunu"),
    ("4734", "Kamu İhale Kanunu"),
    ("6100", "Hukuk Muhakemeleri Kanunu"),
)


def _percentile(samples: list[float], quantile: float) -> float:
    """Nearest-rank percentile over raw samples (no interpolation needed for
    this sample size -- unlike ``evaluation/latency/budget_report.py``'s
    histogram-bucket interpolation, these are exact wall-clock draws)."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(0, min(len(ordered) - 1, int(round(quantile * (len(ordered) - 1)))))
    return ordered[rank]


async def _measure_one(number: str, kind: str = "KANUN") -> tuple[bool, float]:
    start = time.perf_counter()
    try:
        resolved = await resolve_and_fetch(number, kind)
    except Exception:
        resolved = None
    elapsed = time.perf_counter() - start
    return resolved is not None, elapsed


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="mevzuat-mcp'ye karşı gerçek resolve_and_fetch gecikmesini ölç."
    )
    parser.add_argument(
        "--repeat", type=int, default=5, help="Her kanun için tekrar sayısı (varsayılan 5)."
    )
    parser.add_argument(
        "--outside-curated-only",
        action="store_true",
        help="Yalnızca curated 7 dışındaki kanunları ölç (sıcak taban etkisini hariç tut).",
    )
    args = parser.parse_args()

    register_servers()
    if not is_registered(MEVZUAT_SERVER):
        print(
            "mevzuat sunucusu kayıtlı değil -- MEVZUAT_MCP_ENABLED veya "
            "MEVZUAT_SOURCE=mcp ayarlarından birinin açık olması gerekir."
        )
        return 1

    targets: list[tuple[str, str, str]] = [
        (ref.number, ref.kind, ref.title) for ref in CURATED_LEGISLATION
    ]
    if args.outside_curated_only:
        targets = []
    targets += [(number, "KANUN", title) for number, title in OUTSIDE_CURATED]

    print("=" * 88)
    print("   mevzuat-mcp Gecikme Ölçümü")
    print("=" * 88)
    print(f"Tekrar/kanun : {args.repeat}")
    print(f"Kanun sayısı : {len(targets)}\n")
    print(f"{'kanun':10s} {'başlık':45s} {'ort(s)':>8} {'min(s)':>8} {'max(s)':>8} {'başarı'}")
    print("-" * 88)

    all_samples: list[float] = []
    for number, kind, title in targets:
        samples: list[float] = []
        successes = 0
        for _ in range(args.repeat):
            ok, elapsed = await _measure_one(number, kind)
            samples.append(elapsed)
            successes += ok
        all_samples.extend(samples)
        avg = sum(samples) / len(samples)
        print(
            f"{number:10s} {title[:45]:45s} {avg:8.2f} {min(samples):8.2f} "
            f"{max(samples):8.2f} {successes}/{len(samples)}"
        )

    print("-" * 88)
    if all_samples:
        p50 = _percentile(all_samples, 0.50)
        p95 = _percentile(all_samples, 0.95)
        p99 = _percentile(all_samples, 0.99)
        print(f"Toplam gözlem: {len(all_samples)}")
        print(f"p50: {p50:.2f}s   p95: {p95:.2f}s   p99: {p99:.2f}s")
        print()
        if p95 > 10.0:
            print(
                "p95, ~8-10s'nin belirgin üzerinde -- evrak analizi/taslak "
                "gibi bir per-request canlı yola genişleme, bağlantı "
                "havuzlaması eklenene kadar beklemeli."
            )
        else:
            print("p95, ~8-10s eşiğinin altında.")
    print("=" * 88)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
