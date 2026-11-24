#!/usr/bin/env python3
"""Rank candidate features for the AEC Model Bridge roadmap.

Input: a JSON file with a list of candidates. Each candidate has 1-5 ratings for

    reach        how many target users (BIM coordinators/managers) would use it
    impact       how much it changes their day (time saved, risk removed)
    gap          how far behind competitors we are without it (1 = we lead, 5 = everyone has it)
    fit          fit with the product's promise: human-approved, verifiable, safe changes
    confidence   how sure we are about the four ratings above
    effort       cost to build (1 = days, 5 = months)
    live_risk    how much it depends on live-Revit acceptance we cannot run in CI (1 = none)

Score = weighted value / cost, the same shape as RICE. Value is a weighted sum of
reach, impact, gap and fit, multiplied by confidence. Cost is effort plus a penalty
for live-Revit risk. Because the weights are judgement calls, the script also runs a
Monte Carlo pass: it redraws the weights from a Dirichlet distribution around the
defaults and the ratings with +-1 noise, then reports how often each candidate lands
in the top 10. A feature that ranks high only under one exact set of weights is
fragile; ``p_top10`` and ``rank_p10``/``rank_p90`` expose that.

Usage:
    python scripts/roadmap/score_features.py candidates.json [--runs 5000] [--seed 7]
        [--markdown out.md] [--csv out.csv]

Standard library only, so it runs anywhere the repo does.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence

VALUE_WEIGHTS: Dict[str, float] = {"reach": 0.25, "impact": 0.35, "gap": 0.15, "fit": 0.25}
LIVE_RISK_WEIGHT = 0.5
RATING_FIELDS = ("reach", "impact", "gap", "fit", "confidence", "effort", "live_risk")


@dataclass(frozen=True)
class Candidate:
    id: str
    title: str
    category: str
    summary: str
    ratings: Dict[str, float]
    competitors: Sequence[str] = ()
    mock_testable: bool = True

    @staticmethod
    def from_dict(raw: dict) -> "Candidate":
        ratings = {}
        for key in RATING_FIELDS:
            value = float(raw[key])
            if not 1 <= value <= 5:
                raise ValueError(f"{raw.get('id')}: {key}={value} is outside 1-5")
            ratings[key] = value
        return Candidate(
            id=str(raw["id"]),
            title=str(raw["title"]),
            category=str(raw.get("category", "other")),
            summary=str(raw.get("summary", "")),
            ratings=ratings,
            competitors=tuple(raw.get("competitors", ())),
            mock_testable=bool(raw.get("mock_testable", True)),
        )


def score(ratings: Dict[str, float], weights: Dict[str, float] = VALUE_WEIGHTS,
          live_risk_weight: float = LIVE_RISK_WEIGHT) -> float:
    value = sum(weights[k] * ratings[k] for k in weights) * (ratings["confidence"] / 5.0)
    cost = ratings["effort"] + live_risk_weight * (ratings["live_risk"] - 1)
    return round(100.0 * value / cost, 2)


def _dirichlet(rng: random.Random, means: Dict[str, float], concentration: float) -> Dict[str, float]:
    draws = {k: rng.gammavariate(max(m * concentration, 1e-3), 1.0) for k, m in means.items()}
    total = sum(draws.values())
    return {k: v / total for k, v in draws.items()}


def _jitter(rng: random.Random, ratings: Dict[str, float]) -> Dict[str, float]:
    return {k: min(5.0, max(1.0, v + rng.choice((-1, 0, 0, 0, 1)))) for k, v in ratings.items()}


def monte_carlo(cands: List[Candidate], runs: int, seed: int, top_n: int = 10) -> Dict[str, dict]:
    rng = random.Random(seed)
    ranks: Dict[str, List[int]] = {c.id: [] for c in cands}
    for _ in range(runs):
        weights = _dirichlet(rng, VALUE_WEIGHTS, concentration=20.0)
        live_w = rng.uniform(0.25, 1.0)
        scored = sorted(cands, key=lambda c: score(_jitter(rng, c.ratings), weights, live_w), reverse=True)
        for position, cand in enumerate(scored, start=1):
            ranks[cand.id].append(position)
    out = {}
    for cid, positions in ranks.items():
        positions.sort()
        out[cid] = {
            "p_top10": round(sum(1 for p in positions if p <= top_n) / runs, 3),
            "rank_median": statistics.median(positions),
            "rank_p10": positions[int(0.10 * (runs - 1))],
            "rank_p90": positions[int(0.90 * (runs - 1))],
        }
    return out


def rank(cands: List[Candidate], runs: int, seed: int) -> List[dict]:
    mc = monte_carlo(cands, runs, seed) if runs else {}
    rows = []
    for c in cands:
        row = {"id": c.id, "title": c.title, "category": c.category, "summary": c.summary,
               "score": score(c.ratings), "mock_testable": c.mock_testable,
               "competitors": ", ".join(c.competitors), **c.ratings}
        row.update(mc.get(c.id, {}))
        rows.append(row)
    # Primary key: robustness (probability of top 10), then the point score.
    rows.sort(key=lambda r: (r.get("p_top10", 0.0), r["score"]), reverse=True)
    for i, row in enumerate(rows, start=1):
        row["rank"] = i
    return rows


def to_markdown(rows: List[dict], limit: int | None = None) -> str:
    head = ("| # | Feature | Category | Score | P(top 10) | Rank p10-p90 | Effort | Mock-testable |\n"
            "| ---: | --- | --- | ---: | ---: | --- | ---: | :---: |\n")
    body = []
    for r in rows[:limit]:
        span = f"{r.get('rank_p10', '-')}-{r.get('rank_p90', '-')}"
        body.append(f"| {r['rank']} | **{r['title']}** - {r['summary']} | {r['category']} | {r['score']:.1f} "
                    f"| {r.get('p_top10', 0):.0%} | {span} | {int(r['effort'])} | {'yes' if r['mock_testable'] else 'no'} |")
    return head + "\n".join(body) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("candidates", type=Path)
    parser.add_argument("--runs", type=int, default=5000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--csv", type=Path)
    args = parser.parse_args(argv)

    cands = [Candidate.from_dict(x) for x in json.loads(args.candidates.read_text(encoding="utf-8"))]
    ids = [c.id for c in cands]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate candidate ids")
    rows = rank(cands, args.runs, args.seed)

    if args.markdown:
        args.markdown.write_text(to_markdown(rows), encoding="utf-8")
    if args.csv:
        with args.csv.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
    print(to_markdown(rows, args.top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
