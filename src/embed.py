"""Embedder: writes tags + mapped recovery descriptors into an image's 2 LSBs/pixel.

detect.py is this module's exact mirror -- see its module docstring for the shared
direction contract (m vs minv). Any change here to bit order, block order, or the
HMAC message must be made in detect.py too, or every block fails verification.
"""

import warnings
from pathlib import Path

import cv2
import numpy as np

import imageio_any
from blockmap import build_map
from metrics import image_metrics
from payload import (bits_to_lsb_pairs, block_tags, budget, coerce_key,
                     crop_to_blocks, encode_descriptor, from_blocks, msb, to_blocks)

PSNR_BOUND = 44.15  # analytical max for full-entropy 2-LSB PLAIN replacement (pre-#27
                    # baseline; see self-check). #27's LSB shifting is specifically
                    # designed to beat this, so a measured psnr above it is now expected,
                    # not a bug signal -- see the shifted self-check bounds below instead.


def _shift_lsb_pairs(orig: np.ndarray, target: np.ndarray) -> np.ndarray:
    """#27 AuSR1-style LSB shifting: the nearest uint8 value carrying `target` in its low
    2 bits, vs. plain replacement's `msb(orig) | target` (always exactly right but always
    IN the same quantization window as `orig`).

    Two candidates only: `in_window` (the historical value: same window as `orig`,
    always valid since msb(orig) <= 252 and target <= 3) and `out_window`, the same low
    bits one window over, in whichever direction that is closer. `out_window` wins only
    when it is STRICTLY closer -- algebraically that is exactly the case where `target`
    and orig's own low bits sit diagonally opposite in the 4-value window
    (|target - r| == 3, also the case plain replacement moves the pixel furthest) --
    AND landing there stays inside [0, 255]. A tie (|target - r| == 2: both directions
    cost 2) and a clamp collision (out_window would leave [0, 255], which only happens
    in the bottom or top quantization window of the whole 0..255 range) both fall back
    to `in_window`: a tie buys nothing by moving, and at the clamp there is nowhere to
    go. This is also why `in_window` needs no bounds check of its own before the
    fallback -- it is always valid, by construction.
    """
    orig = orig.astype(np.int16)
    target = target.astype(np.int16)
    r = orig & 3
    in_window = (orig & 0xFC) | target
    diff = target - r                                # -3..3
    out_window = in_window - 4 * np.sign(diff)        # the other direction, one window over
    d_in = np.abs(diff)
    use_out = (4 - d_in < d_in) & (out_window >= 0) & (out_window <= 255)
    return np.where(use_out, out_window, in_window).astype(np.uint8)


def embed_image(img: np.ndarray, key: bytes | str, image_id: bytes | str,
                block: int = 8, variant: str = "A", d_min: float | None = None,
                ) -> tuple[np.ndarray, dict]:
    """Embed tags + mapped recovery descriptors into the 2 LSBs; return (watermarked, info)."""
    if img.dtype != np.uint8:
        # Do NOT helpfully cast: a float image in 0..1 cast to uint8 becomes a
        # black image, and the psnr assert in the self-check is the only thing
        # that would ever catch that mistake if we let it through silently.
        raise ValueError(f"embed_image requires uint8 input, got dtype {img.dtype}")
    if img.ndim == 3 and img.shape[2] == 1:
        img = img[:, :, 0]
    if img.ndim == 3 and img.shape[2] == 4:
        raise ValueError("4-channel RGBA input is not supported -- drop the alpha "
                          "channel before calling embed_image; watermarking it silently "
                          "produces garbage transparency")
    if img.ndim == 3 and img.shape[2] != 3:
        raise ValueError(f"unsupported channel count {img.shape[2]}")
    greyscale = img.ndim == 2

    key_b = coerce_key(key)
    iid = image_id.encode("utf-8") if isinstance(image_id, str) else image_id

    img, crop = crop_to_blocks(img, block)
    H, W = img.shape[:2]
    cap, tag_bits, desc_bits = budget(block)
    # ONE map, shared by all channels: build_map is called once, outside the channel
    # loop. Binding `channel` into the map would give three different maps, letting a
    # block be recoverable in R but not G -- producing colour-fringed recovered blocks
    # and three separate unrecoverable masks instead of one map / one mask.
    m, minv, map_info = build_map(key_b, iid, (H, W), block, d_min)

    planes = [img] if greyscale else [img[:, :, c] for c in range(3)]
    out = []
    n_clipped = 0
    # #27: tag_pixels is the boundary between the two halves of every block's payload.
    # Pixels [0, tag_pixels) carry the block's own tag; pixels [tag_pixels, B*B) carry
    # the descriptor it holds for its partner (bits_to_lsb_pairs maps bit-pair t to
    # pixel t -- see that function's docstring -- and payload is [tag_bits, desc_bits]
    # concatenated, so this split is exact).
    tag_pixels = tag_bits // 2
    for ch, plane in enumerate(planes):
        raw_blocks = to_blocks(plane, block)     # (K, B, B) untouched original pixels
        bmsb = msb(raw_blocks)                   # (K, B, B), 2 LSBs already zero
        # Descriptor FIRST, then the tag that binds it. Order matters: the tag must
        # cover the descriptor bits this block physically carries, or those 96 of 128
        # payload bits are unauthenticated and an attacker can destroy every recovery
        # descriptor in the image at ~40 dB without tripping a single block. There is
        # no circularity -- the descriptor depends only on bmsb, never on the tag.
        desc, nclip = encode_descriptor(bmsb, variant, desc_bits)
        n_clipped += nclip
        # DIRECTION CONTRACT: embed.py writes with minv, NOT m. Block i carries its own
        # tag plus desc[minv[i]] -- the descriptor of the block whose backup is stored
        # at i (blockmap.py: minv[i] = index of the block whose descriptor is STORED IN
        # block i). detect.py reads the mirror image of this line with m.
        carried = desc[minv]
        carried_pairs = bits_to_lsb_pairs(carried)  # (K, desc_bits/2) values 0..3

        # #27 LSB SHIFTING. block_tags hashes blocks_msb.tobytes() WHOLE (every pixel's
        # own MSB, not just the ones carrying the tag), so if ANY pixel in the block
        # moved into a different quantization window, a clean re-read would recompute a
        # different bmsb than the one the tag was built from and fail its own
        # authentication -- "verifies at embed time, fails on a clean re-read", the
        # exact failure mode to avoid. That rules out shifting the tag-carrying pixels:
        # their target bits ARE the tag, so letting them move would make the hash
        # depend on its own output (compute the tag to know the pixels, compute the
        # pixels to know the tag). The descriptor-carrying pixels have no such problem
        # -- their target bits come from ANOTHER block's descriptor, already fixed --
        # so: shift those first (against the true original pixel value, not bmsb),
        # fold the result into "the MSB this block will actually store", hash THAT, and
        # only then plain-replace the tag pixels on top of it. Since the tag pixels'
        # slice of bmsb_final is untouched by the shift, that plain replace is exactly
        # the historical in-window write and provably cannot move them -- not merely
        # asked not to.
        flat_raw = raw_blocks.reshape(-1, block * block)
        desc_shifted = _shift_lsb_pairs(flat_raw[:, tag_pixels:], carried_pairs)
        bmsb_flat = bmsb.reshape(-1, block * block).copy()
        bmsb_flat[:, tag_pixels:] = desc_shifted & np.uint8(0xFC)
        bmsb_final = bmsb_flat.reshape(bmsb.shape)

        tags = block_tags(bmsb_final, key_b, iid, (H, W), block, ch, variant, tag_bits,
                          carried_desc=carried)
        tag_pairs = bits_to_lsb_pairs(tags)  # (K, tag_pixels) values 0..3
        # No clipping needed anywhere: MSB(x) <= 252 and pair <= 3, so MSB(x) | pair <=
        # 255 always -- true for the tag pixels here exactly as it always was.
        tag_vals = bmsb_flat[:, :tag_pixels] | tag_pairs

        final_flat = np.empty_like(bmsb_flat)
        final_flat[:, :tag_pixels] = tag_vals
        final_flat[:, tag_pixels:] = desc_shifted
        wm_blocks = final_flat.reshape(bmsb.shape)
        out.append(from_blocks(wm_blocks, (H, W), block))

    # Colour: each channel gets its OWN full payload (own tags, own descriptors), not
    # a payload split across channels. Each channel's descriptor then reconstructs its
    # own content, so recovery never needs cross-channel inference, and capacity is 3x
    # for free at no PSNR cost (every channel takes identical 2-LSB distortion).
    # ponytail: upgrade path if recovered PSNR ever needs another 2-3 dB -- watermark
    # luma only and spend the freed 3x capacity on a richer descriptor, at the cost of
    # needing a reversible colour transform.
    wm = out[0] if greyscale else np.stack(out, axis=-1)

    # The keystone property, kept in production, not behind a debug flag -- updated for
    # #27. Plain replacement never moved a pixel's MSB projection at all, so this used
    # to be exact equality. LSB shifting deliberately lets a DESCRIPTOR pixel cross into
    # the immediately adjacent quantization window (see _shift_lsb_pairs); TAG pixels
    # never move (see the per-channel loop above), so the bound is one window (4), not
    # zero. This is only the distortion-magnitude half of the old assertion -- the real
    # keystone check, that a clean re-read authenticates every block, is Assertion 1 in
    # test_e2e.py's test_keystone(), which is exactly what exercises the shift-vs-tag
    # interaction this function relies on.
    assert np.max(np.abs(msb(wm).astype(np.int16) - msb(img).astype(np.int16))) <= 4

    psnr, ssim = image_metrics(img, wm)
    info = {
        "block": block, "variant": variant, "K": map_info["K"], "shape": (H, W),
        "crop": crop, "psnr": psnr, "ssim": ssim, "psnr_bound": PSNR_BOUND,
        "n_clipped": n_clipped, "map_info": map_info,
        "channels": 1 if greyscale else 3, "image_id": iid,
    }
    return wm, info


def load_image(path: str | Path) -> np.ndarray:
    """Read an image as uint8 RGB via imageio_any -- NOT a raw cv2.imread.

    imageio_any normalises every format to (H, W, 3) uint8 RGB, including RGBA: the
    alpha channel is composited over white rather than hitting embed_image's 4-channel
    rejection (see embed_image's docstring for why that rejection itself stays). Any
    caveat imageio_any attaches (alpha composited, format is lossy, ...) is surfaced as
    a warning here since load_image's return type is a plain array with nowhere else to
    put it.
    """
    path = Path(path)
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read image: {path}") from exc
    page = imageio_any.decode(data, filename=path.name)[0]
    if page.note:
        warnings.warn(f"{path}: {page.note}")
    return page.rgb


def save_image(path: str | Path, img: np.ndarray) -> None:
    """Write a lossless image; asserts the extension is one of .png/.bmp/.tif/.tiff."""
    path = Path(path)
    # Load-bearing, not decoration: a single JPEG save destroys every LSB and every
    # result in the paper.
    assert path.suffix.lower() in (".png", ".bmp", ".tif", ".tiff"), (
        f"refusing to save to lossy/unknown extension {path.suffix!r} -- "
        "watermark LSBs would not survive")
    if img.ndim == 3 and img.shape[2] == 3:
        out = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif img.ndim == 3 and img.shape[2] == 4:
        out = cv2.cvtColor(img, cv2.COLOR_RGBA2BGRA)
    else:
        out = img
    ok = cv2.imwrite(str(path), out)
    assert ok, f"cv2.imwrite failed: {path}"


# --------------------------------------------------------------------------
# Self-check
# --------------------------------------------------------------------------

def _synthetic_natural(n: int) -> np.ndarray:
    """Deterministic gradient + sinusoid + noise image: high-entropy low-freq DCT, no corpus."""
    y, x = np.mgrid[0:n, 0:n]
    base = 0.5 * x + 0.5 * y + 40.0 * np.sin(x / 6.0) * np.cos(y / 9.0) + 128.0
    noise = np.random.default_rng(0).normal(0.0, 15.0, size=(n, n))
    return np.clip(base + noise, 0, 255).astype(np.uint8)


if __name__ == "__main__":
    from detect import detect_image  # local: avoids a module-level cycle risk for callers

    KEY = b"embed-selfcheck-key"
    img = _synthetic_natural(128)

    for B in (4, 8):
        for variant in ("A", "B"):
            for I in (img, np.stack([img] * 3, axis=-1)):
                wm, info = embed_image(I, KEY, b"selfcheck", B, variant)
                assert wm.shape == I.shape and wm.dtype == np.uint8
                Ic, _ = crop_to_blocks(I, B)
                # #27: descriptor pixels may cross exactly one quantization window (4),
                # tag pixels never move -- see the assert in embed_image itself for the
                # full rule. The bound that actually matters -- clean re-read verifies --
                # is checked right below via a real detect_image() round trip.
                assert np.max(np.abs(msb(wm).astype(np.int16) - msb(Ic).astype(np.int16))) <= 4
                assert np.max(np.abs(wm.astype(np.int16) - Ic.astype(np.int16))) <= 3
                det = detect_image(wm, KEY, b"selfcheck", B, variant, refine=False)
                assert det.raw_mask.sum() == 0, (
                    f"B={B} variant={variant}: shifted watermark failed to "
                    "self-authenticate on a clean re-read")
                # Upper bound is the valuable half of this assert: a measured value
                # above it means the payload is not full-entropy -- an all-zero
                # descriptor array, a minv indexing mistake producing a constant, or a
                # variant typo falling through. A lower-bound-only assert would pass on
                # all of those. The band is only valid for high-entropy low-frequency
                # DCT content, which is why _synthetic_natural() exists instead of a
                # constant image (a flat image legitimately reaches ~50 dB).
                # #27 REPIN: LSB shifting moved this ceiling up by ~+1.3 dB (was 44.30/
                # 44.70) -- it is now the same distortion-reduction the whole change is
                # FOR, not drift to paper over. Re-measured on this exact fixture (B in
                # {4, 8}, both colour modes) after implementing _shift_lsb_pairs: A
                # ranges 44.950-45.415 dB, B ranges 45.071-45.643 dB -- B still sits
                # above A for the same reason as before (its 2x2-mean descriptor is
                # less than full-entropy by the CLT, on top of the shift gain both
                # variants now get). New ceilings below carry ~0.2-0.3 dB margin over
                # those measured maxima, same style as the old ones.
                hi = 45.60 if variant == "A" else 45.90
                assert 42.0 <= info["psnr"] <= hi, (variant, info["psnr"])
                # SSIM floor is 0.96, calibrated against the REAL corpus, not guessed.
                # Measured across all 32 corpus images x both variants: min 0.97073
                # (splash.tif, variant B, at a healthy 43.92 dB PSNR), mean 0.982/0.984.
                # A 0.99 floor fails 7 of the 8 USC-SIPI images on correct code -- SSIM's
                # structure term is normalized by local variance, so a fixed-variance
                # embedding perturbation dominates on low-variance content. Verified this
                # is not a windowing artifact: skimage's default 7x7 uniform window, the
                # Wang et al. 11x11 Gaussian, and Gaussian-on-luma all agree to ~0.001.
                # 0.96 leaves ~0.011 margin under the real minimum while still catching a
                # genuine regression, which lands far below 0.96, not just under it.
                assert info["ssim"] > 0.96, (variant, info["ssim"])
                assert info["n_clipped"] == 0
                print(f"  B={B} variant={variant} colour={I.ndim == 3}: "
                      f"psnr={info['psnr']:.2f} ssim={info['ssim']:.4f}")

    # dtype / channel-count trust-boundary checks
    try:
        embed_image(np.zeros((16, 16, 4), dtype=np.uint8), KEY, b"x", 8, "A")
        raise SystemExit("expected ValueError for RGBA input")
    except ValueError:
        pass
    try:
        embed_image(np.zeros((16, 16), dtype=np.float32), KEY, b"x", 8, "A")
        raise SystemExit("expected ValueError for non-uint8 input")
    except ValueError:
        pass

    # load_image: RGBA on disk composites to (H, W, 3) RGB over white, with a warning,
    # instead of coming back 4-channel and hitting embed_image's rejection above (#24).
    import tempfile
    from PIL import Image as _Image
    hole = np.full((32, 32, 4), (0, 200, 0, 255), dtype=np.uint8)
    hole[2:6, 2:6] = (0, 0, 200, 0)  # blue, fully transparent
    with tempfile.TemporaryDirectory() as tmp:
        rgba_path = Path(tmp) / "rgba.png"
        _Image.fromarray(hole, mode="RGBA").save(rgba_path)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            loaded = load_image(rgba_path)
        assert loaded.shape == (32, 32, 3), loaded.shape
        assert tuple(loaded[3, 3]) == (255, 255, 255), loaded[3, 3]  # hole -> white
        assert tuple(loaded[0, 0]) == (0, 200, 0)                    # opaque area untouched
        assert any("composited" in str(w.message) for w in caught), "expected alpha-composite warning"
        wm, _ = embed_image(loaded, KEY, b"rgba-selfcheck", 8, "A")  # no longer throws on RGBA files
        assert wm.shape == (32, 32, 3)  # block-aligned already, no cropping needed

    print("embed.py self-check OK")
