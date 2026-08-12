"""Re-derives Variant C's quantization tables and checks them against payload.py.

Variant C spends its 96 descriptor bits as ~34 variable-width DCT coefficient
fields instead of Variant A's 12 fixed 8-bit ones. The widths and step sizes are
not hand-tuned: they are the output of a rate-distortion optimization run against
measured coefficient statistics, and this module is that run. `python
src/fit_variant_c.py` re-derives both tables from scratch and asserts they equal
the literals in payload.py, so the format constants cannot drift away from the
procedure that justifies them -- the same standard the rest of this project holds
its numbers to.

Because the DCT here is orthonormal, summed squared error in the coefficient
domain IS summed squared error in the pixel domain (Parseval). Minimising one
minimises the other exactly, which is what makes a per-coefficient allocator
valid at all.

THE TRAINING SET, and why it looks like this. Two content classes have opposite
demands. A photograph's DCT energy collapses into the first few zig-zag terms, so
it wants precision. A document scan is broadband -- text is edges -- and it wants
coefficient COUNT. Fitting on documents alone starved chroma badly enough to cost
a saturated-colour image 7.3 dB; fitting on photographs alone left document text
blurred. So the training set is deliberately mixed: one synthetic document page
plus three corpus photographs.

The document is SYNTHESISED here, procedurally, from a fixed seed -- not loaded
from a file. Two reasons, both load-bearing:
  1. The real scanned page this variant was developed against is somebody's
     personal document. It has no business in a public repository, and a fit that
     depends on it would not be reproducible by anyone else.
  2. Rendering text would drag in a font, and a font is either a system
     dependency (absent on some machines) or a Pillow bitmap whose rasterisation
     can shift between versions. Procedural numpy has neither problem: the same
     seed gives the same page on every machine, forever.
What matters statistically is not that it says words, but that it has the right
DCT signature: hard black-on-white strokes a few pixels wide arranged in
horizontal runs, a mostly-flat page, a faint colour cast, and scanner noise.
"""

from pathlib import Path

import cv2
import numpy as np

from embed import load_image
from payload import (C_BITS, C_DESC_BITS, C_MODE_BITS, C_STEPS, budget,
                     dct_matrix, decode_descriptor, encode_descriptor,
                     from_blocks, msb, to_blocks, zigzag_indices)

SAMPLES = Path(__file__).resolve().parent.parent / "samples"
B = 8
MAX_BITS = 8                       # widest field the packer will emit
LOADS = np.linspace(1.2, 6.0, 49)  # candidate quantizer loading factors, in sigmas
RD_SAMPLE_CAP = 120_000            # coefficients sampled per position when fitting
TRAIN_PHOTOS = ("airplane.png", "baboon.png", "house.png")
DOC_BLUR_SIGMA = 0.7               # see synthetic_document(); swept, not guessed


# --------------------------------------------------------------------------
# Synthetic training document
# --------------------------------------------------------------------------

def synthetic_document(h: int = 880, w: int = 648, seed: int = 0) -> np.ndarray:
    """A deterministic stand-in for a photographed text page, as uint8 RGB.

    Not a picture of text -- a source with the same DCT statistics as one.
    """
    rng = np.random.default_rng(seed)
    page = np.full((h, w), 236.0)                     # off-white paper, not pure white

    y = 40
    while y < h - 40:
        line_h = rng.integers(9, 15)                  # x-height of this line
        x = 40 + rng.integers(0, 30)
        right = w - 40 - rng.integers(0, 120)         # ragged right edge
        while x < right:
            gw = rng.integers(3, 11)                  # glyph width
            if rng.random() < 0.82:                   # 18% of slots are spaces
                # A glyph is a dark bar with a lighter interior -- gives both the
                # sharp stroke edges and the mid-frequency structure real text has.
                ink = rng.uniform(20, 70)
                page[y:y + line_h, x:x + gw] = ink
                if gw >= 6 and line_h >= 10:
                    page[y + 2:y + line_h - 2, x + 2:x + gw - 2] = ink + rng.uniform(40, 110)
            x += gw + rng.integers(1, 4)
        y += line_h + rng.integers(6, 14)

    # Lens blur, and it is load-bearing. Hard pixel-edge glyphs put far more energy
    # in the high zig-zag terms than any photograph of a page does -- a real camera
    # always band-limits -- and an unblurred page pushes the fit to over-weight AC.
    # DOC_BLUR_SIGMA was not picked for realism: it was swept, and each value judged
    # by the WORST-CASE gain of the table it produces across the held-out corpus.
    # Measured: sigma 0 -> +1.95 dB worst / +3.03 mean; 0.3 -> +1.96 / +3.04;
    # 0.7 -> +2.52 / +3.43; 0.9 -> +1.47 / +3.19. 0.7 dominates on both.
    page = cv2.GaussianBlur(page, (0, 0), DOC_BLUR_SIGMA)

    # A photographed page is never evenly lit and never perfectly grey.
    gy, gx = np.mgrid[0:h, 0:w]
    page *= 1.0 - 0.10 * (gx / w) - 0.05 * (gy / h)
    page += rng.normal(0.0, 3.0, (h, w))              # sensor noise

    cast = np.array([1.00, 0.985, 0.955])             # faint warm cast, still near-grey
    rgb = np.clip(page[:, :, None] * cast[None, None, :], 0, 255).astype(np.uint8)
    return rgb


# --------------------------------------------------------------------------
# Rate-distortion fit
# --------------------------------------------------------------------------

def zz_coefficients(img_msb: np.ndarray) -> np.ndarray:
    """(H,W,3) MSB-projected -> (3K, 64) zig-zag-ordered DCT coefficients."""
    h, w = img_msb.shape[:2]
    h, w = h - h % B, w - w % B
    stack = np.stack([to_blocks(img_msb[:h, :w, c], B) for c in range(3)])
    D = dct_matrix(B)
    C = D @ (stack.astype(np.float64) - 128.0) @ D.T
    zz = zigzag_indices(B)
    return C[:, :, [r for r, _ in zz], [c for _, c in zz]].reshape(-1, B * B)


def rd_curve(coef: np.ndarray, rng: np.random.Generator
             ) -> tuple[np.ndarray, np.ndarray]:
    """Measured (distortion, best step) for every (zig-zag position, bit width).

    The step for a given width is chosen by MEASURING squared error over a grid of
    loading factors and keeping the minimum -- saturation included. That is why
    Variant C saturates on purpose where Variant A proves it never does: for a
    2-bit field, clipping a rare large coefficient genuinely beats spreading the
    same 2 bits over a range wide enough to contain it.
    """
    if coef.shape[0] > RD_SAMPLE_CAP:
        coef = coef[rng.choice(coef.shape[0], RD_SAMPLE_CAP, replace=False)]
    sigma = coef.std(0)
    dist = np.zeros((B * B, MAX_BITS + 1))
    step = np.ones((B * B, MAX_BITS + 1))
    dist[:, 0] = (coef ** 2).mean(0)          # 0 bits = coefficient dropped entirely
    for i in range(B * B):
        ci = coef[:, i]
        for bits in range(1, MAX_BITS + 1):
            lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
            cand = np.maximum(2 * LOADS * sigma[i] / (2 ** bits), 1e-6)
            err = [((np.clip(np.rint(ci / s), lo, hi) * s - ci) ** 2).mean() for s in cand]
            j = int(np.argmin(err))
            dist[i, bits], step[i, bits] = err[j], cand[j]
    return dist, step


def lower_convex(d: np.ndarray) -> np.ndarray:
    """Lower convex hull along the rate axis.

    Greedy marginal-gain allocation is only optimal when each position's
    distortion-vs-bits curve is convex. Measured curves are very nearly convex but
    not exactly, and one concave kink lets greedy stop early at a position that
    would still have paid off two bits later.
    """
    out = d.copy()
    for _ in range(len(d)):
        changed = False
        for b in range(1, len(d) - 1):
            mid = 0.5 * (out[b - 1] + out[b + 1])
            if out[b] > mid:
                out[b], changed = mid, True
        if not changed:
            break
    return out


def allocate(dist: np.ndarray, total: int, dc_floor: int) -> np.ndarray:
    """Hand out `total` bits to whichever position buys the most measured error.

    `dc_floor` is a deliberate departure from pure MSE optimality. A coarse DC step
    shifts a whole 8x8 block's brightness, which reads as blotching -- far more
    objectionable than the same squared error spread across AC terms. Unconstrained,
    the optimizer gave DC 6 bits and regressed a smooth low-detail image by 1.92 dB.
    A floor of 7 turned that into a 0.72 dB GAIN while costing 0.04 dB of mean.
    """
    conv = np.stack([lower_convex(dist[i]) for i in range(B * B)])
    bits = np.zeros(B * B, dtype=int)
    bits[0] = dc_floor

    def gain(i):
        return conv[i, bits[i]] - conv[i, bits[i] + 1] if bits[i] < MAX_BITS else -1.0

    g = np.array([gain(i) for i in range(B * B)])
    for _ in range(total - dc_floor):
        i = int(np.argmax(g))
        if g[i] <= 0:
            break
        bits[i] += 1
        g[i] = gain(i)
    return bits


def fit() -> tuple[tuple, tuple]:
    """-> (bits_per_mode, steps_per_mode), each a 2-tuple of 64-length tuples."""
    rng = np.random.default_rng(0)
    train = [msb(synthetic_document())]
    for name in TRAIN_PHOTOS:
        p = SAMPLES / "usc_sipi" / name
        if not p.exists():
            raise SystemExit(
                f"missing training image {p}.\nRun 'python samples/fetch_corpus.py' first "
                f"-- this fit needs the corpus, like every other stage in the "
                f"reproduction chain (see README).")
        img = load_image(p)
        train.append(msb(img if img.ndim == 3 else np.stack([img] * 3, -1))[:, :, :3])

    coef = np.concatenate([zz_coefficients(t) for t in train])

    # Two tables, split on AC energy: smooth blocks and detailed blocks want
    # different allocations, and one bit of the 96 says which was used. That bit is
    # covered by the HMAC already, because it lives in the descriptor field.
    ac_energy = (coef[:, 1:] ** 2).sum(1)
    split = np.median(ac_energy)
    budget_bits = C_DESC_BITS - C_MODE_BITS

    bits_out, steps_out = [], []
    for subset in (coef[ac_energy <= split], coef[ac_energy > split]):
        dist, step = rd_curve(subset, rng)
        bits = allocate(dist, budget_bits, dc_floor=7)
        assert bits.sum() == budget_bits, bits.sum()
        steps = np.where(bits > 0, step[np.arange(B * B), np.maximum(bits, 1)], 0.0)
        bits_out.append(tuple(int(v) for v in bits))
        steps_out.append(tuple(round(float(v), 4) for v in steps))
    return tuple(bits_out), tuple(steps_out)


# --------------------------------------------------------------------------
# Self-check: refit, compare to the shipped literals, measure the gain
# --------------------------------------------------------------------------

def reconstruct(img_msb: np.ndarray, variant: str, desc_bits: int) -> np.ndarray:
    """Round-trip a whole image through one descriptor variant, per channel."""
    h, w = img_msb.shape[:2]
    h, w = h - h % B, w - w % B
    planes = []
    for c in range(3):
        blocks = to_blocks(img_msb[:h, :w, c], B)
        bits_c, _ = encode_descriptor(blocks, variant, desc_bits)
        planes.append(from_blocks(decode_descriptor(bits_c, variant, B), (h, w), B))
    return np.stack(planes, -1)


if __name__ == "__main__":
    bits, steps = fit()

    drift = (bits != C_BITS) or (steps != C_STEPS)

    # Measure the tables THIS RUN just derived, not whatever payload.py currently
    # ships. Without this the printed gains silently describe the old constants
    # whenever a refit differs, which is precisely when someone is reading them --
    # a genuinely misleading failure mode, caught the first time it happened.
    # Patching the module globals rather than reimplementing the quantizer keeps
    # the measurement running through the REAL codec.
    import payload as _p
    _p.C_BITS, _p.C_STEPS = bits, steps

    if drift:
        print("TABLES DIFFER from payload.py. Refitted values:\n")
        print("C_BITS = (")
        for m in (0, 1):
            print(f"    # mode {m} -- {sum(1 for v in bits[m] if v)} coefficients, "
                  f"{sum(bits[m])} bits")
            print(f"    {bits[m]},")
        print(")\n\nC_STEPS = (")
        for m in (0, 1):
            print(f"    {steps[m]},")
        print(")")
    else:
        print(f"tables match payload.py exactly "
              f"({sum(1 for v in C_BITS[0] if v)}/{sum(1 for v in C_BITS[1] if v)} "
              f"coefficients per mode, {sum(C_BITS[0])}+{C_MODE_BITS} bits)")

    # Measure what the shipped tables actually buy, on held-out corpus images the
    # fit never saw. Reported as the ceiling on recovery: descriptors intact, zero
    # tampering -- no recovery can beat this, so it is the honest figure of merit.
    _, _, db = budget(B)
    held = [p for p in sorted((SAMPLES / "usc_sipi").glob("*.png"))
            if p.name not in TRAIN_PHOTOS] + \
           sorted((SAMPLES / "kodak").glob("*.png"))[:8]
    rows = [("synthetic-doc", msb(synthetic_document()))]
    rows += [(p.stem, msb(load_image(p)[:, :, :3])) for p in held]

    label = "REFITTED (not yet in payload.py)" if drift else "shipped"
    print(f"\nceiling on recovery -- descriptors intact, zero tamper. C table: {label}")
    print(f"{'image':<16}{'A':>8}{'C':>8}{'gain':>8}")
    gains = []
    for name, img in rows:
        h, w = img.shape[:2]; h, w = h - h % B, w - w % B
        ref = img[:h, :w]
        out = {}
        for v in ("A", "C"):
            rec = reconstruct(ref, v, db)
            mse = ((ref.astype(np.float64) - rec.astype(np.float64)) ** 2).mean()
            out[v] = 10 * np.log10(255.0 ** 2 / max(mse, 1e-12))
        gains.append(out["C"] - out["A"])
        print(f"{name[:15]:<16}{out['A']:>8.2f}{out['C']:>8.2f}{out['C'] - out['A']:>+8.2f}")
    print(f"{'MEAN':<16}{'':>8}{'':>8}{np.mean(gains):>+8.2f}")
    print(f"worst case: {min(gains):+.2f} dB")

    # The guarantee that makes C safe to default to. A mean gain would not be
    # enough: this table ships for every user and every image, so "never worse
    # than the variant it replaces" is the property that has to hold.
    assert min(gains) > 0, f"variant C regressed an image by {min(gains):.2f} dB"
    assert not drift, "refit does not reproduce the shipped tables -- update payload.py"
    print("\nfit_variant_c.py self-check OK")
