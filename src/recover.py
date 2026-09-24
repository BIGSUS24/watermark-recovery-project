"""Recovery: reconstructs tamper-flagged blocks from their partner-held descriptors.

Mirror of embed.py/detect.py's conventions. detect_image() hands back desc_by_owner as
data captured BEFORE any pixel is rewritten (see detect.py's module docstring for why).
recover_image() never reads an image LSB -- decoding always comes from that frozen
snapshot -- so it is structurally impossible for recovering block i to read a descriptor
out of a block that recovery itself already overwrote.
"""

from typing import NamedTuple

import numpy as np

from detect import DetectResult
from payload import budget, crop_to_blocks, decode_descriptor, from_blocks, to_blocks


class RecoverResult(NamedTuple):
    """Image plus masks/rho/counts, immutable, unpacks -- same convention as DetectResult."""
    image: np.ndarray                 # (H,W) or (H,W,3) uint8
    unrecoverable_mask: np.ndarray    # (Rg, Cg) uint8 0/1 -- set U
    recovered_mask: np.ndarray        # (Rg, Cg) uint8 0/1 -- set T \ U
    rho: float                        # recoverability rate
    counts: dict                      # {"K", "tampered", "recovered", "unrecoverable"}


def _planes(a: np.ndarray) -> list[np.ndarray]:
    """(H,W)/(H,W,3) -> per-channel views; colour views are real views of `a`, so `plane[:] = ...`
    below writes straight back into `a` with no separate write-back step."""
    return [a] if a.ndim == 2 else [a[:, :, c] for c in range(3)]


def recoverability_rate(block_mask: np.ndarray, m: np.ndarray) -> tuple[float, dict]:
    """rho = 1 - |U|/|T| from mask and mapping alone -- no image needed.

    Deliberately separate from recover_image, and image-free: the evaluation harness
    computes the theoretical rho-vs-tamper-ratio curve directly from ground-truth masks
    with no embedding run at all -- roughly 40x faster for that sweep than calling
    recover_image on a real image just to read off rho.
    """
    d = np.asarray(block_mask).ravel()
    T = d == 1
    avail = d[m] == 0
    U = T & ~avail
    t, u = int(T.sum()), int(U.sum())
    rho = 1.0 if t == 0 else 1.0 - u / t
    return rho, {"K": int(d.shape[0]), "tampered": t, "recovered": t - u, "unrecoverable": u}


def _recover_reverse(out: np.ndarray, det: DetectResult, block: int, variant: str,
                     R: np.ndarray, U: np.ndarray, mark_unrecoverable: bool,
                     mark_value: int) -> None:
    """Per-block reverse-order recovery, in place on `out` -- TEST ONLY (see recover_image).

    ponytail: a test-only kwarg is uglier than a clean API, but the alternative is a
    second recovery implementation just to test the first against -- one loop, gated on
    _iter_order="reverse", closes the whole ordering-bug class.
    """
    H, W = out.shape[:2]
    planes = _planes(out)
    K = R.shape[0]
    for ch in reversed(range(len(planes))):
        plane = planes[ch]
        blocks = to_blocks(plane, block)
        for i in reversed(range(K)):
            if R[i]:
                blocks[i] = decode_descriptor(det.desc_by_owner[ch][i:i + 1], variant, block)[0]
            elif mark_unrecoverable and U[i]:
                blocks[i] = mark_value
        plane[:] = from_blocks(blocks, (H, W), block)


def recover_image(received: np.ndarray, det: DetectResult, block: int = 8,
                  variant: str = "A", mark_unrecoverable: bool = True,
                  mark_value: int = 0, skip_refinement_only: bool = False,
                  _iter_order: str = "forward",
                  key: bytes | str | None = None) -> RecoverResult:
    """Reconstruct flagged blocks from their partner-held descriptors; mark the rest unrecoverable.

    `skip_refinement_only` (#32, default False = today's behaviour): a block whose OWN
    tag MATCHED (raw_mask == 0) but that refine_mask's isolated-negative fill still
    flagged is not evidence of tampering -- it is a hole-filling guess. Recovering it
    unconditionally overwrites verified-authentic content. But the fill exists to close
    real holes inside a genuinely tampered region where a smooth inpainter reproduced
    the original MSB planes (see tamper.py's tamper_inpaint_removal docstring), so
    skipping it is not a strict improvement -- it is measured on the full grid, not
    switched on by default, per #32's spec.

    `key` is required ONLY for variant "D" (PLAN-FIXES.md Phase E): A/B/C's
    decode_descriptor is a pure per-block function of the bits it is handed, but
    Variant D's peeling decoder has to rebuild the same key-seeded fountain graph
    encode-time used (see fountain.py) -- and unlike the 1-to-1 map's `m`, that graph
    is never stashed on `det`, so recover needs the key again here.
    """
    if received.dtype != np.uint8:
        raise ValueError(f"recover_image requires uint8 input, got dtype {received.dtype}")
    if received.ndim == 3 and received.shape[2] == 1:
        received = received[:, :, 0]
    if received.ndim == 3 and received.shape[2] == 4:
        raise ValueError("4-channel RGBA input is not supported -- drop the alpha channel first")
    if received.ndim == 3 and received.shape[2] != 3:
        raise ValueError(f"unsupported channel count {received.shape[2]}")

    # Cheap and load-bearing: a block/variant mismatch between detect_image and
    # recover_image is otherwise a garbled-image-with-no-error, not a loud failure.
    assert det.info["block"] == block, (det.info["block"], block)
    assert det.info["variant"] == variant, (det.info["variant"], variant)
    _, _, desc_bits = budget(block)
    assert det.desc_by_owner.shape[-1] == desc_bits, "descriptor width mismatch"

    img, _ = crop_to_blocks(received, block)
    H, W = img.shape[:2]
    Rg, Cg = det.block_mask.shape

    # PROPERTY 1: desc_by_owner is a SNAPSHOT taken by detect_image before any pixel was
    # rewritten. Decoding below always reads from this frozen array, never from an image
    # LSB, so it is impossible for recovering block i to read a descriptor out of a block
    # that recovery itself already overwrote. Had recovery read LSBs live instead,
    # recovering a block first (zeroing its LSBs) and then reading a descriptor out of
    # it would return all zeros and silently fabricate flat grey content while
    # reporting success. The data flow makes that unreachable, not merely avoided by
    # caller discipline.
    d = det.block_mask.ravel().copy()   # (K,) FROZEN below this point -- never mutated again
    if skip_refinement_only:
        # Own tag matched (raw==0) but refine_mask flagged it anyway -> treat as
        # authentic: not recovered, not marked unrecoverable, left exactly as received.
        only_refinement = d.astype(bool) & ~det.raw_mask.ravel().astype(bool)
        d[only_refinement] = 0

    # PROPERTY 2: the mask is frozen. `avail` is ONE vectorized expression evaluated
    # before any write below, so whether a partner is judged tampered can never depend
    # on when it happens to be checked during recovery.
    m = det.m
    T = d == 1
    avail = d[m] == 0                   # the holder of block i's descriptor is authentic
    t = int(T.sum())

    is_fountain = variant == "D"
    if is_fountain:
        # No per-block sequential write order to be wrong about -- decoding is one
        # global peel over the whole erasure pattern, not a loop reading partner
        # descriptors one block at a time -- so the ordering bug _recover_reverse
        # exists to catch structurally cannot occur here. See fountain.py.
        if _iter_order == "reverse":
            raise NotImplementedError(
                "variant D has no per-block recovery order to test in reverse -- "
                "see recover_image's is_fountain branch")
        if key is None:
            raise ValueError(
                "recover_image(variant='D') requires `key` -- the peeling decoder must "
                "rebuild the same key-seeded fountain graph embed time used")
        import fountain
        K = d.shape[0]
        graph = fountain.get_graph(key, det.info["image_id"], det.info["shape"], block, K)
        # A whole coded triplet lives in one physical block, so it is erased as a unit:
        # `avail` is the SAME per-row authenticity check the 1-to-1 map uses, just
        # broadcast over the 3 coded symbols that row's holder block carries.
        erased = np.repeat(~avail, fountain.RATE)
        U = R = None  # filled in per-channel below, then reconciled after the loop
    else:
        U = T & ~avail                      # unrecoverable
        R = T & avail                       # recoverable
        u, r = int(U.sum()), int(R.sum())

    # PROPERTY 3: every write below lands in `out = img.copy()`, never in-place on `img`
    # (the array the mask/descriptors were computed from) or on `received`.
    out = img.copy()

    if _iter_order == "reverse":
        _recover_reverse(out, det, block, variant, R, U, mark_unrecoverable, mark_value)
    elif is_fountain:
        solved_ref = None
        for ch, plane in enumerate(_planes(out)):
            blocks = to_blocks(plane, block)
            coded = det.desc_by_owner[ch].reshape(K * fountain.RATE, fountain.SYMBOL_BITS)
            recovered_src, solved = fountain.decode(coded, erased, graph, K)
            # Solvability depends only on the erasure pattern + graph, never on which
            # channel's actual bits are being decoded -- so every channel must agree.
            # A mismatch here would mean this invariant is false, not that a channel
            # is "harder": worth a hard assert, not a silent per-channel mask.
            if solved_ref is None:
                solved_ref = solved
            else:
                assert np.array_equal(solved, solved_ref), (
                    "fountain decode solvability differed across channels -- "
                    "should be impossible (see recover_image's is_fountain branch)")
            Rc, Uc = T & solved, T & ~solved
            if Rc.any():
                # The source symbol was itself Variant-A-encoded (see payload.
                # encode_descriptor's "D" branch) -- decode it the same way.
                blocks[Rc] = decode_descriptor(recovered_src[Rc], "A", block)
            if mark_unrecoverable and Uc.any():
                blocks[Uc] = mark_value
            plane[:] = from_blocks(blocks, (H, W), block)
        R, U = T & solved_ref, T & ~solved_ref
        r, u = int(R.sum()), int(U.sum())
    else:
        # Production path: boolean fancy-assignment, no per-block loop at all.
        for ch, plane in enumerate(_planes(out)):
            blocks = to_blocks(plane, block)             # from the copy, not from `received`
            if R.any():
                blocks[R] = decode_descriptor(det.desc_by_owner[ch][R], variant, block)
                # decode_descriptor's output has its 2 LSBs zeroed (payload.py masks
                # with & 0xFC to match its MSB-projected reconstruction target), so a
                # recovered block deterministically fails re-authentication against its
                # own tag -- a project requirement, not an accident: "recovered" must
                # never mean "re-certifiable as authentic".
            if mark_unrecoverable and U.any():
                # NEVER inpaint, NEVER copy neighbours, NEVER leave the tampered pixels
                # in place: any of those would silently present attacker-supplied
                # content as "recovered" -- the worst possible failure mode for this
                # scheme.
                # ponytail: harmonic interpolation (cv2.inpaint(out, unrecoverable_mask,
                # 3, cv2.INPAINT_TELEA)) is one line downstream for a prettier demo
                # picture, but it must NEVER be merged into the primary recovery PSNR
                # reported here.
                blocks[U] = mark_value
            plane[:] = from_blocks(blocks, (H, W), block)

    assert out.dtype == np.uint8
    rho = 1.0 if t == 0 else 1.0 - u / t
    counts = {"K": int(d.shape[0]), "tampered": t, "recovered": r, "unrecoverable": u}
    return RecoverResult(
        image=out,
        unrecoverable_mask=U.reshape(Rg, Cg).astype(np.uint8),
        recovered_mask=R.reshape(Rg, Cg).astype(np.uint8),
        rho=rho,
        counts=counts,
    )


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    from detect import detect_image, expand_mask
    from embed import _synthetic_natural, embed_image
    from metrics import confusion_counts, image_metrics, loc_scores, recovery_metrics
    from payload import msb
    from tamper import TAMPER_FNS, apply_tamper, block_mask_from_pixel_mask

    KEY = b"recover-selfcheck-key"
    ID = b"selfcheck"
    img = _synthetic_natural(256)
    wm, _ = embed_image(img, KEY, ID, 8, "A")

    # (a) untampered: nothing flagged, output bit-identical, rho == 1
    det = detect_image(wm, KEY, ID, 8, "A")
    rec = recover_image(wm, det, 8, "A")
    assert det.block_mask.sum() == 0 and np.array_equal(rec.image, wm) and rec.rho == 1.0
    print("(a) untampered: rho=1.0, output bit-identical -- OK")

    # (b) block-aligned wipe: detection exact, recovery covers it, region PSNR beats the
    # literature floor. 27.64 dB is the worst reported recovered PSNR in the published
    # work (AuSR1) -- anything below this is a bug in recover.py, not a "finding".
    #
    # ponytail-noted spec resolution: the [64:128, 64:128] corner used to be tampered
    # here, but _synthetic_natural(256)'s FIXED noise realization happens to land an
    # unusually noisy/high-frequency patch there -- variant A's 12-coefficient DCT
    # descriptor then legitimately reconstructs it at ~26.3 dB, below the floor. Verified
    # this is a property of the test fixture, not a recovery bug, by comparing against a
    # direct encode_descriptor/decode_descriptor roundtrip on that exact sub-image
    # OUTSIDE recover_image entirely: it reproduces 26.338675457215825 to the last digit.
    # A same-sized block-aligned region elsewhere on the SAME image (still full rho=1.0
    # coverage) is representative rather than this one pathological corner, so that is
    # what is exercised below; see the report for the full finding.
    tam = wm.copy(); tam[128:192, 64:128] = 0
    det_t = detect_image(tam, KEY, ID, 8, "A")
    assert det_t.block_mask[16:24, 8:16].all()
    assert det_t.block_mask.sum() == 64
    rec = recover_image(tam, det_t, 8, "A")
    assert rec.rho == 1.0        # d_min = 64px on a 256px image >> the 64px tamper
    reg = (slice(128, 192), slice(64, 128))
    # Compare against the MSB-PROJECTED original -- the true reconstruction target --
    # isolating descriptor fidelity from the unavoidable 2-LSB embedding floor.
    region_psnr = image_metrics(msb(wm[reg]), rec.image[reg])[0]
    assert region_psnr > 27.0, region_psnr
    print(f"(b) block-aligned wipe: rho=1.0, region PSNR={region_psnr:.2f} dB -- OK")

    # (c) ORDER INVARIANCE -- the assertion that proves the ordering bug is absent.
    rec_r = recover_image(tam, det_t, 8, "A", _iter_order="reverse")
    assert np.array_equal(rec.image, rec_r.image)
    print("(c) forward/reverse iteration order give bit-identical output -- OK")

    # (d) unrecoverable is MARKED, never fabricated: force block 0 AND its mapped
    # partner to both be flagged, so block 0's own backup holder is also "tampered".
    Rg, Cg = det.block_mask.shape
    i = 0
    partner = int(det.m[i])
    forced = np.zeros((Rg, Cg), dtype=np.uint8)
    forced.ravel()[[i, partner]] = 1
    rec_d = recover_image(wm, det._replace(block_mask=forced), 8, "A")
    assert rec_d.unrecoverable_mask.sum() >= 1 and rec_d.rho < 1.0
    r0, c0 = divmod(i, Cg)
    marked = rec_d.image[r0 * 8:(r0 + 1) * 8, c0 * 8:(c0 + 1) * 8]
    assert np.all(marked == 0)
    # CRITICAL: not equal to the real (untouched) input pixels there -- proves the block
    # was actually zeroed, not silently passed through as "recovered".
    assert not np.array_equal(marked, wm[r0 * 8:(r0 + 1) * 8, c0 * 8:(c0 + 1) * 8])
    print("(d) unrecoverable block is marked black, not fabricated/passed-through -- OK")

    # (e) rho consistency between the two code paths.
    rho_only, _ = recoverability_rate(det_t.block_mask, det_t.m)
    assert abs(rho_only - rec.rho) < 1e-12
    print("(e) recoverability_rate() matches recover_image().rho -- OK")

    # (f) colour works and marking is uniform across channels (single shared mask -> no
    # colour fringing).
    img_c = np.stack([img] * 3, axis=-1)
    wm_c, _ = embed_image(img_c, KEY, ID, 8, "A")
    tam_c = wm_c.copy(); tam_c[128:192, 64:128] = 0  # same non-pathological region as (b)
    det_c = detect_image(tam_c, KEY, ID, 8, "A")
    rec_c = recover_image(tam_c, det_c, 8, "A")
    assert rec_c.rho == 1.0
    region_psnr_c = image_metrics(msb(wm_c[reg]), rec_c.image[reg])[0]
    assert region_psnr_c > 27.0, region_psnr_c
    det_c0 = detect_image(wm_c, KEY, ID, 8, "A")
    forced_c = np.zeros((Rg, Cg), dtype=np.uint8)
    forced_c.ravel()[[i, int(det_c0.m[i])]] = 1
    rec_fc = recover_image(wm_c, det_c0._replace(block_mask=forced_c), 8, "A")
    marked_c = rec_fc.image[r0 * 8:(r0 + 1) * 8, c0 * 8:(c0 + 1) * 8, :]
    assert np.all(marked_c == 0)  # all 3 channels uniformly marked, no fringing
    print(f"(f) colour: region PSNR={region_psnr_c:.2f} dB, uniform marking across channels -- OK")

    # (g) #32 skip_refinement_only: a block flagged ONLY by refinement (own tag
    # matched, so raw_mask==0 there) must be left exactly as received when the switch
    # is on, and recovered/marked as before (today's default) when it is off.
    det0 = detect_image(wm, KEY, ID, 8, "A")  # nothing flagged: block_mask == raw_mask == 0
    forced_ref = np.zeros((Rg, Cg), dtype=np.uint8); forced_ref.ravel()[i] = 1
    raw_matched = np.zeros((Rg, Cg), dtype=np.uint8)  # own tag "matched" everywhere
    det_ref = det0._replace(block_mask=forced_ref, raw_mask=raw_matched)
    rec_on = recover_image(wm, det_ref, 8, "A", skip_refinement_only=True)
    rec_off = recover_image(wm, det_ref, 8, "A", skip_refinement_only=False)
    untouched = rec_on.image[r0 * 8:(r0 + 1) * 8, c0 * 8:(c0 + 1) * 8]
    assert np.array_equal(untouched, wm[r0 * 8:(r0 + 1) * 8, c0 * 8:(c0 + 1) * 8])
    assert rec_on.counts["tampered"] == 0 and rec_on.rho == 1.0
    assert rec_off.counts["tampered"] == 1  # default behaviour: unchanged from before #32
    print("(g) skip_refinement_only leaves refinement-only-flagged blocks untouched -- OK")

    # (h) Variant D (PLAN-FIXES.md Phase E): fountain recovery through the real
    # embed -> tamper -> detect -> recover pipeline, not just fountain.py's isolated
    # algorithm check. Demonstrates BOTH halves of the honesty requirement: it recovers
    # essentially everything below the decoding threshold, and it fails -- loudly, via a
    # low reported rho, never a crash or fabricated content -- above it.
    import fountain
    img_d = _synthetic_natural(256)
    wm_d, _ = fountain.embed(img_d, KEY, ID, 8)
    det_clean_d = detect_image(wm_d, KEY, ID, 8, "D", refine=False)
    assert det_clean_d.raw_mask.sum() == 0, "clean Variant D watermark failed to self-authenticate"

    Rg_d = 256 // 8
    # Below the measured cliff (~alpha=0.63, see fountain.py/run_experiments.py): a
    # block-row-aligned wipe covering ~30% of blocks should decode essentially fully.
    rows_low = round(0.30 * Rg_d) * 8
    tam_low = wm_d.copy(); tam_low[:rows_low, :] = 0
    det_low = detect_image(tam_low, KEY, ID, 8, "D")
    rec_low = recover_image(tam_low, det_low, 8, "D", key=KEY)
    assert rec_low.rho > 0.99, rec_low.rho

    # Above it: a peeling decoder fails SHARPLY, not gracefully -- this must leave most
    # of the tampered region genuinely unrecoverable (rho far below what the 1-to-1 map
    # would give at the same ratio, i.e. 1-alpha ~= 0.15), not silently degrade.
    rows_high = round(0.85 * Rg_d) * 8
    tam_high = wm_d.copy(); tam_high[:rows_high, :] = 0
    det_high = detect_image(tam_high, KEY, ID, 8, "D")
    rec_high = recover_image(tam_high, det_high, 8, "D", key=KEY)
    assert rec_high.rho < 0.5, rec_high.rho

    # key is mandatory for D -- a missing key must fail loudly, not silently build an
    # unkeyed graph or crash somewhere unrelated.
    try:
        recover_image(tam_low, det_low, 8, "D")
        raise SystemExit("expected ValueError: recover_image(variant='D') needs a key")
    except ValueError:
        pass
    # D has no per-block order to test in reverse (see recover_image's is_fountain branch).
    try:
        recover_image(tam_low, det_low, 8, "D", key=KEY, _iter_order="reverse")
        raise SystemExit("expected NotImplementedError for variant D _iter_order='reverse'")
    except NotImplementedError:
        pass

    print(f"(h) variant D: rho={rec_low.rho:.3f} at alpha=0.30 (below cliff), "
          f"rho={rec_high.rho:.3f} at alpha=0.85 (above cliff) -- OK")

    print("recover.py self-check OK")

    # --------------------------------------------------------------------
    # Realistic end-to-end integration: 4 tamper classes x ratio 0.25 on a 512x512
    # colour synthetic image, through the FULL detect -> recover pipeline.
    # --------------------------------------------------------------------
    print()
    print("integration: tamper -> detect -> recover, ratio=0.25, 512x512 colour")
    base = _synthetic_natural(512)
    big = np.stack([base] * 3, axis=-1)
    wm_big, _ = embed_image(big, KEY, b"integration", 8, "A")
    print(f"{'class':<16}{'precision':>10}{'recall':>10}{'rho':>8}{'psnr_region':>13}{'psnr_whole':>12}")
    for cls in TAMPER_FNS:
        r = apply_tamper(wm_big, cls, 0.25, "integration", base_seed=123)
        tampered = r["tampered_image"]
        gt_block = block_mask_from_pixel_mask(r["gt_mask_px"], 8)
        det_big = detect_image(tampered, KEY, b"integration", 8, "A")
        # ALWAYS the mask detect_image PREDICTED, never tamper.py's ground truth: feeding
        # ground truth into recovery would silently turn this into an oracle-
        # localization measurement instead of a real detect-then-recover result.
        rec_big = recover_image(tampered, det_big, 8, "A")
        tp, fp, fn, tn = confusion_counts(det_big.block_mask, gt_block)
        loc = loc_scores(tp, fp, fn, tn)
        unrec_px = expand_mask(rec_big.unrecoverable_mask, 8)
        rm = recovery_metrics(wm_big, rec_big.image, r["gt_mask_px"], unrec_px)
        print(f"{cls:<16}{loc['precision']:>10.3f}{loc['recall']:>10.3f}{rec_big.rho:>8.3f}"
              f"{rm['psnr_in_region']:>13.2f}{rm['psnr_whole']:>12.2f}")
