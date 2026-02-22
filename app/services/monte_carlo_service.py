"""Monte Carlo simulation engine for FAIR-based risk quantification.

Pure Python — no numpy, scipy, or external dependencies.
Implements PERT and triangular distributions, Poisson sampling,
sensitivity analysis (Spearman rank correlation), and histogram/exceedance output.
"""

import math
import random
import json
from datetime import datetime
from sqlalchemy.orm import Session

from models import (
    RiskAssessmentItem, RiskSimulationRun, ScenarioControlLink,
    EFFECTIVENESS_NUMERIC,
)


# ── Distribution Samplers ────────────────────────────────────────────────

def pert_sample(min_val, likely, max_val, lambda_=4, rng=None):
    """Sample from a PERT (modified Beta) distribution.

    The PERT distribution is parameterized by min, most-likely, max and a shape
    parameter lambda_ (default 4). We convert to standard Beta(alpha, beta)
    parameters and sample using the Gamma-ratio method from Python stdlib.
    """
    rng = rng or random

    # Auto-swap if min > max
    if min_val > max_val:
        min_val, max_val = max_val, min_val

    # Clamp likely within bounds
    likely = max(min_val, min(likely, max_val))

    # Degenerate case: no range
    if max_val - min_val < 1e-12:
        return likely

    mu = (min_val + lambda_ * likely + max_val) / (lambda_ + 2)

    # When likely == mu (or very close), the standard PERT alpha formula
    # divides by (likely - mu) which is zero.  Fall back to symmetric Beta
    # shape parameters derived from lambda_.
    denom = (likely - mu) * (max_val - min_val)
    if abs(denom) < 1e-12:
        # Symmetric fallback: alpha = beta = 1 + lambda_/2  (bell-shaped)
        a1 = 1.0 + lambda_ / 2.0
        a2 = a1
    else:
        a1 = ((mu - min_val) * (2 * likely - min_val - max_val)) / denom
        if a1 <= 0:
            a1 = 1.0 + lambda_ / 2.0
        a2 = a1 * (max_val - mu) / (mu - min_val) if (mu - min_val) > 1e-12 else 1.0 + lambda_ / 2.0
        if a2 <= 0:
            a2 = 1.0 + lambda_ / 2.0

    # Sample from Beta(a1, a2) using gammavariate
    x = rng.gammavariate(a1, 1.0)
    y = rng.gammavariate(a2, 1.0)
    if x + y == 0:
        beta_sample = 0.5
    else:
        beta_sample = x / (x + y)

    return min_val + beta_sample * (max_val - min_val)


def triangular_sample(min_val, likely, max_val, rng=None):
    """Triangular distribution — uses Python stdlib random.triangular()."""
    rng = rng or random
    # Auto-swap if min > max
    if min_val > max_val:
        min_val, max_val = max_val, min_val
    if max_val - min_val < 1e-12:
        return likely
    # Clamp mode within bounds
    mode = max(min_val, min(likely, max_val))
    return rng.triangular(min_val, max_val, mode)


def poisson_sample(lam, rng=None):
    """Poisson deviate — Knuth algorithm for small lambda, Gaussian approx for large."""
    rng = rng or random
    if lam <= 0:
        return 0
    if lam < 30:
        # Knuth algorithm
        L = math.exp(-lam)
        k = 0
        p = 1.0
        while True:
            k += 1
            p *= rng.random()
            if p <= L:
                return k - 1
    else:
        # Gaussian approximation for large lambda
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))


# ── Control Effectiveness ────────────────────────────────────────────────

def compute_combined_effectiveness(control_links):
    """Diminishing-returns model: 1 - product(1 - weight_i * numeric_eff_i)."""
    if not control_links:
        return 0.0

    product = 1.0
    for link in control_links:
        eff_str = link.effectiveness_at_assessment or "NONE"
        numeric_eff = EFFECTIVENESS_NUMERIC.get(eff_str, 0.0)
        weight = link.weight if link.weight is not None else 1.0
        weight = max(0.0, min(1.0, weight))
        product *= (1.0 - weight * numeric_eff)

    return round(1.0 - product, 4)


# ── Sensitivity Analysis (Spearman Rank Correlation) ─────────────────────

def _rank(values):
    """Assign ranks to values (1-based, average ties)."""
    n = len(values)
    indexed = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[indexed[j + 1]] == values[indexed[j]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[indexed[k]] = avg_rank
        i = j + 1
    return ranks


def spearman_correlation(x, y):
    """Compute Spearman rank correlation between two lists."""
    n = len(x)
    if n < 3:
        return 0.0
    rx = _rank(x)
    ry = _rank(y)

    mean_rx = sum(rx) / n
    mean_ry = sum(ry) / n

    num = sum((rx[i] - mean_rx) * (ry[i] - mean_ry) for i in range(n))
    den_x = math.sqrt(sum((rx[i] - mean_rx) ** 2 for i in range(n)))
    den_y = math.sqrt(sum((ry[i] - mean_ry) ** 2 for i in range(n)))

    if den_x == 0 or den_y == 0:
        return 0.0
    return num / (den_x * den_y)


# ── Core Simulation ──────────────────────────────────────────────────────

def run_simulation(
    tef_min, tef_likely, tef_max,
    vuln_min, vuln_likely, vuln_max,
    plm_min, plm_likely, plm_max,
    slm_min, slm_likely, slm_max,
    control_effectiveness=0.0,
    iterations=10000,
    seed=None,
    distribution="PERT",
):
    """Run Monte Carlo simulation using the FAIR model.

    Returns dict with:
        annual_losses: list[float]
        stats: {mean, median, p5, p10, p90, p95, std_dev, min, max}
        histogram: [{bin_start, bin_end, count}]
        exceedance: [{threshold, probability}]
        sensitivity: [{factor, correlation, rank}]
    """
    rng = random.Random(seed)
    sample_fn = pert_sample if distribution == "PERT" else triangular_sample

    annual_losses = []
    tef_samples = []
    vuln_samples = []
    plm_samples = []
    slm_samples = []

    loss_reduction = 1.0 - max(0.0, min(1.0, control_effectiveness))

    for _ in range(iterations):
        # 1. Sample Threat Event Frequency
        tef = sample_fn(tef_min, tef_likely, tef_max, rng=rng)
        tef = max(0.0, tef)
        tef_samples.append(tef)

        # 2. Sample Vulnerability (clamp 0-1)
        vuln = sample_fn(vuln_min, vuln_likely, vuln_max, rng=rng)
        vuln = max(0.0, min(1.0, vuln))
        vuln_samples.append(vuln)

        # 3. Loss Event Frequency (Poisson)
        lef = poisson_sample(tef * vuln, rng=rng)

        # 4. For each loss event, sample PLM + SLM
        annual_loss = 0.0
        iter_plm = 0.0
        iter_slm = 0.0
        for _ in range(lef):
            plm = sample_fn(plm_min, plm_likely, plm_max, rng=rng)
            plm = max(0.0, plm)
            slm = sample_fn(slm_min, slm_likely, slm_max, rng=rng)
            slm = max(0.0, slm)
            annual_loss += (plm + slm) * loss_reduction
            iter_plm += plm
            iter_slm += slm

        plm_samples.append(iter_plm)
        slm_samples.append(iter_slm)
        annual_losses.append(annual_loss)

    # ── Statistics ────────────────────────────────────────────────────────
    sorted_losses = sorted(annual_losses)
    n = len(sorted_losses)

    def percentile(data, pct):
        idx = pct / 100.0 * (len(data) - 1)
        lo = int(math.floor(idx))
        hi = int(math.ceil(idx))
        if lo == hi:
            return data[lo]
        return data[lo] + (data[hi] - data[lo]) * (idx - lo)

    mean_val = sum(sorted_losses) / n if n else 0.0
    variance = sum((x - mean_val) ** 2 for x in sorted_losses) / n if n else 0.0
    std_dev = math.sqrt(variance)

    stats = {
        "mean": round(mean_val, 2),
        "median": round(percentile(sorted_losses, 50), 2),
        "p5": round(percentile(sorted_losses, 5), 2),
        "p10": round(percentile(sorted_losses, 10), 2),
        "p90": round(percentile(sorted_losses, 90), 2),
        "p95": round(percentile(sorted_losses, 95), 2),
        "std_dev": round(std_dev, 2),
        "min": round(sorted_losses[0], 2) if n else 0.0,
        "max": round(sorted_losses[-1], 2) if n else 0.0,
    }

    # ── Histogram (30 bins) ──────────────────────────────────────────────
    histogram = []
    if n > 0:
        lo_val = sorted_losses[0]
        hi_val = sorted_losses[-1]
        num_bins = 30
        if hi_val <= lo_val:
            hi_val = lo_val + 1.0
        bin_width = (hi_val - lo_val) / num_bins
        bins = [0] * num_bins
        for val in sorted_losses:
            idx = int((val - lo_val) / bin_width)
            if idx >= num_bins:
                idx = num_bins - 1
            bins[idx] += 1
        for i in range(num_bins):
            histogram.append({
                "bin_start": round(lo_val + i * bin_width, 2),
                "bin_end": round(lo_val + (i + 1) * bin_width, 2),
                "count": bins[i],
            })

    # ── Exceedance Curve (50 points) ─────────────────────────────────────
    exceedance = []
    if n > 0:
        num_points = 50
        lo_val = sorted_losses[0]
        hi_val = sorted_losses[-1]
        if hi_val <= lo_val:
            hi_val = lo_val + 1.0
        step = (hi_val - lo_val) / (num_points - 1) if num_points > 1 else 1.0
        for i in range(num_points):
            threshold = lo_val + i * step
            count_above = sum(1 for v in sorted_losses if v > threshold)
            exceedance.append({
                "threshold": round(threshold, 2),
                "probability": round(count_above / n, 4),
            })

    # ── Sensitivity (Spearman rank correlation) ──────────────────────────
    factors = [
        ("TEF", tef_samples),
        ("VULN", vuln_samples),
        ("PLM", plm_samples),
        ("SLM", slm_samples),
    ]
    sensitivity = []
    for name, samples in factors:
        corr = spearman_correlation(samples, annual_losses)
        sensitivity.append({"factor": name, "correlation": round(corr, 4)})

    # Sort by absolute correlation descending
    sensitivity.sort(key=lambda x: abs(x["correlation"]), reverse=True)
    for rank, item in enumerate(sensitivity, 1):
        item["rank"] = rank

    return {
        "annual_losses": annual_losses,
        "stats": stats,
        "histogram": histogram,
        "exceedance": exceedance,
        "sensitivity": sensitivity,
    }


# ── Orchestrator (DB integration) ────────────────────────────────────────

def run_and_store(db: Session, item_id: int, user_id: int = None,
                  iterations: int = 10000, seed: int = None,
                  distribution: str = "PERT") -> RiskSimulationRun:
    """Read FAIR factors from the assessment item, compute control effectiveness,
    run simulation, and store the RiskSimulationRun record."""

    item = db.query(RiskAssessmentItem).filter(RiskAssessmentItem.id == item_id).first()
    if not item:
        return None

    # Validate FAIR factors are present
    for attr in ("tef_min", "tef_likely", "tef_max",
                 "vuln_min", "vuln_likely", "vuln_max",
                 "plm_min", "plm_likely", "plm_max",
                 "slm_min", "slm_likely", "slm_max"):
        if getattr(item, attr, None) is None:
            return None

    # Auto-correct min/max ordering (user may have entered them backwards)
    def _ordered(lo, hi):
        if lo is not None and hi is not None and lo > hi:
            return hi, lo
        return lo, hi

    tef_min, tef_max = _ordered(item.tef_min, item.tef_max)
    vuln_min, vuln_max = _ordered(item.vuln_min, item.vuln_max)
    plm_min, plm_max = _ordered(item.plm_min, item.plm_max)
    slm_min, slm_max = _ordered(item.slm_min, item.slm_max)

    # Compute combined control effectiveness from linked controls
    control_links = db.query(ScenarioControlLink).filter(
        ScenarioControlLink.item_id == item_id
    ).all()
    combined_eff = compute_combined_effectiveness(control_links)

    # Run simulation
    result = run_simulation(
        tef_min=tef_min, tef_likely=item.tef_likely, tef_max=tef_max,
        vuln_min=vuln_min, vuln_likely=item.vuln_likely, vuln_max=vuln_max,
        plm_min=plm_min, plm_likely=item.plm_likely, plm_max=plm_max,
        slm_min=slm_min, slm_likely=item.slm_likely, slm_max=slm_max,
        control_effectiveness=combined_eff,
        iterations=iterations,
        seed=seed,
        distribution=distribution,
    )

    # Store simulation run
    run = RiskSimulationRun(
        item_id=item_id,
        iterations=iterations,
        seed=seed,
        distribution_type=distribution,
        mean_ale=result["stats"]["mean"],
        median_ale=result["stats"]["median"],
        p5_ale=result["stats"]["p5"],
        p10_ale=result["stats"]["p10"],
        p90_ale=result["stats"]["p90"],
        p95_ale=result["stats"]["p95"],
        std_dev=result["stats"]["std_dev"],
        min_ale=result["stats"]["min"],
        max_ale=result["stats"]["max"],
        combined_control_effectiveness=combined_eff,
        sensitivity_json=json.dumps(result["sensitivity"]),
        histogram_json=json.dumps(result["histogram"]),
        exceedance_json=json.dumps(result["exceedance"]),
        run_by_user_id=user_id,
        run_at=datetime.utcnow(),
    )
    db.add(run)
    db.flush()
    return run
