"""GeoIPAgent validation on synthetic multi-country traffic (Phase 8, Group C).

Builds labelled batches from REAL public addresses (sampled from the local
GeoLite2-City database, so the agent's own lookup path is what gets exercised),
runs each through the full engine, and reports how often the GeoIPAgent
triggers and how often the final verdict calls an attack.

The traffic is synthetic. The scenario mix (what counts as benign, how much
foreign traffic a legitimate global audience has) is an assumption, so treat
the numbers as directional, not as a measured accuracy.

Run from the product root:
    cd /home/azael/Documents/Code/abuse/detection
    source ../.venv/bin/activate
    python scripts/geo_validation.py [--trials 40]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.agents import geo_agent
from engine.pipeline.run import PipelineRunner

HOME = "US"
_BASE = datetime(2024, 1, 15, 14, 0, 0)

# name -> (is_attack_label, description)
SCENARIOS = {
    "benign_all_home": (False, "100% home-country traffic"),
    "benign_few_travellers": (False, "92% home, 8% from 2 foreign countries"),
    "benign_small_diaspora": (False, "85% home, 15% spread over 5 countries"),
    "benign_global_audience": (False, "70% home, 30% spread over 8 countries (legitimate global users)"),
    "attack_single_country": (True, "55% from one foreign country"),
    "attack_distributed_foreign": (True, "45% foreign, spread over 8 countries"),
    "attack_botnet_spread": (True, "60 low-volume IPs across 20 countries"),
}


def public_ips_by_country(per_country: int = 12, max_countries: int = 45, seed: int = 7) -> dict[str, list[str]]:
    """Probe random IPv4 space through the agent's own lookup until enough countries are found."""
    rng = random.Random(seed)
    found: dict[str, list[str]] = {}
    for _ in range(3_000_000):
        ip = ".".join(str(rng.randint(1, 223)) for _ in range(4))
        country = geo_agent._lookup_country(ip)
        if not country:
            continue
        bucket = found.setdefault(country, [])
        if len(bucket) < per_country:
            bucket.append(ip)
        if len(found) >= max_countries and sum(len(v) >= per_country for v in found.values()) >= max_countries:
            break
    return {c: ips for c, ips in found.items() if len(ips) >= per_country}


def _records(ip_weights: list[tuple[str, float]], n: int, rng: random.Random) -> list[dict]:
    ips, weights = zip(*ip_weights)
    chosen = rng.choices(ips, weights=weights, k=n)
    return [
        {
            "timestamp": (_BASE + timedelta(seconds=i * 2)).isoformat() + "Z",
            "ip": ip, "method": "GET", "endpoint": "/api/items", "status": 200,
            "response_size": 512, "latency": 45.0, "user_agent": "Mozilla/5.0", "org_id": "geo-validation",
        }
        for i, ip in enumerate(chosen)
    ]


def build_batch(name: str, pool: dict[str, list[str]], rng: random.Random) -> list[dict]:
    home_ips = pool[HOME]
    foreign = [c for c in pool if c != HOME]
    rng.shuffle(foreign)

    def spread(countries: list[str], total_weight: float) -> list[tuple[str, float]]:
        ips = [ip for c in countries for ip in pool[c]]
        return [(ip, total_weight / len(ips)) for ip in ips]

    home = [(ip, 1.0 / len(home_ips)) for ip in home_ips]

    def mix(home_share: float, foreign_parts: list[tuple[str, float]]) -> list[tuple[str, float]]:
        return [(ip, w * home_share) for ip, w in home] + foreign_parts

    if name == "benign_all_home":
        return _records(home, 200, rng)
    if name == "benign_few_travellers":
        return _records(mix(0.92, spread(foreign[:2], 0.08)), 200, rng)
    if name == "benign_small_diaspora":
        return _records(mix(0.85, spread(foreign[:5], 0.15)), 200, rng)
    if name == "benign_global_audience":
        return _records(mix(0.70, spread(foreign[:8], 0.30)), 200, rng)
    if name == "attack_single_country":
        return _records(mix(0.45, spread(foreign[:1], 0.55)), 200, rng)
    if name == "attack_distributed_foreign":
        return _records(mix(0.55, spread(foreign[:8], 0.45)), 200, rng)
    if name == "attack_botnet_spread":
        ips = [ip for c in foreign[:20] for ip in pool[c][:3]]
        return _records([(ip, 1.0 / len(ips)) for ip in ips], 200, rng)
    raise KeyError(name)


def run_scenario(name: str, pool: dict[str, list[str]], trials: int) -> dict:
    geo_hits = attack_hits = 0
    for t in range(trials):
        rng = random.Random(f"{name}:{t}")
        batch = build_batch(name, pool, rng)
        runner = PipelineRunner("geo-validation", home_country=HOME)
        verdict = runner.run(batch)
        scores = {s["agent_name"]: s for s in (verdict.get("agent_scores") or [])}
        geo_hits += bool(scores.get("GeoIPAgent", {}).get("triggered"))
        attack_hits += bool(verdict["is_attack"])
    return {"geo_trigger_rate": geo_hits / trials, "attack_rate": attack_hits / trials}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trials", type=int, default=40)
    args = ap.parse_args()

    pool = public_ips_by_country()
    if HOME not in pool or len(pool) < 22:
        print(f"Not enough resolvable countries ({len(pool)}). Is {geo_agent._MMDB_PATH} present?")
        return 2
    print(f"Address pool: {len(pool)} countries, {sum(map(len, pool.values()))} addresses. Trials per scenario: {args.trials}")
    print(f"{'scenario':30s} {'label':7s} {'geo triggers':>13s} {'final attack':>13s}  description")

    tp = fn = fp = tn = 0
    geo_tp = geo_fn = geo_fp = geo_tn = 0
    for name, (is_attack, desc) in SCENARIOS.items():
        r = run_scenario(name, pool, args.trials)
        print(f"{name:30s} {'attack' if is_attack else 'benign':7s} {r['geo_trigger_rate']:13.0%} {r['attack_rate']:13.0%}  {desc}")
        n = args.trials
        if is_attack:
            geo_tp += round(r["geo_trigger_rate"] * n); geo_fn += n - round(r["geo_trigger_rate"] * n)
            tp += round(r["attack_rate"] * n); fn += n - round(r["attack_rate"] * n)
        else:
            geo_fp += round(r["geo_trigger_rate"] * n); geo_tn += n - round(r["geo_trigger_rate"] * n)
            fp += round(r["attack_rate"] * n); tn += n - round(r["attack_rate"] * n)

    def pr(tp, fp, fn):
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        return p, r

    gp, gr = pr(geo_tp, geo_fp, geo_fn)
    fpp, fr = pr(tp, fp, fn)
    print(f"\nGeoIPAgent alone : precision {gp:.2f}, recall {gr:.2f}")
    print(f"Final verdict    : precision {fpp:.2f}, recall {fr:.2f}")
    print("Impossible travel is not exercised: a real database maps one address to one country.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
