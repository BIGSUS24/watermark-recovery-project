"""Experiment runner: produces output/runs.csv, the source of every number in the paper.

Reads the 32-image corpus from samples/manifest.csv (never by globbing a directory --
see samples/fetch_corpus.py). Runs three grid blocks:

    main:      32 images x 4 tamper classes x 7 ratios x 2 variants (A, C), block=8,
               key 0                                                              (1792 rows)
    null:      32 images x 2 variants (A, C) x 5 keys, NO tamper applied, block=8   (320 rows)
    ablation:  8 USC-SIPI x 4 classes x 7 ratios, variant A, block=4, key 0          (224 rows)
             + 32 images x 4 classes x 7 ratios, variant B, block=8, key 0          (896 rows)
               -- #38: B (2x2 block-mean descriptor) is measurably inferior to A/C and no
               longer occupies a main-grid slot, but its numbers must not simply vanish, so
               it runs here on the exact main-grid geometry instead.        (1120 rows total)

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

PARALLELISM (#34): each cell is a pure function of (image, key, variant, block, tamper
class, ratio) -- nothing about one cell depends on another -- so --jobs N runs the grid
across a ProcessPoolExecutor. The embed cache above is computed ONCE in the parent process
before any worker is spawned (see _precompute_embed_cache) and shipped to every worker via
the pool initializer, so parallel execution still embeds each (image, variant, block, key)
exactly once, not once per worker. Cells complete out of order, but results are buffered
and written to output/runs.csv strictly in the same order --jobs 1 would have produced
(see _drain_ready) -- --jobs must never change row order or row content, only wall time.

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
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from detect import detect_image, expand_mask, refinement_flagged_count
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

RATIOS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)  # #40: 3 coarse points hid the
# collapse cliff between 25% and 50% -- seven points map it.
VARIANTS = ("A", "C")  # #38: C is what the app actually ships as its default; B is
# measurably inferior and demoted to an ablation-only block (see iter_ablation_cells).
MAIN_BLOCK = 8
ABLATION_BLOCK = 4
N_KEYS = 5
MAIN_KEY_ID = 0          # key 0 is the one used by the main grid and the ablation
SEED_BASE_DEFAULT = 20260811   # arbitrary but committed -- must never silently change
QUALITATIVE_RATIO = 0.25
QUALITATIVE_VARIANT = "A"
# #36: was hardcoded to "lena" -- Lena's redistribution status is contested, and USC-SIPI
# has already withdrawn it (and tiffany) from its own archive (see fetch_corpus.py's module
# docstring). kodim04 is the Kodak corpus's own well-known portrait -- a close face crop
# with a woven-straw hat (high-frequency mesh texture), smooth skin gradients, fine hair
# detail, and a soft fabric backdrop -- so it exercises the same range of texture the
# qualitative figure is meant to show, without leaning on a redistribution-contested image.
QUALITATIVE_IMAGE_DEFAULT = "kodim04"

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
    "n_false_positive_blocks", "n_blocks_total", "n_refinement_flagged",
    "elapsed_ms", "timestamp_utc",
]


# --------------------------------------------------------------------------
# Corpus / keys / caches
# --------------------------------------------------------------------------

def load_manifest() -> list[dict]:
    """Read the 32-image corpus from samples/manifest.csv -- never glob the directory."""
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r["dataset"] in ("usc_sipi", "kodak")]
    # #36 provenance: every corpus row must carry a licence -- UNKNOWN is an acceptable
    # value (an honest "we don't know"), a missing/empty column is not.
    assert all(r.get("licence") for r in rows), (
        "manifest.csv row(s) missing a non-empty 'licence' column -- see #36; "
        "re-run samples/fetch_corpus.py to regenerate the manifest with provenance")
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


def _qualitative_image_name(samples: list[dict], requested: str | None = None) -> str:
    """Resolve the qualitative-figure image: `requested` (--qualitative-image) if given,
    else QUALITATIVE_IMAGE_DEFAULT. Falls back to the first USC-SIPI image only if that
    name isn't actually in the corpus, and says so LOUDLY (stderr) -- a silent substitution
    here means the qualitative figure the paper's caption describes quietly stops being the
    one this run actually produced, which is worse than just crashing.
    """
    names = {s["name"] for s in samples}
    want = requested or QUALITATIVE_IMAGE_DEFAULT
    if want in names:
        return want
    usc = [s for s in samples if s["dataset"] == "usc_sipi"]
    fallback = (usc[0] if usc else samples[0])["name"]
    print(f"WARNING: qualitative image {want!r} not found in corpus "
          f"(manifest has {sorted(names)}) -- falling back to {fallback!r}. The qualitative "
          f"figure/paper caption will disagree until manifest.csv or --qualitative-image "
          f"is fixed.", file=sys.stderr)
    return fallback


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
# Parallel execution (#34)
# --------------------------------------------------------------------------
# Windows defaults multiprocessing to "spawn": each worker re-imports this module fresh (the
# module's top-level code runs again, but the `if __name__ == "__main__":` guard at the
# bottom does not), so a worker cannot inherit state via closures or globals set after
# import time in the parent -- it only gets what ProcessPoolExecutor's initializer/initargs
# hands it. Hence the module-level globals and the top-level (picklable) _worker_init /
# _worker_compute functions below, instead of a closure or bound method.

_W_KEYS = _W_SAMPLES = _W_SPLICE_SRC = _W_RAW_CACHE = _W_EMBED_CACHE = None
_W_SEED_BASE = _W_QUAL_NAME = None
_W_SKIP_REFINEMENT_ONLY = False


def _worker_init(keys, samples, splice_src, raw_cache, embed_cache, seed_base, qual_name,
                 skip_refinement_only=False):
    """Runs once per worker PROCESS at pool startup, not per task -- this is what makes the
    precomputed embed_cache shared instead of re-sent (or re-embedded) per cell."""
    global _W_KEYS, _W_SAMPLES, _W_SPLICE_SRC, _W_RAW_CACHE, _W_EMBED_CACHE
    global _W_SEED_BASE, _W_QUAL_NAME, _W_SKIP_REFINEMENT_ONLY
    _W_KEYS, _W_SAMPLES, _W_SPLICE_SRC = keys, samples, splice_src
    _W_RAW_CACHE, _W_EMBED_CACHE = raw_cache, embed_cache
    _W_SEED_BASE, _W_QUAL_NAME = seed_base, qual_name
    _W_SKIP_REFINEMENT_ONLY = skip_refinement_only


def _worker_compute(index: int, cell: dict, run_id: str) -> tuple[int, dict]:
    """Picklable per-task entry point. `index` is the cell's position in the caller's
    deterministic cell order, carried through purely so results can be sorted back into it."""
    row = compute_row(cell, run_id, _W_KEYS, _W_SAMPLES, _W_SPLICE_SRC, _W_RAW_CACHE,
                      _W_EMBED_CACHE, _W_SEED_BASE, _W_QUAL_NAME, _W_SKIP_REFINEMENT_ONLY)
    return index, row


def _required_embed_cache_keys(cells: list[dict], samples: list[dict],
                               splice_src: dict[int, int]) -> set[tuple[str, str, int, int]]:
    """Every (image_name, variant, block, key_id) get_watermarked() will be asked for while
    computing `cells` -- including a splice cell's SOURCE image, which borrows the same
    (variant, block, key_id) as the cell it splices into (see compute_row)."""
    ks = set()
    for cell in cells:
        s = cell["sample"]
        ks.add((s["name"], cell["variant"], cell["block"], cell["key_id"]))
        if cell.get("tamper_class") == "splice":
            src = samples[splice_src[s["idx"]]]
            ks.add((src["name"], cell["variant"], cell["block"], cell["key_id"]))
    return ks


def _precompute_embed_cache(cells: list[dict], samples: list[dict], splice_src: dict[int, int],
                            keys: list[bytes], raw_cache: dict, embed_cache: dict) -> None:
    """Embed everything `cells` will need, ONCE, here, in the parent process, before any
    worker exists -- see module docstring's KEY EFFICIENCY DECISION / PARALLELISM. Without
    this, --jobs>1 would lazily embed on first use PER WORKER PROCESS (each gets its own
    copy of embed_cache via the pool initializer), multiplying the embed count by --jobs.
    """
    by_name = {s["name"]: s for s in samples}
    for name, variant, block, key_id in sorted(_required_embed_cache_keys(cells, samples, splice_src)):
        get_watermarked(by_name[name], variant, block, key_id, keys, raw_cache, embed_cache)


def _drain_ready(pending_by_idx: dict[int, dict], next_write: int) -> tuple[list[dict], int]:
    """Pop the contiguous run of rows starting at `next_write` out of `pending_by_idx`, in
    index order. This is the entire mechanism the byte-identity gate rests on: cells can
    finish in any order across worker processes, but rows only ever leave this function (and
    reach the CSV) in the same order --jobs 1 would have produced them in.
    """
    ready = []
    while next_write in pending_by_idx:
        ready.append(pending_by_idx.pop(next_write))
        next_write += 1
    return ready, next_write


def _run_parallel(pending: list[tuple[dict, str]], writer, f, keys: list[bytes],
                  samples: list[dict], splice_src: dict[int, int], raw_cache: dict,
                  embed_cache: dict, seed_base: int, qual_name: str, total: int,
                  n_skipped: int, t_start: float, log_every: int, jobs: int,
                  skip_refinement_only: bool = False) -> int:
    """Dispatch `pending` (already resume-filtered, in deterministic cell order) to a process
    pool. embed_cache must already hold everything the cells need (_precompute_embed_cache)
    before this is called. Progress logs on completion order (unavoidable with a pool), but
    every row reaches `writer`/`f` strictly in `pending` order via _drain_ready.
    """
    n = len(pending)
    if n == 0:
        return 0
    pending_by_idx: dict[int, dict] = {}
    next_write = 0
    n_done = 0
    with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init,
                             initargs=(keys, samples, splice_src, raw_cache, embed_cache,
                                       seed_base, qual_name, skip_refinement_only)) as ex:
        futures = [ex.submit(_worker_compute, i, cell, run_id)
                   for i, (cell, run_id) in enumerate(pending)]
        for fut in as_completed(futures):
            i, row = fut.result()
            pending_by_idx[i] = row
            n_done += 1
            ready, next_write = _drain_ready(pending_by_idx, next_write)
            for row_ready in ready:
                writer.writerow(row_ready)
            if ready:
                f.flush()
            if n_done % log_every == 0 or n_done == n:
                elapsed = time.perf_counter() - t_start
                rate = n_done / elapsed if elapsed > 0 else 0.0
                eta = (n - n_done) / rate if rate > 0 else float("nan")
                print(f"  [{n_skipped + n_done}/{total}] done={n_done} skipped={n_skipped} "
                      f"elapsed={elapsed:.1f}s eta={eta:.1f}s (jobs={jobs}, completion order)")
    assert next_write == n and not pending_by_idx, (
        "reorder buffer left rows unflushed after pool exit -- a worker task result is missing")
    return n_done


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
    # #38: variant B no longer has a main-grid slot (see VARIANTS), but its numbers
    # must not simply vanish -- run it on the exact geometry the main grid used to run
    # it at (full corpus, block=8) as an ablation-only block instead.
    for s in samples:
        for tamper_class in TAMPER_FNS:
            for ratio in RATIOS:
                yield {"condition": "tamper", "block_group": "ablation", "sample": s,
                       "tamper_class": tamper_class, "ratio": ratio, "variant": "B",
                       "block": MAIN_BLOCK, "key_id": MAIN_KEY_ID}


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
                seed_base: int, qual_name: str, skip_refinement_only: bool = False) -> dict:
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
    rec = recover_image(received, det, block=block, variant=variant,
                        skip_refinement_only=skip_refinement_only)

    # #32: measured unconditionally regardless of the switch above, so both recovery
    # behaviours can be compared on one grid -- see recover_image's docstring.
    n_refinement_flagged = refinement_flagged_count(det.raw_mask, det.block_mask)

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
        "n_refinement_flagged": n_refinement_flagged,
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
            jobs: int = 1, skip_refinement_only: bool = False) -> tuple[int, int, int]:
    """Compute every cell, skipping ones already in csv_path when resume=True.

    Header written only if csv_path did not already exist; every row reaches disk as soon
    as its turn comes -- immediately, for jobs<=1; as soon as the contiguous prefix is
    ready, for jobs>1 (see _drain_ready) -- so a crash mid-grid loses at most the in-flight
    row(s).

    jobs<=1 runs the original plain sequential loop -- unchanged, and also the byte-identity
    reference that --jobs>1's output is diffed against (see module docstring, PARALLELISM).
    """
    completed = load_completed_run_ids(csv_path) if resume else set()
    write_header = not csv_path.exists()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    n_done = n_skipped = 0
    total = len(cells)
    t_start = time.perf_counter()
    jobs = max(1, jobs)
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
            f.flush()

        if jobs == 1:
            for i, cell in enumerate(cells):
                run_id = compute_run_id(cell)
                if resume and run_id in completed:
                    n_skipped += 1
                    continue
                row = compute_row(cell, run_id, keys, samples, splice_src, raw_cache,
                                  embed_cache, seed_base, qual_name, skip_refinement_only)
                writer.writerow(row)
                f.flush()
                n_done += 1
                if (i + 1) % log_every == 0 or i == total - 1:
                    elapsed = time.perf_counter() - t_start
                    rate = n_done / elapsed if elapsed > 0 else 0.0
                    eta = (total - i - 1) / rate if rate > 0 else float("nan")
                    print(f"  [{i + 1}/{total}] done={n_done} skipped={n_skipped} "
                          f"elapsed={elapsed:.1f}s eta={eta:.1f}s")
        else:
            pending = []
            for cell in cells:
                run_id = compute_run_id(cell)
                if resume and run_id in completed:
                    n_skipped += 1
                    continue
                pending.append((cell, run_id))
            _precompute_embed_cache([c for c, _ in pending], samples, splice_src, keys,
                                    raw_cache, embed_cache)
            n_done = _run_parallel(pending, writer, f, keys, samples, splice_src, raw_cache,
                                   embed_cache, seed_base, qual_name, total, n_skipped,
                                   t_start, log_every, jobs, skip_refinement_only)
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

        # #32: how often the isolated-negative fill invents a flag on a block whose own
        # tag matched -- recover_image overwrites this content by default (see its
        # skip_refinement_only parameter / --skip-refinement-only-recovery).
        n_ref = sum(int(r["n_refinement_flagged"]) for r in tamper_rows)
        n_flagged = sum(int(r["n_tampered_blocks"]) for r in tamper_rows)
        print(f"\nn_refinement_flagged (tamper rows): {n_ref} of {n_flagged} flagged blocks")

    n_fp = sum(int(r["n_false_positive_blocks"]) for r in null_rows)
    n_blk = sum(int(r["n_blocks_total"]) for r in null_rows)
    print(f"\nNull condition: {len(null_rows)} rows, false-positive blocks = {n_fp} / {n_blk} block checks")
    if null_rows and n_fp != 0:
        print("  *** WARNING: null-condition false positives != 0 -- STOP, this is a "
              "defect to investigate, not natural variance. Nothing downstream is "
              "trustworthy until it is understood. ***")


# --------------------------------------------------------------------------
# Phase E (PLAN-FIXES.md): Variant A vs C vs D, focused comparison -- NOT the full grid.
# --------------------------------------------------------------------------
# "Do not run the full grid. Run a focused comparison instead: Variant A, C and D on a
# handful of corpus images across all seven ratios." This is that comparison, invoked
# separately via --phase-e -- it does not touch main/null/ablation or output/runs.csv.

PHASE_E_IMAGES = ("pepper", "baboon", "kodim04")  # 2 USC-SIPI (one smooth-ish, one
# high-frequency texture) + 1 Kodak portrait -- deliberately not the 32-image corpus.
PHASE_E_VARIANTS = ("A", "C", "D")
PHASE_E_TAMPER = "crop_refill"  # one representative localized-wipe class; the ratio grid,
# not the tamper-class grid, is the axis this comparison is actually about.


def _embed_for_phase_e(raw: np.ndarray, key: bytes, iid: bytes, variant: str, block: int
                       ) -> tuple[np.ndarray, dict]:
    """A/C go through the normal embed_image(); D needs fountain.embed() instead -- see
    fountain.py's module docstring for why embed_image() itself cannot take a variant="D"
    call directly (its encode_descriptor call site has no key parameter)."""
    if variant == "D":
        import fountain
        return fountain.embed(raw, key, iid, block)
    return embed_image(raw, key, iid, block=block, variant=variant)


def run_phase_e_comparison(seed_base: int = SEED_BASE_DEFAULT) -> list[dict]:
    """3 images x 3 variants x 7 ratios x 1 tamper class = 63 embed/detect/recover
    cycles (not the main grid's 1792). Real embed -> tamper -> detect -> recover on real
    pixels throughout -- PSNR needs real reconstructed images, not the image-free
    recoverability_rate() shortcut, so there is no faster path worth building here.
    """
    samples_by_name = {s["name"]: s for s in load_manifest()}
    key = make_key(MAIN_KEY_ID)
    rows: list[dict] = []
    for name in PHASE_E_IMAGES:
        s = samples_by_name[name]
        raw = load_image(s["path"])
        iid = default_image_id(name, s["shape"], MAIN_BLOCK)
        for variant in PHASE_E_VARIANTS:
            wm, _ = _embed_for_phase_e(raw, key, iid, variant, MAIN_BLOCK)
            for ratio in RATIOS:
                tres = apply_tamper(wm, PHASE_E_TAMPER, ratio, name, seed_base)
                received = tres["tampered_image"]
                gt_px = tres["gt_mask_px"]
                gt_block = block_mask_from_pixel_mask(gt_px, MAIN_BLOCK)
                det = detect_image(received, key, iid, block=MAIN_BLOCK, variant=variant)
                # REQUIREMENT 1 (same as compute_row): recover_image() gets the mask
                # detect_image PREDICTED, never tamper.py's ground truth.
                rec = recover_image(received, det, block=MAIN_BLOCK, variant=variant,
                                    key=key if variant == "D" else None)
                score = _score_and_recover(wm, received, det, rec, gt_block, gt_px, MAIN_BLOCK)
                row = {
                    "image": name, "variant": variant, "ratio": ratio,
                    "rho": rec.rho,
                    "psnr_in_region": score["psnr_in_region"],
                    "psnr_whole_unmarked": score["psnr_whole_unmarked"],
                    "psnr_whole_marked": score["psnr_whole_marked"],
                }
                rows.append(row)
                print(f"  {name:<10} {variant} ratio={ratio:.2f}  rho={rec.rho:.3f}  "
                      f"psnr_region={score['psnr_in_region']:.2f}  "
                      f"psnr_whole_unmarked={score['psnr_whole_unmarked']:.2f}")
    return rows


def print_phase_e_table(rows: list[dict]) -> None:
    """The deliverable: rho / in-region PSNR / whole-image unmarked PSNR per variant per
    ratio, averaged over PHASE_E_IMAGES -- what decides whether D ships."""
    print(f"\n=== Phase E: A vs C vs D, mean over {len(PHASE_E_IMAGES)} images, "
          f"tamper={PHASE_E_TAMPER} ===")
    print(f"{'ratio':>6} {'var':>4} {'rho':>8} {'psnr_region':>12} {'psnr_whole_unmk':>17}")
    for ratio in RATIOS:
        for variant in PHASE_E_VARIANTS:
            sub = [r for r in rows if r["ratio"] == ratio and r["variant"] == variant]
            if not sub:
                continue
            rho_mean = sum(r["rho"] for r in sub) / len(sub)
            reg_vals = [r["psnr_in_region"] for r in sub if r["psnr_in_region"] == r["psnr_in_region"]]
            reg_mean = sum(reg_vals) / len(reg_vals) if reg_vals else float("nan")
            whole_mean = sum(r["psnr_whole_unmarked"] for r in sub) / len(sub)
            print(f"{ratio:>6.2f} {variant:>4} {rho_mean:>8.3f} {reg_mean:>12.2f} {whole_mean:>17.2f}")


def save_phase_e_csv(rows: list[dict], path: Path) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fields = ["image", "variant", "ratio", "rho", "psnr_in_region",
             "psnr_whole_unmarked", "psnr_whole_marked"]
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


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
    p.add_argument("--jobs", type=int, default=os.cpu_count() or 1,
                   help="parallel worker processes for the grid (default: os.cpu_count()); "
                        "--jobs 1 forces the old sequential path")
    p.add_argument("--qualitative-image", default=None, metavar="NAME",
                   help=f"corpus image (manifest stem) to retain full qualitative artifacts "
                        f"for (default: {QUALITATIVE_IMAGE_DEFAULT!r})")
    p.add_argument("--selfcheck", action="store_true",
                   help="run the internal self-check (no corpus/network needed) and exit")
    p.add_argument("--phase-e", action="store_true",
                   help="PLAN-FIXES.md Phase E: focused Variant A/C/D comparison "
                        "(3 images x 3 variants x 7 ratios x 1 tamper class) instead of "
                        "the full grid; writes output/phase_e_comparison.csv")
    p.add_argument("--skip-refinement-only-recovery", action="store_true",
                   help="#32: do not recover blocks flagged only by refine_mask's "
                        "neighbourhood fill (own tag matched) -- default off, matching "
                        "today's behaviour; n_refinement_flagged in runs.csv is always "
                        "populated regardless of this flag, so both behaviours can be "
                        "compared on one grid")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.selfcheck:
        _selfcheck()
        print("run_experiments.py self-check OK")
        return

    if args.phase_e:
        rows = run_phase_e_comparison(args.seed_base)
        print_phase_e_table(rows)
        out_path = OUTPUT_DIR / "phase_e_comparison.csv"
        save_phase_e_csv(rows, out_path)
        print(f"\nwrote {out_path}")
        return

    t_start = time.perf_counter()
    csv_path = OUTPUT_DIR / "runs.csv"
    if args.restart and csv_path.exists():
        csv_path.unlink()

    samples = load_manifest()
    keys = [make_key(i) for i in range(N_KEYS)]
    splice_src = precompute_splice_sources(samples)
    qual_name = _qualitative_image_name(samples, args.qualitative_image)
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
                                          resume=not args.restart, jobs=args.jobs,
                                          skip_refinement_only=args.skip_refinement_only_recovery)
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
                                          resume=not args.restart, jobs=args.jobs,
                                          skip_refinement_only=args.skip_refinement_only_recovery)
        grand_done += done; grand_skipped += skipped; grand_total += total

    elapsed = time.perf_counter() - t_start
    print(f"\nTotal: {grand_done} computed, {grand_skipped} skipped (resumed), "
          f"{grand_total} cells across {groups}. Wall-clock: {elapsed:.1f}s")
    _print_final_summary(csv_path)


# --------------------------------------------------------------------------
# Self-check -- run manually with `python src/run_experiments.py --selfcheck`.
# --------------------------------------------------------------------------

def _selfcheck() -> None:
    """Pure-logic checks for what #34/#36 added: no corpus, no network, no image pipeline.
    The real end-to-end guarantee (--jobs 1 vs --jobs N byte-identical on output/runs.csv)
    is verified by actually running the grid twice and diffing, per the module docstring --
    that's an integration property, not something a unit-style self-check can fake. What's
    checked here is the machinery that guarantee depends on.
    """
    # _qualitative_image_name: default, explicit override, and the loud fallback path.
    fake_samples = [
        {"name": "kodim04", "dataset": "kodak"},
        {"name": "airplane", "dataset": "usc_sipi"},
        {"name": "baboon", "dataset": "usc_sipi"},
    ]
    assert _qualitative_image_name(fake_samples) == QUALITATIVE_IMAGE_DEFAULT
    assert _qualitative_image_name(fake_samples, "baboon") == "baboon"
    assert _qualitative_image_name(fake_samples, "does_not_exist") == "airplane"  # 1st USC-SIPI
    no_usc = [{"name": "kodim04", "dataset": "kodak"}]
    assert _qualitative_image_name(no_usc, "nope") == "kodim04"  # falls back to samples[0]

    # _required_embed_cache_keys: a splice cell must also pull in its SOURCE image's embed,
    # at the same (variant, block, key_id) as the cell it splices into.
    s0, s1 = {"name": "a", "idx": 0}, {"name": "b", "idx": 1}
    samples2, splice_src = [s0, s1], {0: 1, 1: 0}
    cells = [
        {"sample": s0, "variant": "A", "block": 8, "key_id": 0, "tamper_class": "splice"},
        {"sample": s1, "variant": "A", "block": 8, "key_id": 0, "tamper_class": "copy_move"},
    ]
    ks = _required_embed_cache_keys(cells, samples2, splice_src)
    assert ks == {("a", "A", 8, 0), ("b", "A", 8, 0)}, ks

    # _drain_ready: the entire byte-identity guarantee for --jobs>1 rests on this. Feed it
    # completions arriving out of index order and check rows only ever leave in index order.
    pending_by_idx: dict[int, str] = {}
    next_write, flushed = 0, []
    for i in (2, 0, 3, 1, 4):  # arrival order != index order
        pending_by_idx[i] = f"row{i}"
        ready, next_write = _drain_ready(pending_by_idx, next_write)
        flushed.extend(ready)
    assert flushed == [f"row{i}" for i in range(5)], flushed
    assert next_write == 5 and not pending_by_idx

    print("  qualitative-image resolution (default/override/loud-fallback) -- OK")
    print("  splice-aware required embed cache keys -- OK")
    print("  reorder buffer preserves index order under out-of-order completion -- OK")


if __name__ == "__main__":
    main()
