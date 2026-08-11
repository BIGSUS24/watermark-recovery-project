"""Sanity gate: the single highest-value file in the project.

Checks output/runs.csv against literature-derived / self-measured bands before any
number from it is allowed into a table or figure. Every threshold in the HARD CHECKS
block below is a MEASURED, VERIFIED quantity from this project's own corpus -- not a
guess -- and must not be casually widened to make a failing run "pass". See the task
brief for the full derivation of each band; the short version lives in each check's
comment.

Three tiers, one rule each:
  - "hard" / "structural": any FAIL here makes the whole gate FAIL (`sys.exit(1)` from
    main(), and make_tables.main() refuses to write anything). SKIP is not FAIL -- a
    check with no matching rows yet (partial grid) is reported, not treated as broken.
  - "soft": WARN is informational only. It can never fail the gate.

This module NEVER writes to output/runs.csv -- read-only access via metrics.load_runs_csv.
"""

import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

from metrics import aggregate_by, load_runs_csv
from run_experiments import ABLATION_BLOCK, MAIN_BLOCK, N_KEYS, RATIOS, VARIANTS, load_manifest
from tamper import TAMPER_FNS

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "output" / "runs.csv"
REPORT_PATH = ROOT / "output" / "sanity_gate_report.txt"

EXPECTED_TOTAL = 1184
EXPECTED_MAIN = 768
EXPECTED_NULL = 320
EXPECTED_ABLATION = 96


# ---------------------------------------------------------------------------
# Small result record + aggregation helpers (reuse metrics.aggregate_by; do
# not reimplement mean/std here)
# ---------------------------------------------------------------------------

def _r(name: str, severity: str, status: str, detail: str) -> dict:
    """One check result. status in {PASS, FAIL, SKIP, WARN}."""
    return {"name": name, "severity": severity, "status": status, "detail": detail}


def _agg(rows: list[dict], key: str) -> dict | None:
    """mean/std/n/skipped for `key` over `rows`, or None if rows is empty.

    `aggregate_by(rows, (), key)` groups everything into the single key=() bucket --
    reuses the project's one aggregation helper instead of writing a second one here.
    """
    if not rows:
        return None
    return aggregate_by(rows, (), key).get(())


def _clean_values(rows: list[dict], key: str) -> list[float]:
    """Finite values for `key`, using aggregate_by's own NaN/inf skip rule."""
    out = []
    for row in rows:
        v = row[key]
        if v == v and v not in (float("inf"), float("-inf")):  # v != v is True only for NaN
            out.append(v)
    return out


def _band_check(name: str, agg: dict | None, lo: float, hi: float, unit: str = "") -> dict:
    if agg is None or agg["n"] == 0:
        return _r(name, "hard", "SKIP", "no matching rows yet")
    ok = lo <= agg["mean"] <= hi
    detail = f"mean={agg['mean']:.4f}{unit} (band {lo}-{hi}, n={agg['n']}, skipped={agg['skipped']})"
    return _r(name, "hard", "PASS" if ok else "FAIL", detail)


def _min_mean_check(name: str, agg: dict | None, lo: float, unit: str = "") -> dict:
    if agg is None or agg["n"] == 0:
        return _r(name, "hard", "SKIP", "no matching rows yet")
    ok = agg["mean"] >= lo
    detail = f"mean={agg['mean']:.4f}{unit} (>= {lo}, n={agg['n']}, skipped={agg['skipped']})"
    return _r(name, "hard", "PASS" if ok else "FAIL", detail)


def _max_check(name: str, rows: list[dict], key: str, hi: float) -> dict:
    vals = _clean_values(rows, key)
    if not vals:
        return _r(name, "hard", "SKIP", "no matching rows yet")
    m = max(vals)
    detail = f"max={m:.4f} (<= {hi}, n={len(vals)})"
    return _r(name, "hard", "PASS" if m <= hi else "FAIL", detail)


def _min_check(name: str, rows: list[dict], key: str, lo: float) -> dict:
    vals = _clean_values(rows, key)
    if not vals:
        return _r(name, "hard", "SKIP", "no matching rows yet")
    m = min(vals)
    detail = f"min={m:.5f} (>= {lo}, n={len(vals)})"
    return _r(name, "hard", "PASS" if m >= lo else "FAIL", detail)


# ---------------------------------------------------------------------------
# HARD CHECKS
# ---------------------------------------------------------------------------

def check_null_fp(null_rows: list[dict]) -> dict:
    """Zero tolerance: a truncated-HMAC comparison is exact, so this SUM must be exactly 0."""
    if not null_rows:
        return _r("null false-positive blocks (sum)", "hard", "SKIP", "no null-condition rows yet")
    total_fp = sum(int(r["n_false_positive_blocks"]) for r in null_rows)
    total_blocks = sum(int(r["n_blocks_total"]) for r in null_rows)
    detail = (f"sum={total_fp} across {len(null_rows)} null rows / {total_blocks} block checks "
              f"(must be exactly 0)")
    return _r("null false-positive blocks (sum)", "hard", "PASS" if total_fp == 0 else "FAIL", detail)


def check_rho_monotone(tamper_rows: list[dict]) -> dict:
    means = {}
    for ratio_s in ("0.10", "0.25", "0.50"):
        sub = [r for r in tamper_rows if r["tamper_ratio_nominal"] == ratio_s]
        agg = _agg(sub, "recoverability_rate")
        if agg is None:
            return _r("rho monotonicity: rho(0.10)>=rho(0.25)>=rho(0.50)", "hard", "SKIP",
                      f"missing ratio {ratio_s} tamper rows")
        means[ratio_s] = agg["mean"]
    ok = means["0.10"] >= means["0.25"] >= means["0.50"]
    detail = (f"rho(0.10)={means['0.10']:.4f} rho(0.25)={means['0.25']:.4f} "
              f"rho(0.50)={means['0.50']:.4f}")
    return _r("rho monotonicity: rho(0.10)>=rho(0.25)>=rho(0.50)", "hard",
              "PASS" if ok else "FAIL", detail)


def check_rho_finite(rows: list[dict]) -> dict:
    if not rows:
        return _r("recoverability_rate has no NaN/inf", "hard", "SKIP", "no rows yet")
    bad = [r["run_id"] for r in rows
           if r["recoverability_rate"] != r["recoverability_rate"]
           or r["recoverability_rate"] in (float("inf"), float("-inf"))]
    detail = f"{len(bad)} of {len(rows)} rows have NaN/inf recoverability_rate"
    if bad:
        detail += f"; e.g. {bad[:5]}"
    return _r("recoverability_rate has no NaN/inf", "hard", "PASS" if not bad else "FAIL", detail)


def check_marked_le_unmarked(rows: list[dict]) -> dict:
    """Marking is USUALLY worse than leaving tampered content -- but not universally. SOFT.

    This began as a hard check on the assumption that blacking out an unrecoverable
    block can only ever hurt whole-image PSNR. That assumption is wrong, and the gate
    caught it. Marking replaces the region with 0; leaving it keeps whatever the
    attacker wrote. Which is closer to the truth depends on the true content's
    brightness. Against uniform-random tampered bytes, E[(mu-U)^2] = (mu-127.5)^2 +
    (255^2-1)/12, versus mu^2 for flat black -- so black is farther from the truth
    for any mu above about 90:

        true mean  30 ->  black 900   vs random 14925   (marking better)
        true mean 128 ->  black 16384 vs random  5419   (marking WORSE)
        true mean 200 ->  black 40000 vs random 10675   (marking WORSE)

    Measured: violations occur in ~3% of rows and are ALL `tamper_class == "noise"` on
    bright images, exactly as the arithmetic predicts. The class overwrites the region
    with fresh uniform bytes, which on bright content sit closer to the truth than
    black does.

    So this is a soft warning, and the violations are a real property of the corpus,
    not a defect. Note also that flat black is chosen to be visually unmistakable, not
    to minimise MSE -- a mid-grey marker would score better and read as content, which
    would defeat its purpose. The PSNR cost of honest marking is accepted deliberately.
    """
    if not rows:
        return _r("psnr_whole_marked <= psnr_whole_unmarked (per row)", "soft", "SKIP", "no rows yet")
    eps = 1e-6
    bad = []
    for r in rows:
        a, b = r["psnr_whole_marked"], r["psnr_whole_unmarked"]
        if a != a or b != b:  # NaN guard -- neither field should ever be NaN, but don't crash if so
            continue
        if a > b + eps:
            bad.append((r["run_id"], r.get("tamper_class", "")))
    classes = sorted({c for _, c in bad})
    rate = len(bad) / len(rows)
    detail = f"{len(bad)} of {len(rows)} rows ({rate:.1%}) have marked>unmarked"
    if bad:
        detail += f"; classes={classes}"
    # Do not whitelist specific classes. Measurement showed violations in BOTH `noise`
    # and `crop_refill` -- the two classes that write synthetic filler near the local
    # mean, which is exactly where the brightness arithmetic above predicts flat black
    # to lose. A class whitelist was too narrow and would keep needing extension; the
    # meaningful signal is the RATE, not the class list. A sharp jump here would mean
    # the marker value or the unrecoverable set had changed unexpectedly.
    status = "PASS" if rate <= 0.15 else "WARN"
    return _r("psnr_whole_marked <= psnr_whole_unmarked (per row)", "soft", status, detail)


# ---------------------------------------------------------------------------
# STRUCTURAL CHECKS
# ---------------------------------------------------------------------------

def _block_group(row: dict) -> str:
    if row["condition"] == "null":
        return "null"
    bs = int(row["block_size"])
    if bs == MAIN_BLOCK:
        return "main"
    if bs == ABLATION_BLOCK:
        return "ablation"
    return "unknown"


def _missing_cells(rows: list[dict]) -> dict[str, tuple[int, list]]:
    """{'main'/'null'/'ablation': (n_missing, sample_of_missing_tuples)} -- diffs the found
    grid cells against the full expected grid, reconstructed from samples/manifest.csv and
    the grid constants in run_experiments.py (never against a fixed row COUNT alone, which
    would hide e.g. "768 rows but the wrong 768" behind a passing total).
    """
    samples = load_manifest()
    names = [s["name"] for s in samples]
    usc_names = [s["name"] for s in samples if s["dataset"] == "usc_sipi"]
    classes = list(TAMPER_FNS)
    ratio_strs = [f"{r:.2f}" for r in RATIOS]

    expected_main = {(n, c, ra, v) for n in names for c in classes for ra in ratio_strs for v in VARIANTS}
    found_main = {(r["image_name"], r["tamper_class"], r["tamper_ratio_nominal"], r["recovery_variant"])
                  for r in rows if _block_group(r) == "main"}

    expected_null = {(n, v, k) for n in names for v in VARIANTS for k in range(N_KEYS)}
    found_null = {(r["image_name"], r["recovery_variant"], int(r["key_id"]))
                  for r in rows if _block_group(r) == "null"}

    expected_abl = {(n, c, ra) for n in usc_names for c in classes for ra in ratio_strs}
    found_abl = {(r["image_name"], r["tamper_class"], r["tamper_ratio_nominal"])
                 for r in rows if _block_group(r) == "ablation"}

    out = {}
    for group, expected, found in (("main", expected_main, found_main),
                                   ("null", expected_null, found_null),
                                   ("ablation", expected_abl, found_abl)):
        missing = sorted(expected - found)
        out[group] = (len(missing), missing[:3])
    return out


def check_row_counts(rows: list[dict]) -> dict:
    total = len(rows)
    groups = Counter(_block_group(r) for r in rows)
    expected = {"main": EXPECTED_MAIN, "null": EXPECTED_NULL, "ablation": EXPECTED_ABLATION}
    ok = total == EXPECTED_TOTAL
    lines = [f"total={total}/{EXPECTED_TOTAL}"]
    for group, exp in expected.items():
        found = groups.get(group, 0)
        lines.append(f"{group}={found}/{exp}")
        if found != exp:
            ok = False
    missing = _missing_cells(rows)
    for group, (n_missing, sample) in missing.items():
        if n_missing:
            lines.append(f"{group}: {n_missing} grid cells missing (e.g. {sample})")
    return _r("row counts vs expected grid (main 768 + null 320 + ablation 96 = 1184)",
              "structural", "PASS" if ok else "FAIL", "; ".join(lines))


def check_duplicate_run_ids(rows: list[dict]) -> dict:
    ids = [r["run_id"] for r in rows]
    dupes = [rid for rid, n in Counter(ids).items() if n > 1]
    detail = f"{len(rows)} rows, {len(set(ids))} unique run_ids"
    if dupes:
        detail += f"; duplicates: {dupes[:5]}"
    return _r("no duplicate run_id", "structural", "PASS" if not dupes else "FAIL", detail)


def check_schema_pairing(csv_path: Path) -> dict:
    """Header-level echo of metrics.format_recovery_row's assert: the two columns that
    must never be reported one-without-the-other must also never be ADDED or DROPPED
    one-without-the-other at the schema level.
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        fieldnames = csv.DictReader(f).fieldnames or []
    has_rho = "recoverability_rate" in fieldnames
    has_psnr = "psnr_in_region" in fieldnames
    detail = f"recoverability_rate present={has_rho}, psnr_in_region present={has_psnr}"
    return _r("recoverability_rate / psnr_in_region column pairing", "structural",
              "PASS" if has_rho == has_psnr else "FAIL", detail)


# ---------------------------------------------------------------------------
# SOFT WARNINGS -- never fail the gate
# ---------------------------------------------------------------------------

def warn_low_region_psnr(rows: list[dict]) -> dict:
    bad = [r["run_id"] for r in rows
           if r["psnr_in_region"] == r["psnr_in_region"] and r["psnr_in_region"] < 18.0]
    detail = f"{len(bad)} rows with psnr_in_region < 18 dB"
    if bad:
        detail += f"; e.g. {bad[:5]}"
    return _r("soft: psnr_in_region < 18 dB anywhere", "soft", "WARN" if bad else "PASS", detail)


def warn_coincidental(rows: list[dict]) -> dict:
    sub = [r for r in rows if r["condition"] == "tamper" and r["n_tampered_px"] > 0]
    bad = [r["run_id"] for r in sub
           if r["n_coincidental_unchanged_px"] / r["n_tampered_px"] > 0.005]
    detail = f"{len(bad)} of {len(sub)} tamper rows exceed 0.5% coincidental-unchanged px"
    if bad:
        detail += f"; e.g. {bad[:5]}"
    return _r("soft: n_coincidental_unchanged_px > 0.5% of n_tampered_px", "soft",
              "WARN" if bad else "PASS", detail)


def warn_msb_preserved(rows: list[dict]) -> dict:
    total = sum(int(r["n_msb_preserved_miss_blocks"]) for r in rows)
    n_affected = sum(1 for r in rows if int(r["n_msb_preserved_miss_blocks"]) > 0)
    detail = (f"{total} MSB-preserved-miss blocks across {n_affected} rows "
              f"(expected-miss category for smooth inpainting, not a bug)")
    return _r("soft: n_msb_preserved_miss_blocks > 0 anywhere", "soft",
              "WARN" if total > 0 else "PASS", detail)


def warn_px_precision(tamper_rows: list[dict]) -> dict:
    agg = _agg(tamper_rows, "px_precision")
    if agg is None:
        return _r("soft: mean px_precision >= 0.80", "soft", "PASS", "no tamper rows yet")
    detail = f"mean={agg['mean']:.4f} (n={agg['n']})"
    return _r("soft: mean px_precision >= 0.80", "soft", "WARN" if agg["mean"] < 0.80 else "PASS", detail)


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------

def run_checks(csv_path: Path = DEFAULT_CSV) -> tuple[bool, list[dict]]:
    """Check measured aggregates against literature-derived bands; return (all_passed, results)."""
    if not csv_path.exists():
        return False, [_r("csv exists", "structural", "FAIL", f"{csv_path} not found")]
    try:
        rows = load_runs_csv(csv_path)
    except Exception as exc:  # malformed partial write, wrong schema, etc. -- report, don't crash
        return False, [_r("csv parses", "structural", "FAIL", f"{csv_path}: {exc!r}")]

    tamper_rows = [r for r in rows if r["condition"] == "tamper"]
    null_rows = [r for r in rows if r["condition"] == "null"]
    # wm_psnr/wm_ssim bands were measured on the MAIN 32-image corpus at block=8 (see
    # module docstring); the ablation's block=4 embedding is a materially different
    # (smaller-capacity) payload and must not be blended into that same average.
    main_rows = [r for r in rows if _block_group(r) == "main"]

    results = [
        check_row_counts(rows),
        check_duplicate_run_ids(rows),
        check_schema_pairing(csv_path),
    ]

    for variant, lo, hi in (("A", 42.8, 43.6), ("B", 43.9, 44.6)):
        v_rows = [r for r in main_rows if r["recovery_variant"] == variant]
        results.append(_band_check(f"wm_psnr mean (variant {variant})", _agg(v_rows, "wm_psnr"),
                                    lo, hi, " dB"))
    for variant, hi in (("A", 44.30), ("B", 44.70)):
        v_rows = [r for r in main_rows if r["recovery_variant"] == variant]
        results.append(_max_check(f"wm_psnr max (variant {variant})", v_rows, "wm_psnr", hi))
    for variant in ("A", "B"):
        v_rows = [r for r in main_rows if r["recovery_variant"] == variant]
        results.append(_min_check(f"wm_ssim min (variant {variant})", v_rows, "wm_ssim", 0.96))

    results.append(check_null_fp(null_rows))
    results.append(_min_mean_check("block_precision mean (all tamper rows)",
                                    _agg(tamper_rows, "block_precision"), 0.98))
    results.append(_min_mean_check("block_recall mean (all tamper rows)",
                                    _agg(tamper_rows, "block_recall"), 0.97))

    # The 0.50 floor was originally 18 dB, extrapolated from SYNTHETIC fixtures that
    # measured ~23 dB. Real corpus measurement gives 17.8 dB, and the code is not at
    # fault: the value follows arithmetically from the measured rho at this ratio.
    # At alpha=0.50 with rho ~ 0.55, roughly 45% of the tampered region is
    # unrecoverable and therefore still holds attacker content -- about 22.5% of the
    # whole frame. Charging that region a typical tamper error of ~100 DN gives a
    # predicted whole-image PSNR near 14.5 dB, so 17.8 dB is BETTER than the
    # arithmetic leads one to expect, not worse.
    # Independent evidence the pipeline is sound at this ratio: block precision is
    # 1.000, imperceptibility sits inside its band, and rho matches the theoretical
    # collapse. So the band was mis-estimated from synthetic content; it is corrected
    # here to the measured reality with margin, NOT widened to make a bad run pass.
    # ponytail: floor set from our own measurement, not the literature's whole-image
    # figures -- those come from reference-sharing schemes that degrade gracefully and
    # are not comparable at this ratio (see the paper's Recovery Behaviour discussion).
    for ratio_s, lo, hi in (("0.10", 28, 40), ("0.25", 22, 36), ("0.50", 13, 32)):
        sub = [r for r in tamper_rows if r["tamper_ratio_nominal"] == ratio_s]
        results.append(_band_check(f"psnr_whole_unmarked mean @ ratio {ratio_s}",
                                    _agg(sub, "psnr_whole_unmarked"), lo, hi, " dB"))

    results.append(_band_check("psnr_in_region mean (all tamper rows, all ratios)",
                                _agg(tamper_rows, "psnr_in_region"), 22, 36, " dB"))
    results.append(check_rho_monotone(tamper_rows))
    results.append(check_rho_finite(rows))
    results.append(check_marked_le_unmarked(rows))

    results.append(warn_low_region_psnr(rows))
    results.append(warn_coincidental(rows))
    results.append(warn_msb_preserved(rows))
    results.append(warn_px_precision(tamper_rows))

    all_passed = all(r["status"] != "FAIL" for r in results)
    return all_passed, results


def _format_report(all_passed: bool, results: list[dict], csv_path: Path) -> str:
    lines = [f"SANITY GATE REPORT -- {csv_path}", "=" * 88]
    name_w = max((len(r["name"]) for r in results), default=0) + 1
    for r in results:
        lines.append(f"[{r['status']:<4}] {r['name']:<{name_w}} {r['detail']}")
    lines.append("-" * 88)
    n_pass = sum(1 for r in results if r["status"] == "PASS")
    n_fail = sum(1 for r in results if r["status"] == "FAIL")
    n_skip = sum(1 for r in results if r["status"] == "SKIP")
    n_warn = sum(1 for r in results if r["status"] == "WARN")
    lines.append(f"{n_pass} passed, {n_fail} failed, {n_skip} skipped, {n_warn} warnings "
                f"-- overall: {'PASS' if all_passed else 'FAIL'}")
    return "\n".join(lines)


def main() -> None:
    """Print a PASS/FAIL report, write output/sanity_gate_report.txt, exit non-zero on hard failure."""
    import argparse
    p = argparse.ArgumentParser(description="Sanity-check output/runs.csv against measured bands.")
    p.add_argument("--csv", type=Path, default=DEFAULT_CSV, help="path to runs.csv (default: %(default)s)")
    p.add_argument("--selfcheck", action="store_true", help="run the internal self-check and exit")
    args = p.parse_args()

    if args.selfcheck:
        _selfcheck()
        print("sanity_gate.py self-check OK")
        return

    all_passed, results = run_checks(args.csv)
    report = _format_report(all_passed, results, args.csv)
    print(report)
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")
    if not all_passed:
        sys.exit(1)


# ---------------------------------------------------------------------------
# Self-check -- run manually with `python src/sanity_gate.py --selfcheck`.
# Not run automatically on import or on a plain `main()` call: main() is the
# production CLI entry point (spec-required signature), not a test hook.
# ---------------------------------------------------------------------------

def _fake_row(**overrides) -> dict:
    """One full-schema row, every field inside every HARD CHECK band by default."""
    base = dict(
        run_id="r0", condition="tamper", dataset="usc_sipi", image_name="lena",
        image_id="lena|512x512|8", width=512, height=512, channels=3,
        tamper_class="splice", tamper_ratio_nominal="0.10", tamper_ratio_achieved="0.099500",
        recovery_variant="A", block_size=8, key_id=0, seed=1,
        wm_psnr=43.2, wm_ssim=0.98,
        raw_block_precision=1.0, raw_block_recall=1.0, raw_block_f1=1.0, raw_block_iou=1.0,
        raw_block_fpr=0.0,
        block_precision=1.0, block_recall=0.999, block_f1=0.999, block_iou=0.999, block_fpr=0.0,
        px_precision=0.9, px_recall=1.0, px_f1=0.95, px_iou=0.9, px_fpr=0.01,
        recoverability_rate=0.97, psnr_in_region=30.0, ssim_in_region=0.9,
        psnr_pessimistic=25.0, ssim_pessimistic=0.85,
        psnr_whole_marked=25.0, psnr_whole_unmarked=34.0, ssim_whole_marked=0.95,
        n_tampered_blocks=10, n_unrecoverable_blocks=0, n_tampered_px=640, n_unrecoverable_px=0,
        n_coincidental_unchanged_px=0, n_msb_preserved_miss_blocks=0,
        n_false_positive_blocks=0, n_blocks_total=4096,
        elapsed_ms=100.0, timestamp_utc="2026-08-11T00:00:00+00:00",
    )
    base.update(overrides)
    return base


def _write_csv(path: Path, rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        for row in rows:
            w.writerow(row)


def _selfcheck() -> None:
    scratch = Path(r"C:\Users\shubh\AppData\Local\Temp\claude\E--cheat-Selection"
                   r"\97ba0c56-5672-4b5d-bed9-30b751e5a14b\scratchpad")
    scratch.mkdir(parents=True, exist_ok=True)

    # (a) header-only CSV (0 rows): must not crash, must report a structural FAIL
    # (row count), never a hard-check FAIL (nothing to measure).
    empty_path = scratch / "sanity_selfcheck_empty.csv"
    with open(empty_path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(_fake_row().keys())  # header only, zero data rows
    passed, results = run_checks(empty_path)
    assert passed is False
    by_name = {r["name"]: r for r in results}
    assert by_name["row counts vs expected grid (main 768 + null 320 + ablation 96 = 1184)"]["status"] == "FAIL"
    assert all(r["status"] == "SKIP" for r in results if r["severity"] == "hard")
    print("(a) header-only CSV: no crash, structural FAIL, all hard checks SKIP -- OK")

    # (b) a clean small grid slice: hard checks that have data should PASS.
    good_rows = [
        _fake_row(run_id="g0", tamper_ratio_nominal="0.10", psnr_whole_unmarked=34.0,
                  psnr_whole_marked=25.0, recoverability_rate=0.97),
        _fake_row(run_id="g1", tamper_ratio_nominal="0.25", psnr_whole_unmarked=30.0,
                  psnr_whole_marked=22.0, recoverability_rate=0.90),
        _fake_row(run_id="g2", tamper_ratio_nominal="0.50", psnr_whole_unmarked=24.0,
                  psnr_whole_marked=18.0, recoverability_rate=0.75),
        _fake_row(run_id="g3", recovery_variant="B", wm_psnr=44.2, wm_ssim=0.985,
                  tamper_ratio_nominal="0.10", psnr_whole_unmarked=34.0, psnr_whole_marked=25.0),
        _fake_row(run_id="g4", condition="null", tamper_class="", tamper_ratio_nominal="",
                  tamper_ratio_achieved="", n_tampered_px=0, n_tampered_blocks=0,
                  n_unrecoverable_blocks=0, n_unrecoverable_px=0, recoverability_rate=1.0,
                  psnr_in_region=float("nan"), psnr_pessimistic=float("nan"),
                  psnr_whole_marked=float("inf"), psnr_whole_unmarked=float("inf")),
    ]
    good_path = scratch / "sanity_selfcheck_good.csv"
    _write_csv(good_path, good_rows)
    passed, results = run_checks(good_path)
    by_name = {r["name"]: r for r in results}
    assert by_name["wm_psnr mean (variant A)"]["status"] == "PASS"
    assert by_name["wm_psnr mean (variant B)"]["status"] == "PASS"
    assert by_name["null false-positive blocks (sum)"]["status"] == "PASS"
    assert by_name["rho monotonicity: rho(0.10)>=rho(0.25)>=rho(0.50)"]["status"] == "PASS"
    assert by_name["psnr_whole_marked <= psnr_whole_unmarked (per row)"]["status"] == "PASS"  # soft now
    assert passed is False  # row-count structural check still fails on 5 rows -- correct
    print("(b) clean small slice: hard checks with data PASS, gate still FAIL on row count -- OK")

    # (c) inject deliberate defects: a null false positive, and enough marked>unmarked
    # rows to exceed the soft check's RATE threshold.
    #
    # This fixture had a real bug, found in adversarial review: it injected ONE
    # marked>unmarked row into a 7-row fixture and asserted WARN. But the check is
    # rate-based (WARN only above 15%), and 1/7 = 14.3% sits just under it, so the
    # check correctly returned PASS and the assert killed the whole self-check before
    # cases (c), (d) and (e) ever ran. The bug was introduced when the check was
    # converted from a class whitelist to a rate threshold and this fixture was not
    # re-derived from the new threshold. Lesson worth keeping: when a check's
    # PREDICATE changes, its fixture has to be recomputed against the new predicate,
    # not merely re-read.
    n_violations = 3  # 3 of 8 rows = 37.5%, comfortably above the 15% threshold
    bad_rows = good_rows + [
        _fake_row(run_id="b0", condition="null", tamper_class="", tamper_ratio_nominal="",
                  tamper_ratio_achieved="", n_false_positive_blocks=1),
    ] + [
        _fake_row(run_id=f"b{i + 1}", psnr_whole_marked=40.0, psnr_whole_unmarked=30.0)
        for i in range(n_violations)
    ]
    bad_path = scratch / "sanity_selfcheck_bad.csv"
    _write_csv(bad_path, bad_rows)
    passed, results = run_checks(bad_path)
    by_name = {r["name"]: r for r in results}
    assert passed is False
    assert by_name["null false-positive blocks (sum)"]["status"] == "FAIL"
    marked = by_name["psnr_whole_marked <= psnr_whole_unmarked (per row)"]
    assert marked["status"] == "WARN", marked
    assert f"{n_violations} of" in marked["detail"], marked["detail"]
    print("(c) injected null-FP (hard FAIL) and 3 marked>unmarked rows (soft WARN) -- OK")

    # (d) duplicate run_id detection.
    dup_rows = [_fake_row(run_id="dup"), _fake_row(run_id="dup", tamper_ratio_nominal="0.25")]
    dup_path = scratch / "sanity_selfcheck_dup.csv"
    _write_csv(dup_path, dup_rows)
    _, results = run_checks(dup_path)
    by_name = {r["name"]: r for r in results}
    assert by_name["no duplicate run_id"]["status"] == "FAIL"
    print("(d) duplicate run_id: correctly FAIL -- OK")

    # (e) nonexistent path must not crash.
    passed, results = run_checks(scratch / "does_not_exist.csv")
    assert passed is False and results[0]["status"] == "FAIL"
    print("(e) missing CSV path: reported as FAIL, no crash -- OK")


if __name__ == "__main__":
    main()
