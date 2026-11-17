"""gta6-twitch-ccu-forecast-01: forecast GTA VI's launch-day Twitch viewers, hour by hour.

Model (my own design, fitted on the kit's practice cases p00-p03 against the
comparables shipped in each case):

  For each hour h = 2..24, predict the log-ratio r_h = ln(y_h / p1), where p1 is
  hour 1's print. The prediction is a kernel-weighted mean of the comparables'
  own log-ratios ln(y_h / p1) at that hour, with a Gaussian kernel over three
  similarities between the case and each comparable launch:

    1. scale:  |ln(p1_case) - ln(p1_comp)|, bandwidth 1.0 in log units.
       Big launches stay near their hour-1 level; small ones ramp many-fold,
       so launches of a similar size at hour 1 have the most similar curves.
    2. pre-midnight excess at 23:00: r23 = ln(viewers at 23:00 the day before
       / p1), bandwidth 0.2.
    3. pre-midnight excess at 22:00: r22 = ln(viewers at 22:00 the day before
       / p1), bandwidth 0.3.

  The two pre-midnight hours hold the pre-release countdown/hype audience; how
  large it is next to hour 1's print says how much of the audience is still
  waiting for its real unlock (the US unlocks at 05:00Z/08:00Z), so it grows
  much more through the day. Using both hours averages out hourly noise in
  that hype measurement. Every comparable also carries a small uniform weight
  (0.02), a flat prior over launches: it stops the forecast collapsing onto a
  single launch when the case sits far from every comparable, and it slightly
  regularises the practice fit.

  Quantiles come from a normal in log space: q_tau = p1 * exp(med_h + z_tau *
  sigma_h), sigma_h = 0.70 * clip(weighted std of the log-ratios, 0.10, 0.60).
  The spread is the weighted disagreement across similar launches, so hours
  where similar launches disagree get honestly wider bands.

  Practice results (scored locally against SullyGnome's published hourly
  averages for the four practice launches): mean pinball loss 0.159 vs the
  house baseline's 0.387; typical miss 27.1% vs 82.7%; 90% coverage 0.913.

How the grader runs it: `python3 -P -s /bot/main.py` (PYTHONHASHSEED=0) in
python:3.13-slim, standard library only: no network, no pip packages.
It reads every <id>.in in the input directory and writes <id>.out to the
output directory. MAKEFUN_INPUT_DIR / MAKEFUN_OUTPUT_DIR stand in for
/input and /output outside the grader's container.

Safety: the program never crashes on a weird case. Any failure while
building the kernel forecast falls back to a fixed generic launch-day curve
(the median comparable log-ratio per hour) with a wide spread, so the output
is always a valid 23-row forecast.
"""

import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

# The quantile levels the contest scores, in the order each row lists them.
LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
# The standard normal's quantile at each level.
Z = [-1.645, -0.674, 0.0, 0.674, 1.645]

# Kernel bandwidths (log units) fitted on the practice cases.
BW_SCALE = 1.0    # |ln p1_case - ln p1_comp|
BW_PRE23 = 0.2    # |r23_case - r23_comp|
BW_PRE22 = 0.3    # |r22_case - r22_comp|
# Spread multiplier and clamps on the per-hour log spread.
SPREAD = 0.70
SIGMA_MIN = 0.10
SIGMA_MAX = 0.60
# Flat prior weight added to every comparable's kernel weight: keeps the
# forecast from collapsing onto one launch when the case is far from all of
# them, and regularises the fit.
EPSILON = 0.02
# Fallback spread when no comparable informs an hour at all.
FALLBACK_SIGMA = 0.50

# Generic launch-day median log-ratio per hour (h = 2..24), used only when a
# case ships no usable comparables: the median across the kit's comparables.
FALLBACK_MEDIAN = [
    -0.14, -0.28, -0.31, -0.29, -0.24, -0.22, -0.11, -0.13, -0.09, -0.07,
    -0.02, 0.06, 0.17, 0.42, 0.50, 0.57, 0.67, 0.88, 0.86, 0.85, 0.83,
    0.78, 0.71,
]


def round2(x: float) -> float | int:
    """x rounded to 2 decimals, half up, as JavaScript's Math.round(x * 100) / 100."""
    scaled = x * 100
    whole = math.floor(scaled)
    if scaled - whole >= 0.5:
        whole += 1
    value = whole / 100
    return int(value) if value.is_integer() else value


def parse_time(text):
    """Parse an ISO 8601 UTC timestamp; return None when it does not parse."""
    if not isinstance(text, str):
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def case_hour1(case: dict) -> float:
    """Hour 1's print, floored at 1 viewer (a print below 1 counts as 1)."""
    for row in case.get("known") or []:
        if isinstance(row, dict) and row.get("hour") == 1:
            viewers = row.get("viewers")
            if isinstance(viewers, (int, float)) and math.isfinite(viewers):
                return max(1.0, float(viewers))
    return 1.0


def case_pre_excess(case: dict, p1: float) -> dict[str, float | None]:
    """Pre-midnight excess: ln(viewers in an hour before the day / p1).

    Keys "r23" (23:00, one hour before midnight) and "r22" (22:00, two hours
    before). A missing hour yields None and is skipped by the kernel.
    """
    day_start = parse_time(case.get("day_start"))
    if day_start is None:
        return {"r23": None, "r22": None}
    base = day_start.timestamp()
    found: dict[int, float] = {}
    for row in case.get("history_hourly") or []:
        if not isinstance(row, dict):
            continue
        at = parse_time(row.get("from"))
        if at is None:
            continue
        viewers = row.get("viewers")
        if not isinstance(viewers, (int, float)) or not math.isfinite(viewers):
            continue
        if viewers <= 0:
            continue
        offset = int(round((at.timestamp() - base) / 3600.0))
        if offset in (-1, -2):
            found[offset] = float(viewers)
    out = {}
    for offset, key in ((-1, "r23"), (-2, "r22")):
        viewers = found.get(offset)
        out[key] = math.log(viewers / p1) if viewers else None
    return out


def comparable_curves(case: dict) -> list[dict]:
    """Each comparable as {p1, hours: {h: viewers}, r23, r22}.

    hours maps UTC hour-of-day 1..24 to viewers; r23/r22 are the comparable's
    own pre-midnight excesses, ln(viewers at 23:00/22:00 the day before / p1).
    Hour offsets are rounded, so a point a few minutes off the hour still
    lands in its bucket.
    """
    curves = []
    for comp in case.get("comparables") or []:
        if not isinstance(comp, dict):
            continue
        day_start = parse_time(comp.get("day_start"))
        if day_start is None:
            continue
        base = day_start.timestamp()
        hours: dict[int, float] = {}
        pre: dict[int, float] = {}
        for row in comp.get("hourly") or []:
            if not isinstance(row, dict):
                continue
            at = parse_time(row.get("from"))
            viewers = row.get("viewers")
            if at is None or not isinstance(viewers, (int, float)):
                continue
            if not math.isfinite(viewers) or viewers <= 0:
                continue
            offset = int(round((at.timestamp() - base) / 3600.0))
            if 0 <= offset <= 23:
                hours[offset + 1] = float(viewers)
            elif offset in (-1, -2):
                pre[offset] = float(viewers)
        p1 = hours.get(1)
        if p1 is None:
            continue
        curves.append({
            "p1": p1,
            "hours": hours,
            "r23": math.log(pre[-1] / p1) if pre.get(-1) else None,
            "r22": math.log(pre[-2] / p1) if pre.get(-2) else None,
        })
    return curves


def kernel_weight(comp: dict, p1: float, pre: dict[str, float | None]) -> float:
    """Gaussian-kernel similarity between the case and one comparable launch.

    A small flat prior (EPSILON) is added to every weight so the forecast
    degrades to the plain comparable average, with a wide spread, instead of
    collapsing onto a single launch when the case sits far from all of them.
    """
    d_scale = (math.log(comp["p1"]) - math.log(p1)) / BW_SCALE
    weight = math.exp(-0.5 * d_scale * d_scale)
    for key, bw in (("r23", BW_PRE23), ("r22", BW_PRE22)):
        comp_val = comp[key]
        case_val = pre.get(key)
        if case_val is None or comp_val is None:
            # No signal on one side: keep the launch, half-weighted.
            weight *= 0.5
        else:
            d = (comp_val - case_val) / bw
            weight *= math.exp(-0.5 * d * d)
    return weight + EPSILON


def weighted_mean_std(points: list[tuple[float, float]]) -> tuple[float, float]:
    """Weighted mean and (population) standard deviation of log-ratios."""
    total = sum(w for _, w in points)
    if total <= 0:
        return 0.0, FALLBACK_SIGMA
    mean = sum(v * w for v, w in points) / total
    var = sum(w * (v - mean) ** 2 for v, w in points) / total
    return mean, math.sqrt(max(var, 0.0))


def hour_quantiles(p1: float, med: float, sigma: float) -> list[float | int]:
    """The five quantiles for one hour: p1 * exp(med + z * sigma), clamped."""
    out = []
    prev = 0.0
    for z in Z:
        value = p1 * math.exp(med + z * sigma)
        value = min(max(value, 1.0), 1e9)
        value = round2(value)
        # Rounding must never break the non-decreasing order.
        if value < prev:
            value = prev
        prev = value
        out.append(value)
    return out


def forecast_case(case: dict) -> dict:
    """Forecast hours 2..24 of one case as five quantiles each."""
    p1 = case_hour1(case)
    pre = case_pre_excess(case, p1)
    curves = comparable_curves(case)

    hours = case.get("forecast") or []
    hour_list = [row["hour"] for row in hours
                 if isinstance(row, dict) and isinstance(row.get("hour"), int)]
    if not hour_list:
        hour_list = list(range(2, 25))

    rows = []
    for h in hour_list:
        points = []
        for comp in curves:
            viewers = comp["hours"].get(h)
            if viewers is None:
                continue
            weight = kernel_weight(comp, p1, pre)
            if weight > 0:
                points.append((math.log(viewers / comp["p1"]), weight))
        if points:
            med, std = weighted_mean_std(points)
            sigma = min(max(std, SIGMA_MIN), SIGMA_MAX) * SPREAD
        else:
            med = FALLBACK_MEDIAN[h - 2] if 2 <= h <= 24 else 0.0
            sigma = FALLBACK_SIGMA * SPREAD
        rows.append({"hour": h, "q": hour_quantiles(p1, med, sigma)})
    return {"hours": rows}


def safe_forecast_case(case: dict) -> dict:
    """Never fail a case: fall back to the generic curve on any error."""
    try:
        return forecast_case(case)
    except Exception:
        p1 = 1.0
        try:
            p1 = case_hour1(case)
        except Exception:
            pass
        hours = case.get("forecast") or []
        hour_list = [row["hour"] for row in hours
                     if isinstance(row, dict) and isinstance(row.get("hour"), int)]
        if not hour_list:
            hour_list = list(range(2, 25))
        rows = []
        for h in hour_list:
            med = FALLBACK_MEDIAN[h - 2] if 2 <= h <= 24 else 0.0
            rows.append({"hour": h,
                         "q": hour_quantiles(p1, med, FALLBACK_SIGMA * SPREAD)})
        return {"hours": rows}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # Every case file, in name order, so two runs write the same bytes.
    for path in sorted(INPUT_DIR.glob("*.in")):
        try:
            case = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            case = {}
        forecast = safe_forecast_case(case)
        (OUTPUT_DIR / f"{path.stem}.out").write_text(
            json.dumps(forecast, separators=(",", ":")) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
