"""Detector: recomputes per-block HMAC tags, flags mismatches, refines, expands to pixels.

Mirror of embed.py -- see that module's docstring for the shared conventions. Read
blockmap.py's DIRECTION CONTRACT before touching this file:
    m[i]    = index of the block that STORES block i's descriptor.
    minv[i] = index of the block whose descriptor is STORED IN block i.
embed.py wrote with minv (block i carries desc[minv[i]]). detect.py reads with m.

Derivation for the read side: stored_desc[h] is the descriptor found INSIDE holder
block h; embedding put desc[minv[h]] there, so it is the descriptor OF block
minv[h]. Setting j = minv[h] gives h = m[j] (m and minv are mutual inverses), hence
desc_by_owner[j] = stored_desc[m[j]], i.e. desc_by_owner = stored_desc[m].

Detection is tag-based and per-block-independent: a block whose OWN pixels are
untouched always reports authentic, even if the tamper was elsewhere and destroyed
that block's turn as somebody else's backup. Concretely: if a tamper changed ONLY
another block's LSBs (not its own MSB content), this block's tag still matches and
it is correctly reported authentic -- the damage surfaces later as a recovery
failure on the OTHER block, never as a detection failure here. That is also why a
wrong `variant` at detect time fails everything (loudly) instead of garbling
descriptors quietly: variant is bound into the HMAC message, so a mismatch is an
authentication failure, not a silent misread.
"""

from typing import NamedTuple

import numpy as np

from blockmap import build_map
from payload import (block_tags, budget, coerce_key, crop_to_blocks,
                     lsb_pairs_from_blocks, lsb_pairs_to_bits, msb, to_blocks)


class DetectResult(NamedTuple):
    """Nine fields that travel together, immutable, unpacks, type-hinted.

    ponytail: a NamedTuple instead of a dataclass -- zero boilerplate for pure data
    with no attached behaviour. Escalate to a dataclass only if behaviour ever
    attaches to this bundle.
    """
    raw_mask: np.ndarray        # (Rg, Cg) uint8 0/1 -- PRE-refinement, channel-OR
    block_mask: np.ndarray      # (Rg, Cg) uint8 0/1 -- POST-refinement; THE mask
    pixel_mask: np.ndarray      # (H, W)   uint8 0/1
    desc_by_owner: np.ndarray   # (C, K, desc_bits) uint8 -- descriptor OF block j, per channel
    per_channel: np.ndarray     # (C, K)   uint8 0/1 -- raw per-channel mismatch
    m: np.ndarray               # (K,) int32 -- the shared mapping, passed on to recover()
    stored_tags: np.ndarray     # (C, K, tag_bits) uint8 -- the tag found IN each block
    fresh_tags: np.ndarray      # (C, K, tag_bits) uint8 -- the tag recomputed for each block
    info: dict

    def audit(self, block_index: int, channel: int = 0) -> dict:
        """Per-block audit record: the evidence behind one verification decision.

        This is the concrete substance of the project's explainability claim, so it must
        exist rather than be asserted. Every field is a fact a third party holding the key
        can independently recompute and check -- which is exactly what a learned
        localizer's network output cannot offer.

        Returns the stored tag, the recomputed tag, whether they matched, the partner
        block index that holds this block's recovery descriptor, and -- for a flagged
        block -- either that partner's index or an explicit refusal reason.
        """
        i = int(block_index)
        stored = self.stored_tags[channel, i]
        fresh = self.fresh_tags[channel, i]
        matched = bool(np.array_equal(stored, fresh))
        Cg = self.block_mask.shape[1]
        flagged = bool(self.block_mask[i // Cg, i % Cg])
        partner = int(self.m[i])
        partner_flagged = bool(self.block_mask[partner // Cg, partner % Cg])
        rec = {
            "block": i,
            "channel": channel,
            "stored_tag": stored.copy(),
            "recomputed_tag": fresh.copy(),
            "tag_matched": matched,
            "flagged_raw": bool(self.per_channel[channel, i]),
            "flagged_after_refinement": flagged,
            "partner_block": partner,
            "partner_flagged": partner_flagged,
        }
        if not flagged:
            rec["decision"] = "AUTHENTIC"
            rec["reason"] = "recomputed tag equals stored tag"
        elif partner_flagged:
            rec["decision"] = "UNRECOVERABLE"
            rec["reason"] = (f"tag mismatch, and the partner block {partner} holding this "
                             f"block's recovery descriptor was also flagged -- refusing to "
                             f"fabricate content (tamper coincidence)")
        else:
            rec["decision"] = "RECOVERABLE"
            rec["reason"] = (f"tag mismatch; recovery descriptor read from intact "
                             f"partner block {partner}")
        # A flagged-after-refinement block whose OWN tag matched was invented by the
        # isolated-negative fill, not by a hash mismatch. Surfacing it matters: recovery
        # will overwrite verified-authentic content with a lossy approximation.
        if flagged and matched:
            rec["decision"] = "FLAGGED_BY_REFINEMENT"
            rec["reason"] = ("tag MATCHED -- this block was flagged by the neighbourhood "
                             "fill rule, not by a hash mismatch; recovery will overwrite "
                             "authentic content")
        return rec


def detect_image(img: np.ndarray, key: bytes | str, image_id: bytes | str,
                 block: int = 8, variant: str = "A", tau: int = 7,
                 refine: bool = True, d_min: float | None = None,
                 clear_isolated: bool = False) -> DetectResult:
    """Recompute per-block HMAC tags, flag mismatches, refine, and expand to a pixel mask.

    Returns desc_by_owner as a SNAPSHOT rather than leaving recover() to read image
    LSBs live: recovering a block first zeroes its LSBs, so if recovery read a later
    block's descriptor out of the image after an earlier recovery already wrote to it,
    it would read back all zeros and silently fabricate flat content while reporting
    success. Snapshotting here makes that failure mode unreachable rather than merely
    avoided by caller discipline.
    """
    if img.dtype != np.uint8:
        raise ValueError(f"detect_image requires uint8 input, got dtype {img.dtype}")
    if img.ndim == 3 and img.shape[2] == 1:
        img = img[:, :, 0]
    if img.ndim == 3 and img.shape[2] == 4:
        raise ValueError("4-channel RGBA input is not supported -- drop the alpha channel first")
    if img.ndim == 3 and img.shape[2] != 3:
        raise ValueError(f"unsupported channel count {img.shape[2]}")
    greyscale = img.ndim == 2

    key_b = coerce_key(key)
    iid = image_id.encode("utf-8") if isinstance(image_id, str) else image_id

    # crop_to_blocks applies the same rule embed.py used, so K matches as long as the
    # received image has the same dimensions that were embedded. If the image was
    # resized, geometry no longer lines up and everything fails -- correct behaviour
    # for a fragile scheme, not a bug to work around here.
    img, crop = crop_to_blocks(img, block)
    H, W = img.shape[:2]
    cap, tag_bits, desc_bits = budget(block)
    m, minv, map_info = build_map(key_b, iid, (H, W), block, d_min)  # regenerated, never transmitted
    Rg, Cg = H // block, W // block
    K = Rg * Cg

    planes = [img] if greyscale else [img[:, :, c] for c in range(3)]
    C = len(planes)
    per_channel = np.empty((C, K), dtype=np.uint8)
    desc_by_owner = np.empty((C, K, desc_bits), dtype=np.uint8)
    # Kept for the per-block audit record (DetectResult.audit): the stored and
    # recomputed tag are the evidence behind each decision, so a third party with
    # the key can re-verify any single block rather than trusting the mask.
    stored_tags = np.empty((C, K, tag_bits), dtype=np.uint8)
    fresh_tags = np.empty((C, K, tag_bits), dtype=np.uint8)
    for ch, plane in enumerate(planes):
        blocks = to_blocks(plane, block)
        bmsb = msb(blocks)
        stored = lsb_pairs_to_bits(lsb_pairs_from_blocks(blocks))  # (K, cap) extracted payload
        stored_tag = stored[:, :tag_bits]
        stored_desc = stored[:, tag_bits:]  # indexed by HOLDER block, not by owner
        # Recompute the tag over the descriptor bits ACTUALLY PRESENT in the received
        # image, not over what should be there -- that is what makes the descriptor
        # field tamper-evident. If an attacker altered any of block i's 96 carried
        # descriptor bits, fresh_tag[i] diverges and block i is flagged. Without this
        # binding, 96 of 128 payload bits were unauthenticated and every recovery
        # descriptor in an image could be destroyed at ~40 dB PSNR with zero blocks
        # flagged (see payload.block_tags docstring for the verified exploit).
        fresh_tag = block_tags(bmsb, key_b, iid, (H, W), block, ch, variant, tag_bits,
                               carried_desc=stored_desc)
        per_channel[ch] = (stored_tag != fresh_tag).any(axis=1).astype(np.uint8)
        stored_tags[ch] = stored_tag
        fresh_tags[ch] = fresh_tag
        # DIRECTION CONTRACT: detect.py reads with m, NOT minv -- see module docstring
        # for the full derivation (desc_by_owner = stored_desc[m]).
        desc_by_owner[ch] = stored_desc[m]

    raw = per_channel.any(axis=0).astype(np.uint8).reshape(Rg, Cg)  # channel-OR
    # clear_isolated is threaded through to the pipeline, not just available on
    # refine_mask: adversarial review pointed out the paper claimed "the choice is a
    # parameter rather than a hard-coded assumption" while detect_image had no such
    # parameter, so the published behaviour was unreachable through the real pipeline
    # and the claim was false. It defaults to False for the security reason in
    # refine_mask's docstring; pass True to reproduce the published rule.
    block_mask = (refine_mask(raw, tau, clear_isolated=clear_isolated)
                  if refine else raw.copy())
    pixel_mask = expand_mask(block_mask, block)

    info = {
        "block": block, "variant": variant, "K": K, "shape": (H, W), "crop": crop,
        "map_info": map_info, "channels": C, "image_id": iid, "tau": tau, "refine": refine,
    }
    if raw.mean() > 0.9:
        # A mismatched variant/key/image_id/block between embed and detect produces
        # exactly this signature -- far more likely than a genuine 90% tamper. Four
        # lines here save hours during the ablation sweep and in the demo.
        info["suspect_parameters"] = True
        info["suspect_message"] = (
            ">=90% of blocks failed verification -- far more likely a wrong key / "
            "image ID / block size / variant than a genuine 90% tamper.")

    return DetectResult(raw_mask=raw, block_mask=block_mask, pixel_mask=pixel_mask,
                        desc_by_owner=desc_by_owner, per_channel=per_channel, m=m,
                        stored_tags=stored_tags, fresh_tags=fresh_tags, info=info)


def refine_mask(d: np.ndarray, tau: int = 7, clear_isolated: bool = False) -> np.ndarray:
    """8-neighbour majority pass: fill near-surrounded negatives; optionally clear isolated positives.

    `clear_isolated` DEFAULTS TO FALSE, which is a deliberate, measured departure from
    the published refinement rule. The evidence:

    - The authentication tag is an exact truncated HMAC-SHA256 comparison, so the raw
      indicator has NO false positives to clean. Measured across the full experiment
      grid: n_false_positive_blocks summed to exactly 0 over every null-condition row.
    - The isolated-positive rule therefore cannot remove a false positive. It can only
      ever remove a TRUE positive.
    - It provides no measured benefit: comparing raw against refined metrics over the
      tamper grid gave a delta of 0.00000 on precision, recall, F1, IoU and FPR alike.
      The four tamper classes all produce contiguous regions, where every flagged block
      has flagged neighbours, so the rule never fires usefully.
    - It DOES create a real blind spot. A single-block tamper has S=0 and is cleared,
      so it is missed entirely by the production path. An 8x8 block is ample to alter a
      digit on a cheque, a decimal point, or a small figure in a document -- precisely
      the high-value small tamper. It also silently defeats the tag-transplant attack
      demonstration, where a single block carrying a valid-but-misplaced tag correctly
      fails HMAC verification and was then erased from the reported mask.

    So for an exact keyed comparison the rule is all cost and no benefit, and it is off
    by default. Pass clear_isolated=True to reproduce the published behaviour (the
    ablation in the paper reports both).

    The isolated-NEGATIVE fill is retained: it closes holes inside a tampered region,
    which is a genuine improvement and carries no comparable downside.
    """
    Rg, Cg = d.shape
    p = np.zeros((Rg + 2, Cg + 2), dtype=np.int32); p[1:-1, 1:-1] = d
    v = np.zeros((Rg + 2, Cg + 2), dtype=np.int32); v[1:-1, 1:-1] = 1
    OFF = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1), (2, 2)]  # 8-neighbourhood
    # Zero-padded slice sum, not cv2.filter2D / scipy.ndimage: four lines, no extra
    # dependency, and filter2D gives no control over the constant border value, which
    # is exactly what the valid-neighbour count below needs.
    S = sum(p[dy:dy + Rg, dx:dx + Cg] for dy, dx in OFF)       # neighbours flagged
    nvalid = sum(v[dy:dy + Rg, dx:dx + Cg] for dy, dx in OFF)  # 3 corner, 5 edge, 8 interior
    # This tau/8 scaling is a necessary CORRECTION to the paper, not the paper's own
    # rule: with a fixed tau=7, a corner block has only 3 real neighbours, so S <= 3 <
    # 7 and a corner block could NEVER be filled -- border blocks would be silently
    # exempt from the fill rule. Scaling keeps the rule proportionally identical
    # (tau/8 = 0.875, so a corner needs 3 of 3 and an edge needs 5 of 5).
    thresh = np.ceil(tau * nvalid / 8.0)
    out = d.copy()
    if clear_isolated:                  # off by default -- see the docstring for why
        out[(d == 1) & (S == 0)] = 0    # isolated positive -> clear
    out[(d == 0) & (S >= thresh)] = 1   # near-surrounded negative -> fill
    return out


def expand_mask(block_mask: np.ndarray, block: int) -> np.ndarray:
    """(Rg, Cg) block mask -> (H, W) pixel mask."""
    return np.repeat(np.repeat(block_mask, block, axis=0), block, axis=1)


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

if __name__ == "__main__":
    from embed import _synthetic_natural, embed_image

    KEY = b"detect-selfcheck-key"

    # refine_mask geometry, hand-built on 5x5 masks
    d = np.zeros((5, 5), dtype=np.uint8); d[2, 2] = 1
    # A single-block tamper SURVIVES by default -- the security fix. Passing
    # clear_isolated=True reproduces the published rule, which erases it.
    assert refine_mask(d, 7).sum() == 1                       # isolated positive KEPT (default)
    assert refine_mask(d, 7, clear_isolated=True).sum() == 0   # published rule clears it
    d = np.ones((5, 5), dtype=np.uint8); d[2, 2] = 0
    assert refine_mask(d, 7)[2, 2] == 1                        # surrounded negative filled
    d = np.zeros((5, 5), dtype=np.uint8); d[0:2, 0:2] = 1
    assert refine_mask(d, 7)[:2, :2].sum() == 4                # a 2x2 cluster survives
    d = np.ones((5, 5), dtype=np.uint8); d[0, 0] = 0
    assert refine_mask(d, 7)[0, 0] == 1                        # CORNER negative fills: needs 3 of 3
    assert refine_mask(np.zeros((3, 3), dtype=np.uint8), 7).sum() == 0   # all-clean stays clean
    assert refine_mask(np.ones((3, 3), dtype=np.uint8), 7).sum() == 9    # all-dirty stays dirty
    bm = np.zeros((4, 4), dtype=np.uint8); bm[1, 2] = 1
    pm = expand_mask(bm, 8)
    assert pm.sum() == 64 and pm[8:16, 16:24].all()
    print("detect.py: refine_mask + expand_mask geometry OK")

    # round-trip integration check
    img = _synthetic_natural(128)
    wm, _ = embed_image(img, KEY, b"RT", 8, "A")
    det = detect_image(wm, KEY, b"RT", 8, "A", refine=False)
    assert det.raw_mask.sum() == 0                             # untouched -> nothing flagged
    tam = wm.copy(); tam[32:64, 32:64] = 0                     # block-aligned wipe
    dt = detect_image(tam, KEY, b"RT", 8, "A")
    assert dt.block_mask[4:8, 4:8].all()                       # all 16 tampered blocks flagged
    assert dt.block_mask.sum() == 16                           # and nothing else
    print("detect.py: round-trip tamper check OK")

    # audit(): the per-block explainability record. Branching logic over four decision
    # paths, so it gets a runnable check rather than being trusted.
    a_ok = det.audit(0)
    assert a_ok["tag_matched"] is True and a_ok["decision"] == "AUTHENTIC"
    assert np.array_equal(a_ok["stored_tag"], a_ok["recomputed_tag"])
    flagged_idx = int(np.flatnonzero(dt.block_mask.ravel())[0])
    a_bad = dt.audit(flagged_idx)
    assert a_bad["tag_matched"] is False
    assert a_bad["decision"] in ("RECOVERABLE", "UNRECOVERABLE")
    assert not np.array_equal(a_bad["stored_tag"], a_bad["recomputed_tag"])
    # the partner index reported must agree with the mapping itself
    assert a_bad["partner_block"] == int(dt.m[flagged_idx])
    # UNRECOVERABLE must be reported exactly when the partner is also flagged
    Cg_ = dt.block_mask.shape[1]
    for i in np.flatnonzero(dt.block_mask.ravel())[:40]:
        r = dt.audit(int(i))
        p = int(dt.m[int(i)])
        expect_unrec = bool(dt.block_mask[p // Cg_, p % Cg_])
        assert (r["decision"] == "UNRECOVERABLE") == expect_unrec, r
    print("detect.py: per-block audit record OK")

    print("detect.py self-check OK")
