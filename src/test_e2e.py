"""The keystone gate: embed then immediately verify. Nothing downstream is meaningful
until this passes -- see test_keystone's Assertion 3 for the reason a passing
Assertion 1 alone is not enough evidence.
"""

import hashlib
import sys

import numpy as np

from blockmap import build_map
from detect import detect_image
from embed import _synthetic_natural, embed_image
from payload import (budget, crop_to_blocks, encode_descriptor,
                     lsb_pairs_from_blocks, lsb_pairs_to_bits, msb, to_blocks)


def _planes(img: np.ndarray) -> list[np.ndarray]:
    """Split a greyscale (ndim==2) or colour (ndim==3, 3 channels) image into planes."""
    return [img] if img.ndim == 2 else [img[:, :, c] for c in range(3)]


def test_keystone() -> None:
    """Embed then immediately verify an UNTOUCHED watermarked image: zero blocks flagged."""
    KEY = b"e2e-keystone-key"
    rng = np.random.default_rng(0)

    natural = _synthetic_natural(128)
    flat_black = np.zeros((128, 128), dtype=np.uint8)
    flat_white = np.full((128, 128), 255, dtype=np.uint8)
    checker = np.zeros((128, 128), dtype=np.uint8)          # 1-pixel checkerboard: worst-case high freq
    checker[::2, ::2] = 255
    checker[1::2, 1::2] = 255
    full_entropy = rng.integers(0, 256, (128, 128), dtype=np.uint8)
    images = [natural, flat_black, flat_white, checker, full_entropy]

    n = 0
    for base in images:
        for I in (base, np.stack([base] * 3, axis=-1)):     # 2 colour modes
            for B in (4, 8):                                  # 2 block sizes
                for variant in ("A", "B"):                    # 2 variants
                    wm, info = embed_image(I, KEY, b"e2e", B, variant)
                    det = detect_image(wm, KEY, b"e2e", B, variant, refine=False)

                    # Assertion 1 -- THE KEYSTONE. Must be made on raw_mask with
                    # refine=False: if this were asserted on the refined mask instead,
                    # the 8-neighbour pass would silently clean up scattered false
                    # positives, and a partially-broken MSB projection could still
                    # pass. Asserting pre-refinement is the entire point.
                    assert det.raw_mask.sum() == 0, (
                        f"{det.raw_mask.sum()}/{det.raw_mask.size} blocks falsely flagged "
                        f"(B={B}, variant={variant}, colour={I.ndim == 3}) -- "
                        "MSB projection is wrong somewhere")

                    # Assertion 2 -- embedding disturbed only the two LSB planes.
                    Ic, _ = crop_to_blocks(I, B)
                    assert np.array_equal(msb(wm), msb(Ic))

                    # Assertion 3 -- the m/minv canary. MANDATORY AND INDEPENDENT.
                    # Why this cannot be skipped: swapping m and minv between embed and
                    # detect still yields ZERO flagged blocks, because each block
                    # carries its OWN tag and tags are unaffected by which descriptor
                    # sits beside them -- Assertion 1 cannot detect an m/minv swap at
                    # all. This assertion recomputes each channel's own descriptor
                    # directly from the (cropped) original pixels and compares it
                    # against what detect.py handed back as desc_by_owner; an m/minv
                    # swap fails this on essentially every block. Without it, the swap
                    # ships silently and surfaces much later as inexplicably terrible
                    # recovered PSNR.
                    _, tag_bits, desc_bits = budget(B)
                    for ch, plane in enumerate(_planes(Ic)):
                        own, _ = encode_descriptor(msb(to_blocks(plane, B)), variant, desc_bits)
                        assert np.array_equal(det.desc_by_owner[ch], own)

                    n += 1
                    print(f"  [{n}/40] B={B} variant={variant} colour={I.ndim == 3}: "
                          f"psnr={info['psnr']:.2f}")

    assert n == 40


def test_tamper_smoke() -> None:
    """Block-aligned and unaligned wipes: detection covers the tamper."""
    KEY = b"e2e-tamper-key"
    img = _synthetic_natural(128)
    wm, _ = embed_image(img, KEY, b"e2e-tamper", 8, "A")

    # block-aligned wipe: exactly the 4x4 block region flagged, nothing else
    tam = wm.copy(); tam[32:64, 32:64] = 0
    det = detect_image(tam, KEY, b"e2e-tamper", 8, "A")
    assert det.block_mask[4:8, 4:8].all()
    assert det.block_mask.sum() == 16

    # unaligned wipe: detection is intrinsically B x B and over-covers, so the
    # partially-touched border blocks must be flagged too -- the flagged block
    # region must be a SUPERSET of the block-reduced ('any' rule) ground truth,
    # never a subset. The evaluation harness's precision/recall definitions
    # depend on this direction, so it is asserted explicitly rather than assumed.
    tam2 = wm.copy(); tam2[70:130, 70:130] = 0  # numpy clips the slice to 70:128
    gt_px = np.zeros((128, 128), dtype=bool); gt_px[70:128, 70:128] = True
    Rg, Cg = 128 // 8, 128 // 8
    gt_block = gt_px.reshape(Rg, 8, Cg, 8).any(axis=(1, 3))
    det2 = detect_image(tam2, KEY, b"e2e-tamper", 8, "A")
    assert np.all(det2.block_mask[gt_block])  # superset: every touched block is flagged

    print("test_tamper_smoke OK")


# --------------------------------------------------------------------------
# Golden vectors -- the bit-exactness canary
# --------------------------------------------------------------------------
#
# These constants pin the wire format: the block mapping, the payload byte
# layout, and the watermarked output, for one fixed tiny image and one fixed
# key. Any change that alters bit-exactness fails here immediately instead of
# surfacing later as inexplicably bad numbers, or -- worse -- as a silently
# incompatible watermark that a future verifier accepts as authentic.
#
# THE RULE: if these fail, the default assumption is that a change broke the
# format, NOT that the constants are stale. Re-pinning requires a comment
# naming the deliberate change and confirming test_keystone() still passes.
#
# They have been re-pinned twice, both times deliberately, both times to fix a
# security defect found in adversarial review:
#   1. Binding the carried recovery descriptor into the authentication tag
#      (format magic WGT1 -> WGT2) changed the HMAC message. That closed a
#      verified vulnerability in which 96 of 128 payload bits were
#      unauthenticated: an attacker with no key could destroy every recovery
#      descriptor in an image at 40.29 dB PSNR with 0 of 4096 blocks flagged.
#   2. Replacing blockmap._seed_order's quadrant interleave with a flat keyed
#      shuffle changed every mapping. The interleave leaked structure beyond the
#      publicly-documented minimum separation (partner in the same quadrant only
#      2.25% of the time vs a 15.51% separation-only baseline), letting an
#      attacker who knows just the algorithm bias a recoverability-denial attack.
#      It also turned out to buy nothing: the flat shuffle repairs in the same 2
#      sweeps and the same ~0.1s.
# Both changes predate these vectors existing. Had the vectors been in place,
# each would have fired on the change -- which is exactly the point of having
# them, and they were absent when both changes were made.
#
# Because the keystream is HMAC-based rather than random.Random, these values
# are stable across CPython versions, NumPy versions, OS and CPU.

GOLDEN_KEY = b"golden-key-0123456789abcdef01234"   # exactly 32 bytes
GOLDEN_ID = b"GOLDEN"
# 16x16 at B=8 -> K=4 blocks. Deterministic, no corpus dependency.
GOLDEN_IMG = ((np.arange(16 * 16, dtype=np.uint16).reshape(16, 16) * 37) % 256).astype(np.uint8)

GOLDEN = {
    "map_m": (1, 2, 3, 0),
    "map_minv": (3, 0, 1, 2),
    "A_payload_b0": "aa0f369b0402fe05ff0dff03030102fe",
    "A_sha256": "834bed6ae49d74cb5c840dcbac3280c009829742c6dfc831e6c52d9615643403",
    "B_payload_b0": "7b06f057a1a76f82255761ab5fc22567",
    "B_sha256": "bf3b2f662897a3f428d18b6f7b57f53ad1a5be71778395b0e1b9ad327677c386",
    "map4096_sha": "aa4456c3b7e36904d66853dab441b48ac896ee950328aa2e2e4131389eada921",
}


def _golden_actual() -> dict:
    """Compute the current golden values, for both verification and --regen."""
    m, minv, _ = build_map(GOLDEN_KEY, GOLDEN_ID, GOLDEN_IMG.shape, 8)
    out = {"map_m": tuple(int(x) for x in m), "map_minv": tuple(int(x) for x in minv)}
    for variant in ("A", "B"):
        wm, _ = embed_image(GOLDEN_IMG, GOLDEN_KEY, GOLDEN_ID, 8, variant)
        blocks = to_blocks(wm, 8)
        bits = lsb_pairs_to_bits(lsb_pairs_from_blocks(blocks))
        # Pin the payload bytes separately from the image hash: a bit-order change
        # plus a compensating change elsewhere could pass an image-hash-only check,
        # whereas this localizes the failure to the packer.
        out[f"{variant}_payload_b0"] = np.packbits(bits[0]).tobytes().hex()
        out[f"{variant}_sha256"] = hashlib.sha256(wm.tobytes()).hexdigest()
    big, _, _ = build_map(GOLDEN_KEY, GOLDEN_ID, (512, 512), 8)
    # K=4 is too small to catch permutation drift; a K=4096 map hash catches any
    # change to the keystream, the quadrant interleave, or the repair loop.
    out["map4096_sha"] = hashlib.sha256(big.astype("<i4").tobytes()).hexdigest()
    return out


def test_golden_vectors() -> None:
    """Fail loudly if the wire format changed."""
    actual = _golden_actual()
    bad = {k: (GOLDEN[k], actual[k]) for k in GOLDEN if GOLDEN[k] != actual[k]}
    if bad:
        print("GOLDEN VECTOR MISMATCH -- the wire format changed:")
        for k, (want, got) in bad.items():
            print(f"  {k}\n    expected {want}\n    actual   {got}")
        print("Run `python src/test_e2e.py --regen` ONLY if this change was deliberate.")
        raise AssertionError(f"{len(bad)} golden vector(s) mismatched")
    print(f"test_golden_vectors OK ({len(GOLDEN)} vectors pinned)")


if __name__ == "__main__":
    if "--regen" in sys.argv:
        # Regenerating is only valid AFTER the keystone gate passes.
        test_keystone()
        print("\nkeystone passed -- current golden values, paste into GOLDEN:\n")
        for k, v in _golden_actual().items():
            print(f'    "{k}": {v!r},')
        sys.exit(0)
    test_keystone()
    test_tamper_smoke()
    test_golden_vectors()
    print("test_e2e.py: keystone gate PASSED (40/40)")
