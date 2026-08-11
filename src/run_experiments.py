"""Experiment runner: produces output/runs.csv, the source of every number in the paper.

Reads the 32-image corpus from samples/manifest.csv (never by globbing a directory --
see samples/fetch_corpus.py). Runs three grid blocks:

    main:      32 images x 4 tamper classes x 3 ratios x 2 variants, block=8, key 0  (768 rows)
    null:      32 images x 2 variants x 5 keys, NO tamper applied,   block=8         (320 rows)
    ablation:  8 USC-SIPI x 4 classes x 3 ratios, variant A, block=4, key 0           (96 rows)

CORRECTNESS REQUIREMENTS (each closes a way to fabricate a result -- commented again at
the call sites below):
  1. recover_image() is ALWAYS called with the mask detect_image PREDICTED, never
     tamper.py's ground-truth mask. Ground truth is used only for scoring.
  2. Both a marked (unrecoverable blocks flattened black -- our real output) and
     unmarked (unrecoverable left as received -- the AuSR1/AuSR3/Wu-2025-comparable
     figure) whole-image PSNR/SSIM are recorded.
  3. Localization is scored against BOTH det.raw_mask and det.block_mask (refinement
     can cost recall on scattered tampers, so reporting only the flattering mask would
     misrepresent the scheme).
  4/5. Recovery quality is always scored against `wm` (the watermarked image, the true
     pre-tamper reference), never the pre-watermark original. Imperceptibility (wm_psnr/
     wm_ssim) is the only place the pre-watermark original is used, and that happens
     inside embed_image(), not here.

KEY EFFICIENCY DECISION: embed_image() depends only on (image, key, variant, block), not
on tamper class or ratio, so it is cached in-memory (never persisted -- determinism makes
it trivially regenerable) keyed by (image_name, variant, block, key_id). This drops the
main grid from 768 embeds to 64, and the null grid's key-0 cells reuse main's cache too.

NULL CONDITION, framed honestly: per-block false-accept probability is 2**-32. No
feasible number of trials could observe that by chance, so the 5 keys are NOT a
statistical test of the crypto -- they are an implementation-robustness check. A
content-dependent-but-key-independent bug (a payload-layout off-by-one, a serialization
edge case triggered by one image's statistics) reproduces across keys; a genuine
cryptographic false accept would not. If any null-condition false positive is ever
observed, that is a defect to investigate, not a "rare event" to shrug off.
"""

import argparse
import csv
import datetime
import hashlib
import time
from pathlib import Path

import numpy as np

from detect import detect_image, expand_mask
from embed import embed_image, load_image, save_image
from metrics import (aggregate_by, confusion_counts, image_metrics, load_runs_csv,
                     loc_scores, msb_preserved_miss_blocks, recovery_metrics)
from payload import default_image_id, msb, to_blocks
from recover import recover_image
from tamper import TAMPER_FNS, apply_tamper, block_mask_from_pixel_mask

ROOT = Path(__file__).resolve().parent.parent
SAMPLES_DIR = ROOT / "samples"
MANIFEST_PATH = SAMPLES_DIR / "manifest.csv"
OUTPUT_DIR = ROOT / "output"

RATIOS = (0.10, 0.25, 0.50)
VARIANTS = ("A", "B")
MAIN_BLOCK = 8
ABLATION_BLOCK = 4
N_KEYS = 5
MAIN_KEY_ID = 0          # key 0 is the one used by the main grid and the ablation
SEED_BASE_DEFAULT = 20260811   # arbitrary but committed -- must never silently change
QUALITATIVE_RATIO = 0.25
QUALITATIVE_VARIANT = "A"

CSV_FIELDS = [
    "run_id", "condition", "dataset", "image_name", "image_id", "width", "height", "channels",
    "tamper_class", "tamper_ratio_nominal", "tamper_ratio_achieved",
    "recovery_variant", "block_size", "key_id", "seed",
    "wm_psnr", "wm_ssim",
    "raw_block_precision", "raw_block_recall", "raw_block_f1", "raw_block_iou", "raw_block_fpr",
    "block_precision", "block_recall", "block_f1", "block_iou", "block_fpr",
    "px_precision", "px_recall", "px_f1", "px_iou", "px_fpr",
    "recoverability_rate", "psnr_in_region", "ssim_in_region",
    "psnr_pessimistic", "ssim_pessimistic",
    "psnr_whole_marked", "psnr_whole_unmarked", "ssim_whole_marked",
    "n_tampered_blocks", "n_unrecoverable_blocks", "n_tampered_px", "n_unrecoverable_px",
    "n_coincidental_unchanged_px", "n_msb_preserved_miss_blocks",
    "n_false_positive_blocks", "n_blocks_total",
    "elapsed_ms", "timestamp_utc",
]


# --------------------------------------------------------------------------
# Corpus / keys / caches
# --------------------------------------------------------------------------

def load_manifest() -> list[dict]:
    """Read the 32-image corpus from samples/manifest.csv -- never glob the directory."""
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["dataset"] in ("usc_sipi", "kodak")]
    samples = []
    for idx, r in enumerate(rows):
        h, w = int(r["height"]), int(r["width"])
        samples.append({
            "idx": idx, "dataset": r["dataset"], "filename": r["filename"],
            "name": Path(r["filename"]).stem, "path": SAMPLES_DIR / r["relpath"],
            "width": w, "height": h, "channels": int(r["channels"]), "shape": (h, w),
        })
    assert len(samples) == 32, f"expected 32 corpus images (8 USC-SIPI + 24 Kodak), found {len(samples)}"
    return samples


def make_key(key_id: int) -> bytes:
    """Deterministic per-key-id master key; key 0 is the main-grid/ablation key."""
    return b"wgtlr-research-key-%02d" % key_id


def _splice_source_index(samples: list[dict], i: int) -> int:
    """Cyclic-next image (starting at i+1) whose (H, W) shape matches image i's.

    tamper_copy_paste's clamp only SHIFTS where the source patch is read from -- it never
    resizes it -- so a source smaller than the destination's randomly-sized region in
    either axis produces an undersized patch and the later `out[y0:y1, x0:x1] = patch`
    assignment raises ValueError. Verified empirically on this exact corpus: same-shape
    pairs never crash at any ratio (50/50 seeds x 3 ratios), but cross-orientation Kodak
    pairs (512x768 dest, 768x512 src or vice versa) crash on ~6% of seeds at ratio=0.50
    (never at 0.10/0.25 -- only large ratios draw a rectangle wide/tall enough to exceed
    the smaller source dimension). Matching shapes exactly removes the failure mode
    instead of retrying seeds. The corpus has >=6 same-shape images in every shape class
    (8 USC-SIPI 512x512, 18 Kodak 512x768, 6 Kodak 768x512), so a match always exists.
    """
    n = len(samples)
    target = samples[i]["shape"]
    for step in range(1, n):
        j = (i + step) % n
        if samples[j]["shape"] == target:
            return j
    return (i + 1) % n  # unreachable for this corpus -- kept as a defensive fallback


def precompute_splice_sources(samples: list[dict]) -> dict[int, int]:
    return {i: _splice_source_index(samples, i) for i in range(len(samples))}


def _qualitative_image_name(samples: list[dict]) -> str:
    """Prefer 'lena'; fall back to the first USC-SIPI image if the manifest ever changes."""
    names = {s["name"] for s in samples}
    if "lena" in names:
        return "lena"
    usc = [s for s in samples if s["dataset"] == "usc_sipi"]
    return (usc[0] if usc else samples[0])["name"]


def get_raw_image(sample: dict, raw_cache: dict) -> np.ndarray:
    idx = sample["idx"]
    if idx not in raw_cache:
        raw_cache[idx] = load_image(sample["path"])
    return raw_cache[idx]


def get_watermarked(sample: dict, variant: str, block: int, key_id: int, keys: list[bytes],
                    raw_cache: dict, embed_cache: dict) -> tuple[np.ndarray, dict]:
    """Cached embed: depends only on (image, key, variant, block), never tamper class/ratio
    -- see module docstring's KEY EFFICIENCY DECISION. In-memory only, never persisted.
    """
    ck = (sample["name"], variant, block, key_id)
    if ck not in embed_cache:
        raw = get_raw_image(sample, raw_cache)
        iid = default_image_id(sample["name"], sample["shape"], block)
        embed_cache[ck] = embed_image(raw, keys[key_id], iid, block=block, variant=variant)
    return embed_cache[ck]


def _blocks_msb_allch(img: np.ndarray, block: int) -> np.ndarray:
    """(K, B, B) greyscale or (K, C, B, B) colour, MSB-projected -- for
    msb_preserved_miss_blocks, which only needs axis 0 to have length K."""
    if img.ndim == 2:
        return msb(to_blocks(img, block))
    return np.stack([msb(to_blocks(img[:, :, c], block)) for c in range(img.shape[2])], axis=1)


# --------------------------------------------------------------------------
# Grid definitions
# --------------------------------------------------------------------------

def iter_main_cells(samples: list[dict]):
    for s in samples:
        for tamper_class in TAMPER_FNS:
            for ratio in RATIOS:
                for variant in VARIANTS:
                    yield {"condition": "tamper", "block_group": "main", "sample": s,
                           "tamper_class": tamper_class, "ratio": ratio, "variant": variant,
                           "block": MAIN_BLOCK, "key_id": MAIN_KEY_ID}


def iter_null_cells(samples: list[dict]):
    for s in samples:
        for variant in VARIANTS:
            for key_id in range(N_KEYS):
                yield {"condition": "null", "block_group": "null", "sample": s,
                       "variant": variant, "block": MAIN_BLOCK, "key_id": key_id}


def iter_ablation_cells(samples: list[dict]):
    usc = [s for s in samples if s["dataset"] == "usc_sipi"]
    for s in usc:
        for tamper_class in TAMPER_FNS:
            for ratio in RATIOS:
                yield {"condition": "tamper", "block_group": "ablation", "sample": s,
                       "tamper_class": tamper_class, "ratio": ratio, "variant": "A",
                       "block": ABLATION_BLOCK, "key_id": MAIN_KEY_ID}


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def _score_and_recover(wm: np.ndarray, received: np.ndarray, det, rec,
                       gt_block: np.ndarray, gt_px: np.ndarray, block: int) -> dict:
    """Shared localization + recovery scoring for both tamper and null cells.

    `rec` must already be recover_image(received, det, ...) -- called by the caller with
    the mask det PREDICTED (see REQUIREMENT 1 at that call site in compute_row). Ground
    truth (`gt_block`/`gt_px`) is used ONLY here, for scoring.
    """
    # REQUIREMENT 3: score against BOTH raw_mask (pre-refine) and block_mask (post-refine,
    # "THE mask" per detect.py) -- refine_mask's isolated-positive rule clears single-block
    # tampers, so refinement can cost recall on scattered tampers, and reporting only the
    # flattering (post-refine) column would misrepresent that tradeoff.
    tp_r, fp_r, fn_r, tn_r = confusion_counts(det.raw_mask, gt_block)
    tp_b, fp_b, fn_b, tn_b = confusion_counts(det.block_mask, gt_block)
    tp_p, fp_p, fn_p, tn_p = confusion_counts(det.pixel_mask, gt_px)
    raw_loc = loc_scores(tp_r, fp_r, fn_r, tn_r)
    block_loc = loc_scores(tp_b, fp_b, fn_b, tn_b)
    px_loc = loc_scores(tp_p, fp_p, fn_p, tn_p)

    # REQUIREMENT 2: recover_image() marks unrecoverable blocks flat black by default,
    # which costs 10-15 dB of whole-image PSNR. That "marked" figure is our real output,
    # but is NOT comparable to AuSR1/AuSR3/Wu-2025, which report whole-image recovered
    # PSNR with unrecoverable regions left as received rather than blacked out. `alt`
    # reproduces that literature convention so both numbers go in the CSV.
    un_px = expand_mask(rec.unrecoverable_mask, block).astype(bool)
    alt = rec.image.copy()
    alt[un_px] = received[un_px]
    psnr_whole_marked, ssim_whole_marked = image_metrics(wm, rec.image)
    psnr_whole_unmarked, _ = image_metrics(wm, alt)

    # REQUIREMENT 4/5: recovery quality is scored against `wm` -- the state that existed
    # immediately before tampering, and what recovery is actually trying to restore --
    # never against the pre-watermark original.
    rm = recovery_metrics(wm, rec.image, gt_px, un_px)

    return {
        "raw_block_precision": raw_loc["precision"], "raw_block_recall": raw_loc["recall"],
        "raw_block_f1": raw_loc["f1"], "raw_block_iou": raw_loc["iou"], "raw_block_fpr": raw_loc["fpr"],
        "block_precision": block_loc["precision"], "block_recall": block_loc["recall"],
        "block_f1": block_loc["f1"], "block_iou": block_loc["iou"], "block_fpr": block_loc["fpr"],
        "px_precision": px_loc["precision"], "px_recall": px_loc["recall"],
        "px_f1": px_loc["f1"], "px_iou": px_loc["iou"], "px_fpr": px_loc["fpr"],
        "recoverability_rate": rec.rho,
        "psnr_in_region": rm["psnr_in_region"], "ssim_in_region": rm["ssim_in_region"],
        "psnr_pessimistic": rm["psnr_pessimistic"], "ssim_pessimistic": rm["ssim_pessimistic"],
        "psnr_whole_marked": psnr_whole_marked, "ssim_whole_marked": ssim_whole_marked,
        "psnr_whole_unmarked": psnr_whole_unmarked,
        "n_tampered_blocks": rec.counts["tampered"], "n_unrecoverable_blocks": rec.counts["unrecoverable"],
        "n_tampered_px": rm["n_tampered_px"], "n_unrecoverable_px": rm["n_unrecoverable_px"],
        # Extra columns the null condition needs for its rule-of-three bound; populated
        # for every row (not just null) since both are well-defined either way.
        "n_false_positive_blocks": fp_b, "n_blocks_total": int(det.block_mask.size),
    }


# --------------------------------------------------------------------------
# Qualitative image retention (ARTIFACT RETENTION -- one image, all 4 classes, 0.25, A)
# --------------------------------------------------------------------------

def _is_qualitative_cell(cell: dict, qual_name: str) -> bool:
    return (cell["condition"] == "tamper" and cell.get("block_group") == "main"
            and cell["sample"]["name"] == qual_name
            and cell["ratio"] == QUALITATIVE_RATIO and cell["variant"] == QUALITATIVE_VARIANT)


def _mask_overlay(base: np.ndarray, pred_px: np.ndarray, unrecoverable_px: np.ndarray) -> np.ndarray:
    """Predicted-tamper mask in red @ 50% alpha; unrecoverable blocks in cyan (distinct colour)."""
    out = base.astype(np.float64)
    red, cyan, alpha = np.array([255.0, 0.0, 0.0]), np.array([0.0, 255.0, 255.0]), 0.5
    pred_only = pred_px & ~unrecoverable_px
    out[pred_only] = out[pred_only] * (1 - alpha) + red * alpha
    out[unrecoverable_px] = out[unrecoverable_px] * (1 - alpha) + cyan * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def _save_qualitative(sample: dict, wm: np.ndarray, received: np.ndarray, det, rec,
                      block: int, tamper_class: str, raw_cache: dict) -> None:
    img_dir = OUTPUT_DIR / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    name = sample["name"]
    save_image(img_dir / f"{name}_original.png", get_raw_image(sample, raw_cache))
    save_image(img_dir / f"{name}_watermarked.png", wm)
    save_image(img_dir / f"{name}_tampered_{tamper_class}.png", received)
    unrec_px = expand_mask(rec.unrecoverable_mask, block).astype(bool)
    overlay = _mask_overlay(received, det.pixel_mask.astype(bool), unrec_px)
    save_image(img_dir / f"{name}_mask_overlay_{tamper_class}.png", overlay)
    save_image(img_dir / f"{name}_recovered_{tamper_class}.png", rec.image)


# --------------------------------------------------------------------------
# Per-cell computation
# --------------------------------------------------------------------------

def compute_run_id(cell: dict) -> str:
    """Deterministic resumability key: (image_name, condition, tamper_class, ratio,
    recovery_variant, block_size, key_id)."""
    s = cell["sample"]
    ratio_s = f"{cell['ratio']:.2f}" if cell.get("ratio") is not None else ""
    parts = "|".join(str(x) for x in (
        s["name"], cell["condition"], cell.get("tamper_class", ""), ratio_s,
        cell["variant"], cell["block"], cell["key_id"]))
    return hashlib.sha256(parts.encode("utf-8")).hexdigest()[:16]


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def compute_row(cell: dict, run_id: str, keys: list[bytes], samples: list[dict],
                splice_src: dict[int, int], raw_cache: dict, embed_cache: dict,
                seed_base: int, qual_name: str) -> dict:
    """Embed (cached) -> [tamper] -> detect -> recover -> score -> one CSV row."""
    t0 = time.perf_counter()
    s = cell["sample"]
    variant, block, key_id = cell["variant"], cell["block"], cell["key_id"]
    key = keys[key_id]
    wm, embed_info = get_watermarked(s, variant, block, key_id, keys, raw_cache, embed_cache)
    h, w = s["shape"]
    iid_str = f"{s['name']}|{h}x{w}|{block}"
    iid = iid_str.encode("utf-8")

    condition = cell["condition"]
    if condition == "tamper":
        tamper_class, ratio = cell["tamper_class"], cell["ratio"]
        other_image = None
        if tamper_class == "splice":
            # Splice source: next image in the manifest, cyclically, but shape-matched to
            # this image's (H, W) -- see precompute_splice_sources for why a blind i+1
            # crashes on ~6% of cross-orientation Kodak pairs at ratio=0.50. Always the
            # WATERMARKED version of the source (same variant/block/key), so the collage
            # exercises the HMAC's image-ID binding across a real splice.
            src_sample = samples[splice_src[s["idx"]]]
            other_image, _ = get_watermarked(src_sample, variant, block, key_id, keys,
                                              raw_cache, embed_cache)
        tres = apply_tamper(wm, tamper_class, ratio, s["name"], seed_base, other_image=other_image)
        received = tres["tampered_image"]
        gt_px = tres["gt_mask_px"]
        gt_block = block_mask_from_pixel_mask(gt_px, block)
        tamper_ratio_achieved = tres["achieved_ratio"]
        n_coincidental = tres["n_coincidental_unchanged_px"]
    else:
        tamper_class, ratio, tamper_ratio_achieved = "", None, None
        received = wm
        Rg, Cg = h // block, w // block
        gt_block = np.zeros((Rg, Cg), dtype=bool)   # null condition: nothing was tampered
        gt_px = np.zeros((h, w), dtype=bool)
        n_coincidental = 0

    det = detect_image(received, key, iid, block=block, variant=variant)

    # REQUIREMENT 1 -- THE central correctness gate: recover_image() receives the mask
    # detect_image PREDICTED, NEVER tamper.py's ground-truth mask (gt_block/gt_px exist
    # only for scoring, below, and are never passed to recover_image). Feeding ground
    # truth into recovery would silently convert this whole experiment into an oracle-
    # localization measurement and invalidate every recovery number.
    rec = recover_image(received, det, block=block, variant=variant)

    score = _score_and_recover(wm, received, det, rec, gt_block, gt_px, block)

    if condition == "tamper":
        orig_blocks = _blocks_msb_allch(wm, block)
        tamp_blocks = _blocks_msb_allch(received, block)
        n_msb_preserved = msb_preserved_miss_blocks(orig_blocks, tamp_blocks, gt_block, det.block_mask)
    else:
        # gt_block is all-False for null -> the function's "miss" set (gt & ~pred) is
        # empty regardless of pred, so the count is always 0 -- skip computing it.
        n_msb_preserved = 0

    if _is_qualitative_cell(cell, qual_name):
        _save_qualitative(s, wm, received, det, rec, block, tamper_class, raw_cache)

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    row = {
        "run_id": run_id, "condition": condition, "dataset": s["dataset"],
        "image_name": s["name"], "image_id": iid_str,
        "width": s["width"], "height": s["height"], "channels": s["channels"],
        "tamper_class": tamper_class,
        "tamper_ratio_nominal": f"{ratio:.2f}" if ratio is not None else "",
        "tamper_ratio_achieved": f"{tamper_ratio_achieved:.6f}" if tamper_ratio_achieved is not None else "",
        "recovery_variant": variant, "block_size": block, "key_id": key_id, "seed": seed_base,
        "wm_psnr": embed_info["psnr"], "wm_ssim": embed_info["ssim"],
        **score,
        "n_coincidental_unchanged_px": n_coincidental,
        "n_msb_preserved_miss_blocks": n_msb_preserved,
        "elapsed_ms": elapsed_ms,
        "timestamp_utc": _now_iso(),
    }

    # Structural guarantee for the self-check gate (see spec item 2): these five columns
    # must never be NaN. `v == v` is False only for NaN (same idiom metrics.aggregate_by
    # uses) -- inf is fine (e.g. a perfectly-recovered null row), NaN is not.
    for k in ("wm_psnr", "wm_ssim", "recoverability_rate", "psnr_whole_marked", "psnr_whole_unmarked"):
        v = row[k]
        assert v == v, f"{k} is NaN for run_id={run_id} ({s['name']}, {condition}) -- must never happen"

    return row


# --------------------------------------------------------------------------
# Resumability / CSV
# --------------------------------------------------------------------------

def load_completed_run_ids(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        return {row["run_id"] for row in csv.DictReader(f)}


def run_grid(cells: list[dict], csv_path: Path, keys: list[bytes], samples: list[dict],
            splice_src: dict[int, int], raw_cache: dict, embed_cache: dict,
            seed_base: int, qual_name: str, resume: bool = True, log_every: int = 25,
            ) -> tuple[int, int, int]:
    """Compute every cell, skipping ones already in csv_path when resume=True.

    Header written only if csv_path did not already exist; every row is flushed to disk
    immediately after being written, so a crash mid-grid loses at most the in-flight row.
    """
    completed = load_completed_run_ids(csv_path) if resume else set()
    write_header = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    n_done = n_skipped = 0
    total = len(cells)
    t_start = time.perf_counter()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()
        for i, cell in enumerate(cells):
            run_id = compute_run_id(cell)
            if resume and run_id in completed:
                n_skipped += 1
                continue
            row = compute_row(cell, run_id, keys, samples, splice_src, raw_cache,
                              embed_cache, seed_base, qual_name)
            writer.writerow(row)
            f.flush()
            n_done += 1
            if (i + 1) % log_every == 0 or i == total - 1:
                elapsed = time.perf_counter() - t_start
                rate = n_done / elapsed if elapsed > 0 else 0.0
                eta = (total - i - 1) / rate if rate > 0 else float("nan")
                print(f"  [{i + 1}/{total}] done={n_done} skipped={n_skipped} "
                      f"elapsed={elapsed:.1f}s eta={eta:.1f}s")
    return n_done, n_skipped, total


# --------------------------------------------------------------------------
# Summary
# --------------------------------------------------------------------------

def _print_final_summary(csv_path: Path) -> None:
    if not csv_path.exists():
        print("\nNo runs.csv to summarize.")
        return
    rows = load_runs_csv(csv_path)
    tamper_rows = [r for r in rows if r["condition"] == "tamper"]
    null_rows = [r for r in rows if r["condition"] == "null"]

    print("\n=== SUMMARY ===")

    print("\nwm_psnr / wm_ssim by variant (all rows):")
    psnr_v = aggregate_by(rows, ("recovery_variant",), "wm_psnr")
    ssim_v = aggregate_by(rows, ("recovery_variant",), "wm_ssim")
    for variant in VARIANTS:
        k = (variant,)
        if k in psnr_v:
            print(f"  {variant}: psnr mean={psnr_v[k]['mean']:.2f} dB (n={psnr_v[k]['n']})  "
                  f"ssim mean={ssim_v[k]['mean']:.4f} (n={ssim_v[k]['n']})")

    if tamper_rows:
        print("\nblock_precision / block_recall by tamper_class (tamper rows only):")
        p_c = aggregate_by(tamper_rows, ("tamper_class",), "block_precision")
        r_c = aggregate_by(tamper_rows, ("tamper_class",), "block_recall")
        for tc in TAMPER_FNS:
            k = (tc,)
            if k in p_c:
                print(f"  {tc:<16} precision mean={p_c[k]['mean']:.4f} (n={p_c[k]['n']})  "
                      f"recall mean={r_c[k]['mean']:.4f} (n={r_c[k]['n']})")

        print("\nrecoverability_rate / psnr_whole_unmarked by tamper_ratio_nominal (tamper rows only):")
        rho_r = aggregate_by(tamper_rows, ("tamper_ratio_nominal",), "recoverability_rate")
        psnr_r = aggregate_by(tamper_rows, ("tamper_ratio_nominal",), "psnr_whole_unmarked")
        for ratio_s in sorted({r["tamper_ratio_nominal"] for r in tamper_rows}):
            k = (ratio_s,)
            print(f"  ratio={ratio_s}: rho mean={rho_r[k]['mean']:.4f} (n={rho_r[k]['n']})  "
                  f"psnr_whole_unmarked mean={psnr_r[k]['mean']:.2f} dB (n={psnr_r[k]['n']})")

    n_fp = sum(int(r["n_false_positive_blocks"]) for r in null_rows)
    n_blk = sum(int(r["n_blocks_total"]) for r in null_rows)
    print(f"\nNull condition: {len(null_rows)} rows, false-positive blocks = {n_fp} / {n_blk} block checks")
    if null_rows and n_fp != 0:
        print("  *** WARNING: null-condition false positives != 0 -- STOP, this is a "
              "defect to investigate, not natural variance. Nothing downstream is "
              "trustworthy until it is understood. ***")


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the watermark-recovery experiment grid.")
    p.add_argument("--quick", action="store_true",
                   help="2 images, all 4 tamper classes, ratio=0.25, variant A, key 0, no ablation")
    p.add_argument("--restart", action="store_true", help="clear output/runs.csv and start clean")
    p.add_argument("--seed-base", type=int, default=SEED_BASE_DEFAULT)
    p.add_argument("--only", choices=("main", "null", "ablation"), default=None,
                   help="re-run just one grid block (combine with --restart to also wipe the CSV)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    t_start = time.perf_counter()
    csv_path = OUTPUT_DIR / "runs.csv"
    if args.restart and csv_path.exists():
        csv_path.unlink()

    samples = load_manifest()
    keys = [make_key(i) for i in range(N_KEYS)]
    splice_src = precompute_splice_sources(samples)
    qual_name = _qualitative_image_name(samples)
    raw_cache: dict = {}
    embed_cache: dict = {}

    if args.quick:
        quick = ([s for s in samples if s["dataset"] == "usc_sipi"][:1]
                 + [s for s in samples if s["dataset"] == "kodak"][:1])
        cells = [
            {"condition": "tamper", "block_group": "main", "sample": s, "tamper_class": tc,
             "ratio": 0.25, "variant": "A", "block": MAIN_BLOCK, "key_id": MAIN_KEY_ID}
            for s in quick for tc in TAMPER_FNS
        ]
        done, skipped, total = run_grid(cells, csv_path, keys, samples, splice_src,
                                          raw_cache, embed_cache, args.seed_base, qual_name,
                                          resume=not args.restart)
        print(f"\n--quick: {done} computed, {skipped} skipped, {total} cells, "
              f"{time.perf_counter() - t_start:.1f}s wall-clock")
        _print_final_summary(csv_path)
        return

    groups = [args.only] if args.only else ["main", "null", "ablation"]
    generators = {"main": iter_main_cells, "null": iter_null_cells, "ablation": iter_ablation_cells}
    grand_done = grand_skipped = grand_total = 0
    for g in groups:
        cells = list(generators[g](samples))
        print(f"\n=== {g}: {len(cells)} cells ===")
        done, skipped, total = run_grid(cells, csv_path, keys, samples, splice_src,
                                          raw_cache, embed_cache, args.seed_base, qual_name,
                                          resume=not args.restart)
        grand_done += done; grand_skipped += skipped; grand_total += total

    elapsed = time.perf_counter() - t_start
    print(f"\nTotal: {grand_done} computed, {grand_skipped} skipped (resumed), "
          f"{grand_total} cells across {groups}. Wall-clock: {elapsed:.1f}s")
    _print_final_summary(csv_path)


if __name__ == "__main__":
    main()
