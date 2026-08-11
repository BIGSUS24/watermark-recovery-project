"""Metrics for the watermark-recovery project: imperceptibility, localization,
and recovery quality, plus small CSV/aggregation helpers for the results table.

Depends on nothing else in the project — only numpy, scikit-image, and stdlib
(csv, statistics, pathlib). embed.py and friends import `image_metrics` from
here; this module owns the project's single PSNR/SSIM implementation so two
parts of the project never quietly disagree by 0.3 dB.

Pinned choices for PSNR/SSIM (scikit-image's defaults have moved across
versions, so an unstated choice here is a reproducibility hole):
- `data_range=255` is ALWAYS passed explicitly, never dtype-inferred.
- `channel_axis=-1` is used for colour; `multichannel` was deprecated in 0.19
  and REMOVED in 0.20, so channel_axis is the only option on skimage 0.26.
- Colour SSIM is therefore the MEAN OF PER-CHANNEL SSIM (skimage loops per
  channel and averages the per-channel scalars), NOT SSIM of a luma/greyscale
  conversion.
- `win_size` is left at the library default (7, uniform window) — deliberately
  NOT Wang et al.'s original 11x11 Gaussian window — so a reader reproduces
  our numbers by calling structural_similarity() the same one-line way we do.

scikit-image 0.26 behaviour discovered while building this module (see
masked_ssim below for the fix): `structural_similarity(..., full=True)`
returns a full-size SSIM map S, but the *scalar* mssim it also computes
internally is `crop(S, pad).mean()` with `pad = (win_size - 1) // 2` — i.e.
skimage throws away a border strip before averaging, because the boundary
rows/cols of S are `uniform_filter` edge artifacts, not valid SSIM values.
Averaging the *whole* S (border included) does NOT reproduce skimage's own
scalar SSIM (measured ~0.003 off on a 32x32 test image) — only the
border-cropped mean does, to float precision. masked_ssim replicates that
crop before masking for exactly this reason.
"""

import csv
import statistics
from pathlib import Path

import numpy as np
from skimage.metrics import peak_signal_noise_ratio, structural_similarity


# ---------------------------------------------------------------------------
# Imperceptibility
# ---------------------------------------------------------------------------

def image_metrics(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """(PSNR dB, SSIM) between two same-shape uint8 images. THE project's only PSNR/SSIM."""
    colour = a.ndim == 3
    psnr_val = peak_signal_noise_ratio(a, b, data_range=255)
    ssim_val = structural_similarity(a, b, data_range=255,
                                      channel_axis=-1 if colour else None)
    # skimage returns inf for identical images (mse == 0 short-circuit).
    # Leave it as inf — clamping to a big finite number would silently lie
    # about a perfect match.
    return float(psnr_val), float(ssim_val)


def imperceptibility(original: np.ndarray, watermarked: np.ndarray) -> dict:
    """{'psnr': float, 'ssim': float} — thin dict wrapper over image_metrics."""
    psnr_val, ssim_val = image_metrics(original, watermarked)
    return {"psnr": psnr_val, "ssim": ssim_val}


# ---------------------------------------------------------------------------
# Localization confusion matrix
# ---------------------------------------------------------------------------

def confusion_counts(pred_mask: np.ndarray, gt_mask: np.ndarray) -> tuple[int, int, int, int]:
    """(tp, fp, fn, tn) as plain ints; serves both pixel-level and block-level masks."""
    # Coerce to bool at entry: `&` on a uint8 0/1 mask happens to work, but
    # `~` on uint8 flips bits (0->255, 1->254) instead of negating truthiness
    # — a real trap that would silently corrupt fp/fn/tn.
    pred_mask = np.asarray(pred_mask).astype(bool)
    gt_mask = np.asarray(gt_mask).astype(bool)
    tp = int(np.sum(pred_mask & gt_mask));  fp = int(np.sum(pred_mask & ~gt_mask))
    fn = int(np.sum(~pred_mask & gt_mask)); tn = int(np.sum(~pred_mask & ~gt_mask))
    return tp, fp, fn, tn


def loc_scores(tp: int, fp: int, fn: int, tn: int) -> dict:
    """precision, recall, f1, iou, fpr with pinned degenerate-case conventions.

    Degenerate cases follow sklearn's `zero_division=1` convention (a real
    citable library convention, not an invented rule): with nothing to raise
    a false alarm on, precision is vacuously 1.0; with nothing to find,
    recall is vacuously 1.0. This can never mask a miss on its own — a total
    miss (tp=0, fp=0, fn=100) gives precision=1.0 (correctly: no false alarms
    were raised) but recall, IoU and F1 all come out 0.0, and precision is
    never reported alone (see format_recovery_row for the analogous rule on
    the recovery side).
    """
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0   # no false alarms raised => vacuously correct
    recall    = tp / (tp + fn) if (tp + fn) > 0 else 1.0   # nothing to find => vacuously found
    iou       = tp / (tp + fp + fn) if (tp + fp + fn) > 0 else 1.0
    f1        = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0
    fpr       = fp / (fp + tn) if (fp + tn) > 0 else 0.0
    return {"precision": precision, "recall": recall, "f1": f1, "iou": iou, "fpr": fpr}


# ---------------------------------------------------------------------------
# Recovery metrics (in-region only)
# ---------------------------------------------------------------------------

def masked_psnr(a: np.ndarray, b: np.ndarray, mask: np.ndarray,
                 data_range: int = 255) -> float:
    """PSNR computed only over `mask`. Three lines, pinned to skimage's own definition.

    This is the one deliberate departure from "never reimplement a library
    metric": skimage's PSNR has no mask parameter, and the obvious
    alternative (crop to the mask's bounding box) leaks non-tampered border
    pixels into a number that is supposed to be region-only.
    """
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse = float(np.mean(diff[mask] ** 2))       # mask broadcasts over a trailing channel dim
    return float("inf") if mse == 0.0 else 10.0 * np.log10(data_range ** 2 / mse)


# win_size is pinned to skimage's default (7) everywhere in this module (see
# module docstring), so the border-crop pad it uses internally is fixed too.
# ponytail: pad is hardcoded to match that pinned win_size=7 default; if this
# module ever exposes win_size as a parameter, derive pad from it instead of
# hardcoding — leaving it hardcoded silently desyncs from a changed win_size.
_SSIM_WIN_SIZE = 7
_SSIM_PAD = (_SSIM_WIN_SIZE - 1) // 2


def masked_ssim(a: np.ndarray, b: np.ndarray, mask: np.ndarray,
                 data_range: int = 255) -> float:
    """Mean of skimage's per-pixel SSIM map restricted to `mask`.

    SSIM is a windowed (7x7) metric, not a per-pixel one, so it cannot be
    validly computed by masking then averaging the way PSNR can — but full=True
    is the closest correct primitive skimage offers, more correct than the
    common bounding-box-crop shortcut, which would leak non-tampered border
    pixels into a region-only number for the same reason masked_psnr avoids it.

    One more wrinkle found on skimage 0.26 (see module docstring): the S map
    returned by full=True still carries a border strip of filter-boundary
    artifacts that skimage itself excludes before computing its own scalar
    SSIM. We exclude that same strip before masking, or masked_ssim(a, b,
    <all-ones mask>) does not reproduce skimage's own aggregate SSIM value.
    """
    colour = a.ndim == 3
    _, S = structural_similarity(a, b, data_range=data_range,
                                  channel_axis=-1 if colour else None, full=True)
    mask = np.asarray(mask, dtype=bool)
    interior = np.zeros(mask.shape, dtype=bool)
    p = _SSIM_PAD
    interior[p:-p, p:-p] = True
    return float(S[mask & interior].mean())


def recovery_metrics(original: np.ndarray, recovered: np.ndarray,
                      gt_mask_px: np.ndarray,
                      unrecoverable_mask_px: np.ndarray) -> dict:
    """Recovery quality in-region, ALWAYS reported jointly with recoverability rate.

    WARNING: call this with the mask PREDICTED by detection, never with the
    tamper harness's ground-truth mask fed into recovery. This function
    cannot detect that misuse, but doing so would silently convert the whole
    experiment into an oracle-localization measurement.
    """
    gt = np.asarray(gt_mask_px, dtype=bool)
    unrec = np.asarray(unrecoverable_mask_px, dtype=bool)
    n_tampered = int(np.sum(gt))
    n_unrecoverable = int(np.sum(unrec))
    rho = 1.0 - n_unrecoverable / n_tampered if n_tampered > 0 else 1.0  # nothing tampered => 1.0

    optimistic = gt & ~unrec  # the region we actually recovered into
    if np.any(optimistic):
        psnr_in_region = masked_psnr(original, recovered, optimistic)
        ssim_in_region = masked_ssim(original, recovered, optimistic)
    else:
        psnr_in_region = float("nan")
        ssim_in_region = float("nan")

    if np.any(gt):
        # full gt_mask, not gt & ~unrec: unrecoverable pixels are charged here.
        psnr_pessimistic = masked_psnr(original, recovered, gt)
        ssim_pessimistic = masked_ssim(original, recovered, gt)
    else:
        psnr_pessimistic = float("nan")
        ssim_pessimistic = float("nan")

    # Whole-image recovered PSNR/SSIM. This is the quantity the published
    # literature actually reports (AuSR1/AuSR3/Wu-2025 all compare the recovered
    # image against the watermarked one over the WHOLE frame), so it is what our
    # baseline-comparison table must use. It is necessarily much higher than the
    # in-region number, because the untamped majority of the frame sits at the
    # ~44.15 dB 2-LSB embedding floor and dominates the mean squared error.
    # Reporting only the whole-image figure would flatter us; reporting only the
    # in-region figure would look inexplicably poor next to the literature.
    # Both are recorded, and the paper must state which is which.
    psnr_whole, ssim_whole = image_metrics(original, recovered)

    return {
        "recoverability_rate": rho,
        "psnr_in_region": psnr_in_region,
        "ssim_in_region": ssim_in_region,
        "psnr_pessimistic": psnr_pessimistic,
        "ssim_pessimistic": ssim_pessimistic,
        "psnr_whole": psnr_whole,
        "ssim_whole": ssim_whole,
        "n_tampered_px": n_tampered,
        "n_unrecoverable_px": n_unrecoverable,
    }


def format_recovery_row(row: dict) -> str:
    """Format a recovery result for a LaTeX table; refuses to format PSNR without rho.

    Recovery PSNR must never be reported without the recoverability rate
    beside it: excluding unrecoverable blocks from the PSNR silently
    inflates it, and several published papers do exactly that. The assert
    below is the point — a future refactor that drops rho from a row raises
    here immediately instead of quietly emitting an inflated PSNR-only
    number into a submitted table.
    """
    assert "recoverability_rate" in row and "psnr_in_region" in row, \
        "recovery PSNR must never be formatted without recoverability_rate alongside it"
    return f'{row["psnr_in_region"]:.2f} ({row["recoverability_rate"]:.2f})'


# ---------------------------------------------------------------------------
# MSB-preservation diagnostic
# ---------------------------------------------------------------------------

def msb_preserved_miss_blocks(original_blocks_msb: np.ndarray,
                               tampered_blocks_msb: np.ndarray,
                               gt_block_mask: np.ndarray,
                               pred_block_mask: np.ndarray) -> int:
    """Count misses whose block MSB content was bit-identical pre/post tamper.

    A "miss" here is: ground truth says tampered, prediction says clean. This
    function splits misses into the EXPECTED category — the block's MSB
    planes are bit-identical before and after tampering, i.e. smooth
    inpainting over already-flat content that a detector had no signal to
    catch — versus everything else, where ground truth is tampered,
    prediction is clean, but the MSB content genuinely changed. That
    remainder is an unexplained miss and would be a real detector bug. Separating
    the two is exactly the distinction an examiner probes.
    """
    gt = np.asarray(gt_block_mask).ravel().astype(bool)
    pred = np.asarray(pred_block_mask).ravel().astype(bool)
    n = gt.shape[0]
    # ponytail: assumes the blocks arrays' leading dimension already matches
    # the raveled mask length/order (K, ...block dims...). Ceiling: a caller
    # passing blocks shaped (rows, cols, ...) instead of (K, ...) would
    # silently misalign here. Upgrade path: accept an explicit block-grid
    # shape and reshape both masks and blocks from it, if that ever bites.
    orig = np.asarray(original_blocks_msb).reshape(n, -1)
    tamp = np.asarray(tampered_blocks_msb).reshape(n, -1)
    bit_identical = np.all(orig == tamp, axis=1)
    miss = gt & ~pred
    return int(np.sum(miss & bit_identical))


# ---------------------------------------------------------------------------
# CSV / aggregation helpers
# ---------------------------------------------------------------------------

# ponytail: fixed schema set rather than sniffing types from the CSV. Ceiling:
# a new metric column added elsewhere must be added here too or it silently
# stays a string. Upgrade path: try/except float() per field if that
# maintenance cost ever shows up.
NUMERIC_FIELDS: set[str] = {
    "psnr", "ssim",
    "precision", "recall", "f1", "iou", "fpr",
    "recoverability_rate", "psnr_in_region", "ssim_in_region",
    "psnr_pessimistic", "ssim_pessimistic",
    "psnr_whole", "ssim_whole",
    "n_tampered_px", "n_unrecoverable_px",
    "tp", "fp", "fn", "tn",
    # Added for run_experiments.py's output/runs.csv schema (see its module docstring).
    # tamper_ratio_nominal/tamper_ratio_achieved are deliberately NOT added here: they
    # are legitimately "" (empty string) on null-condition rows, and float("") raises --
    # they stay plain strings so load_runs_csv never chokes on a null row.
    "wm_psnr", "wm_ssim",
    "raw_block_precision", "raw_block_recall", "raw_block_f1", "raw_block_iou", "raw_block_fpr",
    "block_precision", "block_recall", "block_f1", "block_iou", "block_fpr",
    "px_precision", "px_recall", "px_f1", "px_iou", "px_fpr",
    "psnr_whole_marked", "psnr_whole_unmarked", "ssim_whole_marked",
    "n_tampered_blocks", "n_unrecoverable_blocks",
    "n_coincidental_unchanged_px", "n_msb_preserved_miss_blocks",
    "n_false_positive_blocks", "n_blocks_total",
    "elapsed_ms", "width", "height", "channels", "block_size", "key_id", "seed",
}


def load_runs_csv(path: Path) -> list[dict]:
    """csv.DictReader -> list[dict], numeric fields cast via a fixed schema set."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        for key in NUMERIC_FIELDS.intersection(row.keys()):
            # float() natively parses "inf" / "-inf" / "nan" literals — exactly
            # what Python's csv writer produces for those float values.
            row[key] = float(row[key])
    return rows


def aggregate_by(rows: list[dict], group_keys: tuple[str, ...],
                  value_key: str) -> dict[tuple, dict]:
    """Group rows and return {group_tuple: {'mean':..., 'std':..., 'n':..., 'skipped':...}}."""
    values: dict[tuple, list[float]] = {}
    skipped: dict[tuple, int] = {}
    for row in rows:
        key = tuple(row[k] for k in group_keys)
        v = float(row[value_key])
        bucket = values.setdefault(key, [])
        skipped.setdefault(key, 0)
        if v != v or v in (float("inf"), float("-inf")):  # v != v is True only for NaN
            skipped[key] += 1
            continue
        bucket.append(v)

    out: dict[tuple, dict] = {}
    for key, vals in values.items():
        n = len(vals)
        mean = statistics.mean(vals) if n > 0 else float("nan")
        std = statistics.pstdev(vals) if n >= 2 else 0.0  # std is 0.0 when n < 2, not undefined
        out[key] = {"mean": mean, "std": std, "n": n, "skipped": skipped[key]}
    return out


# ponytail: stdlib csv + statistics over pandas, even though pandas 3.0.5 is
# installed. The result set is ~1,184 rows — not a pandas-sized problem — and
# pandas 3.x is new enough that its API surface is a reproducibility risk for
# zero gain here. Upgrade to pandas only if row counts grow enough that
# aggregate_by's O(n) Python loop is actually slow.


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    a = np.full((32, 32, 3), 100, dtype=np.uint8)
    assert imperceptibility(a, a)["psnr"] == float("inf")
    assert abs(imperceptibility(a, a)["ssim"] - 1.0) < 1e-9

    # degenerate cases
    s = loc_scores(0, 0, 0, 32 * 32)                       # null condition
    assert s["precision"] == s["recall"] == s["iou"] == 1.0 and s["fpr"] == 0.0
    s2 = loc_scores(0, 0, 100, 0)                          # total miss
    assert s2["precision"] == 1.0 and s2["recall"] == 0.0 and s2["f1"] == 0.0 and s2["iou"] == 0.0

    # hand-computed confusion matrix on a 4x4 grid
    gt = np.zeros((4, 4), bool);   gt[0:2, 0:2] = True     # 4 positives
    pred = np.zeros((4, 4), bool); pred[1:3, 1:3] = True   # 4 predicted, 1 overlap
    tp, fp, fn, tn = confusion_counts(pred, gt)
    assert (tp, fp, fn, tn) == (1, 3, 3, 9)
    sc = loc_scores(tp, fp, fn, tn)
    assert abs(sc["precision"] - 0.25) < 1e-12 and abs(sc["recall"] - 0.25) < 1e-12
    assert abs(sc["iou"] - 1 / 7) < 1e-12

    # uint8 masks must work too (the ~ trap)
    assert confusion_counts(pred.astype(np.uint8), gt.astype(np.uint8)) == (1, 3, 3, 9)

    # masked_ssim over a full mask must equal skimage's own aggregate
    b = a.copy(); b[:16, :16, :] += 5
    whole = structural_similarity(a, b, data_range=255, channel_axis=-1)
    assert abs(masked_ssim(a, b, np.ones((32, 32), bool)) - whole) < 1e-9

    # masked_psnr over a full mask must equal skimage's PSNR
    assert abs(masked_psnr(a, b, np.ones((32, 32), bool))
               - peak_signal_noise_ratio(a, b, data_range=255)) < 1e-9

    # masked metrics really are region-restricted
    mask = np.zeros((32, 32), bool); mask[:16, :16] = True
    assert masked_psnr(a, b, mask) < masked_psnr(a, b, ~mask)   # damage is inside `mask`

    # recovery metrics: rho, joint reporting, empty-mask guards
    r = recovery_metrics(a, b, mask, np.zeros_like(mask))
    assert r["recoverability_rate"] == 1.0 and "psnr_in_region" in r
    half = mask.copy(); half[:8, :] = False                      # some of the region unrecoverable
    r2 = recovery_metrics(a, b, mask, ~half & mask)
    assert 0.0 < r2["recoverability_rate"] < 1.0
    assert r2["psnr_pessimistic"] <= r2["psnr_in_region"] + 1e-9  # pessimistic can only be worse
    r3 = recovery_metrics(a, a, np.zeros((32, 32), bool), np.zeros((32, 32), bool))
    assert r3["recoverability_rate"] == 1.0                       # nothing tampered
    format_recovery_row(r)                                        # must not raise
    try:
        format_recovery_row({"psnr_in_region": 1.0}); raise SystemExit("assert did not fire")
    except AssertionError:
        pass

    # msb-preservation diagnostic: expected miss (MSB unchanged) vs unexplained miss (MSB changed)
    gt_blk = np.array([True, True, False])
    pred_blk = np.array([False, False, False])   # both first two blocks are misses
    orig_msb = np.array([[1, 0, 1], [1, 0, 1], [0, 0, 0]], dtype=np.uint8)
    tamp_msb = orig_msb.copy(); tamp_msb[1] = [0, 1, 0]  # block 1's MSB genuinely changed
    assert msb_preserved_miss_blocks(orig_msb, tamp_msb, gt_blk, pred_blk) == 1  # only block 0 qualifies

    # aggregation, including nan/inf skipping
    rows = [{"g": "x", "v": 1.0}, {"g": "x", "v": 3.0}, {"g": "x", "v": float("nan")},
            {"g": "y", "v": 5.0}]
    agg = aggregate_by(rows, ("g",), "v")
    assert abs(agg[("x",)]["mean"] - 2.0) < 1e-12 and agg[("x",)]["n"] == 2
    assert agg[("x",)]["skipped"] == 1 and agg[("y",)]["std"] == 0.0

    # CSV round-trip through a temp file, including inf/nan literals
    scratch = Path(r"C:\Users\shubh\AppData\Local\Temp\claude\E--cheat-Selection\97ba0c56-5672-4b5d-bed9-30b751e5a14b\scratchpad")
    scratch.mkdir(parents=True, exist_ok=True)
    csv_path = scratch / "metrics_selfcheck.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["run", "psnr", "ssim", "tp"])
        w.writeheader()
        w.writerow({"run": "a", "psnr": "36.21", "ssim": "0.94", "tp": "12"})
        w.writerow({"run": "b", "psnr": str(float("inf")), "ssim": str(float("nan")), "tp": "0"})
    loaded = load_runs_csv(csv_path)
    assert loaded[0]["psnr"] == 36.21 and isinstance(loaded[0]["psnr"], float)
    assert loaded[0]["run"] == "a"  # non-numeric field stays a string
    assert loaded[1]["psnr"] == float("inf")
    assert loaded[1]["ssim"] != loaded[1]["ssim"]  # nan != nan

    print("metrics.py self-check OK")
