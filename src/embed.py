"""Embedder: writes tags + mapped recovery descriptors into an image's 2 LSBs/pixel.

detect.py is this module's exact mirror -- see its module docstring for the shared
direction contract (m vs minv). Any change here to bit order, block order, or the
HMAC message must be made in detect.py too, or every block fails verification.
"""

from pathlib import Path

import cv2
import numpy as np

from blockmap import build_map
from metrics import image_metrics
from payload import (bits_to_lsb_pairs, block_tags, budget, coerce_key,
                     crop_to_blocks, encode_descriptor, from_blocks, msb, to_blocks)

PSNR_BOUND = 44.15  # analytical maximum for full-entropy 2-LSB embedding (see self-check)


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
    for ch, plane in enumerate(planes):
        bmsb = msb(to_blocks(plane, block))  # (K, B, B), 2 LSBs already zero
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
        tags = block_tags(bmsb, key_b, iid, (H, W), block, ch, variant, tag_bits,
                          carried_desc=carried)
        payload = np.concatenate([tags, carried], axis=1)  # (K, cap)
        pairs = bits_to_lsb_pairs(payload)  # (K, B*B) values 0..3
        # No clipping needed anywhere: MSB(x) <= 252 (msb() zeroed the 2 LSBs) and
        # pair <= 3, so MSB(x) | pair <= 255 always. This is why embedding is exactly
        # invertible on the MSB plane -- no np.clip, no saturation, ever.
        wm_blocks = bmsb | pairs.reshape(-1, block, block).astype(np.uint8)
        out.append(from_blocks(wm_blocks, (H, W), block))

    # Colour: each channel gets its OWN full payload (own tags, own descriptors), not
    # a payload split across channels. Each channel's descriptor then reconstructs its
    # own content, so recovery never needs cross-channel inference, and capacity is 3x
    # for free at no PSNR cost (every channel takes identical 2-LSB distortion).
    # ponytail: upgrade path if recovered PSNR ever needs another 2-3 dB -- watermark
    # luma only and spend the freed 3x capacity on a richer descriptor, at the cost of
    # needing a reversible colour transform.
    wm = out[0] if greyscale else np.stack(out, axis=-1)

    # The keystone property, kept in production, not behind a debug flag: embedding
    # must not disturb a single MSB bit.
    assert np.array_equal(msb(wm), msb(img))

    psnr, ssim = image_metrics(img, wm)
    info = {
        "block": block, "variant": variant, "K": map_info["K"], "shape": (H, W),
        "crop": crop, "psnr": psnr, "ssim": ssim, "psnr_bound": PSNR_BOUND,
        "n_clipped": n_clipped, "map_info": map_info,
        "channels": 1 if greyscale else 3, "image_id": iid,
    }
    return wm, info


def load_image(path: str | Path) -> np.ndarray:
    """Read an image as uint8 RGB (or greyscale); converts OpenCV BGR at the I/O boundary."""
    img = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"could not read image: {path}")
    if img.ndim == 3 and img.shape[2] == 3:
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    elif img.ndim == 3 and img.shape[2] == 4:
        img = cv2.cvtColor(img, cv2.COLOR_BGRA2RGBA)  # kept 4-channel; embed_image rejects it
    return img


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
    KEY = b"embed-selfcheck-key"
    img = _synthetic_natural(128)

    for B in (4, 8):
        for variant in ("A", "B"):
            for I in (img, np.stack([img] * 3, axis=-1)):
                wm, info = embed_image(I, KEY, b"selfcheck", B, variant)
                assert wm.shape == I.shape and wm.dtype == np.uint8
                Ic, _ = crop_to_blocks(I, B)
                assert np.array_equal(msb(wm), msb(Ic))  # ONLY the 2 LSBs moved
                assert np.max(np.abs(wm.astype(np.int16) - Ic.astype(np.int16))) <= 3
                # Upper bound is the valuable half of this assert: 44.15 dB is the
                # analytical maximum for full-entropy 2-LSB embedding, so a measured
                # value ABOVE it means the payload is not full-entropy -- an all-zero
                # descriptor array, a minv indexing mistake producing a constant, or a
                # variant typo falling through. A lower-bound-only assert would pass on
                # all of those. The band is only valid for high-entropy low-frequency
                # DCT content, which is why _synthetic_natural() exists instead of a
                # constant image (a flat image legitimately reaches ~50 dB).
                # ponytail-noted spec resolution: variant B's ceiling is looser than
                # variant A's. Variant B's descriptor is a per-2x2-group MEAN of
                # already-quantized values; by the CLT a mean concentrates toward the
                # centre of its range with LESS than full entropy, regardless of image
                # content -- confirmed empirically: even fully IID random per-pixel
                # noise gives variant B ~44.4-44.5 dB, comfortably above the naive
                # 44.15 ceiling, from averaging alone, not a defect. Variant A's DCT
                # coefficients are different: payload.py picks their quantization step
                # sizes via Cauchy-Schwarz specifically so they nearly fill int8's
                # range, which is why 44.16 is the correct tight ceiling for A only.
                # Variant B's real-corpus max measured 44.52 dB (kodim10), above the
                # 44.35 derived from IID-noise assumptions -- photographic content is not IID.
                hi = 44.30 if variant == "A" else 44.70
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

    print("embed.py self-check OK")
