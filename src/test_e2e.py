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
                for variant in ("A", "B", "C"):               # 3 variants
                    # Variant C is a block=8 format by construction: its bit
                    # allocation table has 64 entries and there is no 16-entry
                    # equivalent. It is gated here rather than merely available,
                    # because it is what the web app now embeds BY DEFAULT -- an
                    # ungated default is the one thing this gate exists to prevent.
                    if variant == "C" and B != 8:
                        continue
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

                    # Assertion 2 -- embedding disturbed only the two LSB planes, or (#27)
                    # shifted a descriptor pixel exactly one quantization window closer to
                    # its true value -- never further, and never a tag-carrying pixel (see
                    # embed.py's per-channel loop / _shift_lsb_pairs). Used to be exact
                    # equality when embedding only ever plain-replaced; now bounded at one
                    # window (4). Assertion 1 above, not this one, is what actually proves
                    # shifting didn't break authentication.
                    Ic, _ = crop_to_blocks(I, B)
                    assert np.max(np.abs(msb(wm).astype(np.int16)
                                        - msb(Ic).astype(np.int16))) <= 4

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
                    print(f"  [{n}/50] B={B} variant={variant} colour={I.ndim == 3}: "
                          f"psnr={info['psnr']:.2f}")

    # 5 images x 2 colour modes x (2 block sizes x A,B  +  block 8 only x C)
    assert n == 50, n


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


def test_variant_d_roundtrip() -> None:
    """Variant D (PLAN-FIXES.md Phase E, additive): fountain embed/detect/recover through
    the real pipeline, below and above the measured decoding cliff (~alpha=0.63 -- see
    fountain.py and run_experiments.py's Phase E comparison). Fully additive: does not
    touch the golden-vector loop above, and A/B/C's 50 checks and 9 pinned vectors are
    unaffected by anything in this function.
    """
    import fountain
    from recover import recover_image

    KEY = b"e2e-variant-d-key"
    img = _synthetic_natural(256)
    wm, _ = fountain.embed(img, KEY, b"e2e-d", 8)
    det = detect_image(wm, KEY, b"e2e-d", 8, "D", refine=False)
    assert det.raw_mask.sum() == 0, "clean Variant D watermark failed to self-authenticate"

    Rg = 256 // 8
    # Below the cliff: a block-row-aligned wipe covering ~30% of blocks should decode
    # essentially fully -- 3*(1-0.30) = 2.1x redundancy, comfortably above the ~1.05x a
    # peeling decoder needs.
    rows_low = round(0.30 * Rg) * 8
    tam_low = wm.copy(); tam_low[:rows_low, :] = 0
    det_low = detect_image(tam_low, KEY, b"e2e-d", 8, "D")
    rec_low = recover_image(tam_low, det_low, 8, "D", key=KEY)
    assert rec_low.rho > 0.99, rec_low.rho

    # Above the cliff: a peeling decoder fails SHARPLY, not gracefully -- this must
    # report most of the tampered region genuinely unrecoverable, not silently degrade
    # to something resembling the 1-to-1 map's 1-alpha ~= 0.15.
    rows_high = round(0.85 * Rg) * 8
    tam_high = wm.copy(); tam_high[:rows_high, :] = 0
    det_high = detect_image(tam_high, KEY, b"e2e-d", 8, "D")
    rec_high = recover_image(tam_high, det_high, 8, "D", key=KEY)
    assert rec_high.rho < 0.5, rec_high.rho

    print(f"test_variant_d_roundtrip OK (rho={rec_low.rho:.3f} @ alpha=0.30 below cliff, "
          f"rho={rec_high.rho:.3f} @ alpha=0.85 above cliff)")


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
# They have been re-pinned three times, all deliberate:
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
#   3. #27: embed.py stopped plain-replacing the 2 LSBs and started SHIFTING
#      descriptor pixels to the nearest value with the right low bits (see
#      _shift_lsb_pairs), which changes A_/B_/C_payload_b0 and A_/B_/C_sha256 for
#      every variant -- the embedded bytes themselves are different now, on
#      purpose, for a measured ~+1.3-1.5 dB imperceptibility gain. map_m/
#      map_minv/map4096_sha are UNCHANGED (blockmap.py was not touched), which is
#      exactly the evidence that only the pixel-writing step moved.
# All three changes predate their own vectors existing at the time; each would
# have fired on the change that caused it -- which is the whole point of having
# them.
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
    "A_payload_b0": "284f55d40402fe05ff0dff03030102fe",
    "A_sha256": "c670dc635325074ba7b5012b6876316366f2f7bbd78d7429b6b186b316918f1b",
    "B_payload_b0": "3b8a8dcea1a76f82255761ab5fc22567",
    "B_sha256": "17d48b07d376c435e2a2d1a9e8e0e642857e9619d76eb982b2e6b730864c372a",
    # Variant C, added when C became the app's default descriptor. C packs 31-34
    # variable-width signed fields by hand instead of getting sign handling free
    # from int8's byte view, so a one-bit offset slip in the packer is exactly the
    # class of change that must fail here rather than downstream.
    # Adding these did NOT disturb A_* or B_* above -- verified by regenerating all
    # of them together. That is the evidence that introducing C left the existing
    # wire format bit-identical, so watermarks made before C still verify.
    "C_payload_b0": "1edf3cdd830fc809f2207be3ce34ac27",
    "C_sha256": "6f4641f5ccd9abf58511047deec3ad9c49841cd6a05eaa3ffd0a0bdee5f92c0a",
    "map4096_sha": "aa4456c3b7e36904d66853dab441b48ac896ee950328aa2e2e4131389eada921",
}


def _golden_actual() -> dict:
    """Compute the current golden values, for both verification and --regen."""
    m, minv, _ = build_map(GOLDEN_KEY, GOLDEN_ID, GOLDEN_IMG.shape, 8)
    out = {"map_m": tuple(int(x) for x in m), "map_minv": tuple(int(x) for x in minv)}
    for variant in ("A", "B", "C"):
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
    test_variant_d_roundtrip()
    test_golden_vectors()
    print("test_e2e.py: keystone gate PASSED (50/50)")
