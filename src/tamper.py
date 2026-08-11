"""Tamper-simulation harness: generates realistic image tampering with EXACT ground-truth masks.

Ground truth is defined by the INTENDED region geometry, decided BEFORE any pixel is written --
never by post-hoc diffing. All four tamper_* functions satisfy this by construction: the mask
returned IS the region argument passed to the write, not a comparison of before/after arrays.
Reason: a tamper can by chance leave some pixels' exact values unchanged (flat sky pasted onto
flat sky, or noise that happens to redraw the same byte). If ground truth were a diff, those
pixels would silently vanish from the ground-truth region. Do not "improve" this into a diff.
"""
import hashlib
from typing import Callable

import cv2
import numpy as np


def derive_seed(base_seed: int, *parts: str | int | float) -> int:
    """Deterministic sub-seed: sha256 of the joined parts, truncated to 63 bits."""
    joined = "|".join([str(base_seed)] + [str(p) for p in parts])
    digest = hashlib.sha256(joined.encode()).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)
    # Feed this to np.random.default_rng(seed). NEVER np.random.seed() -- that mutates
    # process-global state and is unsafe the moment anything else runs out of order.


def _rect_region(h: int, w: int, ratio: float, rng: np.random.Generator
                 ) -> tuple[int, int, int, int]:
    """Random rectangle covering `ratio` of the image; returns (y0, x0, y1, x1)."""
    area = ratio * h * w
    aspect = np.exp(rng.uniform(np.log(0.5), np.log(2.0)))  # width / height, log-uniform
    rh = int(round(np.sqrt(area / aspect)))
    rw = int(round(np.sqrt(area * aspect)))
    # clamp BEFORE picking a position, so an extreme aspect ratio at ratio=0.50 can't
    # demand a placement that doesn't fit in the image at all
    rh = max(1, min(rh, h))
    rw = max(1, min(rw, w))
    y0 = int(rng.integers(0, h - rh + 1))
    x0 = int(rng.integers(0, w - rw + 1))
    return y0, x0, y0 + rh, x0 + rw
    # ponytail: deliberately NOT grid-aligned, so the boundary-quantization penalty the paper
    # discusses actually shows up in the PIXEL-level metrics instead of being hidden by
    # conveniently aligned regions.
    # This comment used to claim non-alignment was what stopped block-level precision being
    # trivially 1.0. That was wrong: under the 'any' block ground-truth rule (see
    # block_mask_from_pixel_mask) block-level precision is 1.0 either way, because every block
    # whose content changed necessarily contains an intended-region pixel. Non-alignment buys
    # honesty at pixel level only -- which is the level worth reporting.


def _blob_mask(h: int, w: int, ratio: float, rng: np.random.Generator,
               max_iter: int = 3) -> np.ndarray:
    """Boolean (h, w) mask: union of 3-6 random circles around a common center."""
    k = int(rng.integers(3, 7))
    cy = rng.uniform(0.25, 0.75) * h
    cx = rng.uniform(0.25, 0.75) * w
    angles = rng.uniform(0, 2 * np.pi, size=k)
    fracs = rng.uniform(0.0, 0.8, size=k)  # each circle's center offset, as a fraction of radius

    def draw(r: float) -> np.ndarray:
        canvas = np.zeros((h, w), dtype=np.uint8)
        r_int = max(1, int(round(r)))
        for i in range(k):
            cyi = int(round(cy + np.sin(angles[i]) * fracs[i] * r))
            cxi = int(round(cx + np.cos(angles[i]) * fracs[i] * r))
            cv2.circle(canvas, (cxi, cyi), r_int, 1, -1)  # cv2 clips off-canvas draws for free
        return canvas.astype(bool)

    target = ratio * h * w
    r = float(np.sqrt(target / (k * np.pi)))  # analytic per-circle radius, ignoring overlap
    mask = draw(r)
    for _ in range(max_iter):  # measure -> rescale -> redraw, capped so borders can't runaway
        achieved = mask.sum() / (h * w)
        r *= 2.0 if achieved <= 1e-9 else np.sqrt(ratio / achieved)
        mask = draw(r)
    return mask  # achieved ratio is whatever this is -- never silently relabelled to `ratio`


def tamper_copy_paste(image: np.ndarray, ratio: float, seed: int,
                      source_image: np.ndarray | None = None
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Paste a same-shaped rectangular region from source_image into a random location of image."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    y0, x0, y1, x1 = _rect_region(h, w, ratio, rng)
    rh, rw = y1 - y0, x1 - x0
    if source_image is None:
        # no source given -> pull from the SAME image, mirrored across the centre: deterministic
        # and structurally distinct from the destination, so src/dst can't degenerate to the same spot
        patch = image[h - y1:h - y0, w - x1:w - x0]
    else:
        # realistic splicing case: same region coordinates, different photo. Clamp defensively
        # in case source_image is a different size than image.
        sh, sw = source_image.shape[:2]
        sy0 = min(y0, max(0, sh - rh))
        sx0 = min(x0, max(0, sw - rw))
        patch = source_image[sy0:sy0 + rh, sx0:sx0 + rw]
    out = image.copy()
    out[y0:y1, x0:x1] = patch
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return out, mask


def tamper_inpaint_removal(image: np.ndarray, ratio: float, seed: int,
                           method: str = "telea") -> tuple[np.ndarray, np.ndarray]:
    """Diffusion-inpaint a blob region -- a constant/mean fill would be trivially detectable and
    unrealistic, so it is deliberately NOT used. cv2.inpaint is a real diffusion algorithm, which
    is why this class is EXPECTED to show the lowest recall of the four: a smooth fill over
    already-flat content can numerically reproduce the original MSB planes near the hole
    boundary. That is an expected miss, not a bug.
    """
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    mask = _blob_mask(h, w, ratio, rng)
    flags = cv2.INPAINT_TELEA if method == "telea" else cv2.INPAINT_NS
    mask_u8 = mask.astype(np.uint8) * 255
    if image.ndim == 2:
        try:
            filled = cv2.inpaint(image, mask_u8, inpaintRadius=3, flags=flags)
        except cv2.error:
            # this opencv build rejected a plain 2-D array -- add an explicit channel dim
            filled = cv2.inpaint(image[:, :, None], mask_u8, inpaintRadius=3, flags=flags)[:, :, 0]
    else:
        filled = cv2.inpaint(image, mask_u8, inpaintRadius=3, flags=flags)
    out = image.copy()
    out[mask] = filled[mask]  # index-assign only within the region -> exact outside by construction
    return out, mask


def tamper_crop_refill(image: np.ndarray, ratio: float, seed: int
                       ) -> tuple[np.ndarray, np.ndarray]:
    """Replace a rectangular region with a SYNTHETIC patch -- zero real captured content, which
    is the one property distinguishing crop-refill from copy-paste.
    """
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    y0, x0, y1, x1 = _rect_region(h, w, ratio, rng)
    rh, rw = y1 - y0, x1 - x0
    color = image.ndim == 3
    n_ch = image.shape[2] if color else None

    # low-res noise, upsampled + blurred, so the patch has plausible texture, not pixel grain
    low_h, low_w = max(4, rh // 8), max(4, rw // 8)
    low_shape = (low_h, low_w, n_ch) if color else (low_h, low_w)
    low = rng.normal(128.0, 40.0, size=low_shape).astype(np.float32)
    patch = cv2.resize(low, (rw, rh), interpolation=cv2.INTER_CUBIC)
    ksize = max(3, (min(rh, rw) // 10) | 1)  # odd kernel size
    patch = cv2.GaussianBlur(patch, (ksize, ksize), 0)
    if color and patch.ndim == 2:
        patch = patch[:, :, None]  # guard against opencv dropping a singleton channel dim

    # sample a thin ring just OUTSIDE the region to match tone; clip each side to image bounds so
    # a region touching the edge simply loses that side instead of erroring
    ring = 5
    sides = [
        image[max(0, y0 - ring):y0, x0:x1],
        image[y1:min(h, y1 + ring), x0:x1],
        image[y0:y1, max(0, x0 - ring):x0],
        image[y0:y1, x1:min(w, x1 + ring)],
    ]
    flat_sides = [s.reshape(-1, n_ch) if color else s.reshape(-1) for s in sides if s.size]
    if flat_sides:
        border_px = np.concatenate(flat_sides, axis=0)
    else:
        # region touches every side (only possible near ratio~1.0) -- fall back to the whole image
        border_px = image.reshape(-1, n_ch) if color else image.reshape(-1)
    border_px = border_px.astype(np.float64)

    axis = 0 if color else None
    b_mean, b_std = border_px.mean(axis=axis), border_px.std(axis=axis)
    p_mean, p_std = patch.reshape(-1, n_ch).mean(axis=0) if color else patch.mean(), \
                    patch.reshape(-1, n_ch).std(axis=0) if color else patch.std()
    p_std = np.where(p_std < 1e-6, 1.0, p_std) if color else (p_std if p_std > 1e-6 else 1.0)
    patch = (patch - p_mean) / p_std * b_std + b_mean  # affine-match mean/std to the border ring

    patch = np.clip(patch, 0, 255).astype(np.uint8)
    out = image.copy()
    out[y0:y1, x0:x1] = patch
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return out, mask


def tamper_noise_corruption(image: np.ndarray, ratio: float, seed: int
                            ) -> tuple[np.ndarray, np.ndarray]:
    """Full destructive overwrite of a rectangular region with fresh random bytes (not additive)."""
    rng = np.random.default_rng(seed)
    h, w = image.shape[:2]
    y0, x0, y1, x1 = _rect_region(h, w, ratio, rng)
    out = image.copy()
    region_shape = out[y0:y1, x0:x1].shape
    out[y0:y1, x0:x1] = rng.integers(0, 256, size=region_shape, dtype=np.uint8)
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return out, mask


TAMPER_FNS: dict[str, Callable] = {
    "splice": tamper_copy_paste,
    "inpaint_removal": tamper_inpaint_removal,
    "crop_refill": tamper_crop_refill,
    "noise": tamper_noise_corruption,
}


def apply_tamper(image: np.ndarray, tamper_class: str, ratio: float,
                 image_id: str, base_seed: int,
                 other_image: np.ndarray | None = None) -> dict:
    """Dispatch to a tamper class with a derived deterministic seed; return results + diagnostics."""
    seed = derive_seed(base_seed, image_id, tamper_class, ratio)
    fn = TAMPER_FNS[tamper_class]
    if tamper_class == "splice":
        tampered, mask = fn(image, ratio, seed, source_image=other_image)
    else:
        tampered, mask = fn(image, ratio, seed)

    # DIAGNOSTIC only, never fed back into the mask (see module docstring on the coincidence trap)
    if image.ndim == 3:
        unchanged = np.all(tampered == image, axis=-1)
    else:
        unchanged = tampered == image
    n_coincidental = int(unchanged[mask].sum())

    return {
        "tampered_image": tampered,
        "gt_mask_px": mask,
        "achieved_ratio": float(mask.sum() / mask.size),
        "seed_used": seed,
        "n_coincidental_unchanged_px": n_coincidental,
    }


def block_mask_from_pixel_mask(pixel_mask: np.ndarray, block: int,
                               rule: str = "any") -> np.ndarray:
    """Reduce a pixel mask to block granularity; rule 'any' (default) or 'majority'.

    The detector only ever outputs whole-block decisions -- a flagged block's mask is the ENTIRE
    block however small the damage inside it -- so scoring ground truth at a finer granularity
    than the detector's own quantization would bake in an asymmetry unrelated to the algorithm's
    real behaviour. That is the reason for 'any', and it stands.

    CORRECTION, from adversarial review. This docstring used to add that "'any' is also the most
    conservative reasonable rule (largest possible ground-truth region), so it can't be accused
    of flattering precision." **That gets the direction of the bias exactly backwards.** The
    largest possible ground-truth region is precisely what MAXIMISES precision, because it
    absorbs every prediction into the true-positive count.

    The consequence is stronger than a wording slip, and it must be reported with the numbers it
    affects: every tamper function here writes ONLY inside its intended region (asserted in the
    self-check with ==, not a tolerance), so any block whose content changed necessarily contains
    at least one region pixel, so under the 'any' rule that block is ground-truth-positive.
    False positives at block level are therefore STRUCTURALLY IMPOSSIBLE, and the measured
    block-level precision of exactly 1.000000 on every row -- with zero variance -- is a
    tautology of the scoring rule, not a measurement of the detector. A detector that flagged
    the entire image would also score 1.000 here.

    Block-level RECALL is unaffected by this and remains a real measurement, as is everything at
    PIXEL level, where the block-quantization penalty actually shows up (measured ~0.95, not 1.0).
    The paper must present pixel precision as the informative localization figure and state
    plainly why the block-level number is vacuous.

    Note also that the non-grid-alignment of tamper regions (see _rect_region) does NOT rescue
    block-level precision, as a comment there once implied: under the 'any' rule, unaligned
    regions make it trivially 1.0 just as aligned ones would. Non-alignment only affects pixel
    precision, which is the point of doing it.

    'majority' is a free secondary column so a robustness footnote can be produced if an
    examiner asks whether the choice of rule drove the result.
    """
    h, w = pixel_mask.shape
    rows, cols = h // block, w // block
    cropped = pixel_mask[: rows * block, : cols * block]  # crop, don't pad -- project convention
    reshaped = cropped.reshape(rows, block, cols, block)
    if rule == "any":
        return reshaped.any(axis=(1, 3))
    return reshaped.mean(axis=(1, 3)) >= 0.5


if __name__ == "__main__":
    rng0 = np.random.default_rng(0)
    for shape in [(64, 64), (64, 64, 3)]:
        img = rng0.integers(0, 256, shape, dtype=np.uint8)
        other = rng0.integers(0, 256, shape, dtype=np.uint8)
        for cls in TAMPER_FNS:
            r1 = apply_tamper(img, cls, 0.25, "test", base_seed=42, other_image=other)
            r2 = apply_tamper(img, cls, 0.25, "test", base_seed=42, other_image=other)
            assert np.array_equal(r1["tampered_image"], r2["tampered_image"])   # determinism
            assert np.array_equal(r1["gt_mask_px"], r2["gt_mask_px"])
            assert r1["tampered_image"].shape == img.shape
            assert r1["tampered_image"].dtype == np.uint8
            assert r1["gt_mask_px"].shape == img.shape[:2]
            assert r1["gt_mask_px"].dtype == bool
            assert abs(r1["achieved_ratio"] - 0.25) < 0.15                     # sizing sane
            outside = ~r1["gt_mask_px"]
            assert np.array_equal(r1["tampered_image"][outside], img[outside]) # EXACT, not approximate
            r3 = apply_tamper(img, cls, 0.25, "test", base_seed=43, other_image=other)
            assert not np.array_equal(r1["tampered_image"], r3["tampered_image"])  # rng actually used

    rng512 = np.random.default_rng(1)
    big_img_512 = rng512.integers(0, 256, (512, 512, 3), dtype=np.uint8)
    other_512 = rng512.integers(0, 256, (512, 512, 3), dtype=np.uint8)

    # all three ratios work for every class, at a realistic size
    for ratio in (0.10, 0.25, 0.50):
        for cls in TAMPER_FNS:
            r = apply_tamper(big_img_512, cls, ratio, "img", 7, other_image=other_512)
            assert abs(r["achieved_ratio"] - ratio) < 0.15, (cls, ratio, r["achieved_ratio"])

    # noise corruption should be near-total replacement inside its region
    r = apply_tamper(big_img_512, "noise", 0.25, "img", 7)
    changed = (r["tampered_image"] != big_img_512)
    if changed.ndim == 3: changed = changed.any(axis=-1)
    assert changed[r["gt_mask_px"]].mean() > 0.95

    # block reduction
    pm = np.zeros((32, 32), dtype=bool); pm[0, 0] = True
    assert block_mask_from_pixel_mask(pm, 8).sum() == 1                  # 'any' catches a single pixel
    assert block_mask_from_pixel_mask(pm, 8, "majority").sum() == 0      # 'majority' does not
    assert block_mask_from_pixel_mask(pm, 8).shape == (4, 4)

    print("tamper.py self-check OK")
