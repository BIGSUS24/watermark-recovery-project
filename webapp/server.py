"""Flask backend for the watermark-recovery web app.

Thin HTTP/JSON layer over the frozen src/ pipeline (embed -> detect -> recover).
No numerics live here -- every number returned to the browser comes straight
from src/, exactly as computed, never re-rounded or re-derived.

# ponytail: SESSION is a single global in-memory dict, no auth, no locking --
# this is a single-user local tool, not a multi-tenant server. Ceiling: exactly
# one concurrent user/tab; a second tab silently shares (and can clobber) the
# first tab's state. Upgrade path: key SESSION by a per-tab id (Flask session
# cookie or a client-generated UUID) if multi-user support is ever needed.

Run:      python webapp/server.py
Serves:   http://127.0.0.1:8765/
"""

import base64
import csv
import io
import sys
import zipfile
from functools import wraps
from pathlib import Path

import cv2
import numpy as np
from flask import Flask, Response, jsonify, request

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
SAMPLES_DIR = ROOT / "samples"
sys.path.insert(0, str(SRC))

import db  # noqa: E402  -- webapp/db.py, the protected-image library

import imageio_any  # noqa: E402  -- decode-side format adapter (any format -> RGB)
from embed import embed_image, load_image  # noqa: E402
from detect import detect_image, expand_mask  # noqa: E402
from recover import recover_image  # noqa: E402
from tamper import apply_tamper, block_mask_from_pixel_mask  # noqa: E402
from metrics import confusion_counts, loc_scores, recovery_metrics  # noqa: E402
from payload import crop_to_blocks, default_image_id, to_blocks  # noqa: E402

app = Flask(__name__, static_folder="static", static_url_path="")
app.config["MAX_CONTENT_LENGTH"] = 32 * 1024 * 1024  # 32MB: generous for one upload

# ---------------------------------------------------------------------------
# Session state -- see module docstring's ponytail note
# ---------------------------------------------------------------------------
SESSION: dict = {}


class ApiError(Exception):
    """A business-logic error with an HTTP status, never a raw traceback."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def require(key: str, message: str):
    """Fetch SESSION[key] or raise a 409 explaining which earlier step is missing."""
    val = SESSION.get(key)
    if val is None:
        raise ApiError(message, 409)
    return val


def guarded(fn):
    """Every route: catch business errors and anything unexpected into clean JSON."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except ApiError as exc:
            return jsonify(error=str(exc)), exc.status
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except Exception as exc:  # noqa: BLE001 -- last resort, never leak a traceback
            app.logger.exception("unhandled error in %s", fn.__name__)
            return jsonify(error=f"internal error: {exc}"), 500
    return wrapper


def _clean(v):
    """Recursively swap NaN/Infinity floats for JSON-safe strings -- JSON has no
    literal for either, and a bare NaN/Infinity token breaks JS's JSON.parse for
    the WHOLE response, not just that one field."""
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return str(v)
    if isinstance(v, dict):
        return {k: _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    return v


def ok(**kw):
    return jsonify({k: _clean(v) for k, v in kw.items()})


# ---------------------------------------------------------------------------
# Image codec helpers
# ---------------------------------------------------------------------------

def encode_png_bytes(rgb: np.ndarray) -> bytes:
    """RGB array -> PNG file bytes. PNG is lossless, so these bytes decode back to
    the exact same array -- which is what lets a downloaded image be re-uploaded
    later and still verify. Any lossy format here would silently destroy the
    watermark before the user ever got the file."""
    ok_, buf = cv2.imencode(".png", rgb[:, :, ::-1])  # RGB -> BGR for cv2, per spec
    if not ok_:
        raise ApiError("failed to encode PNG", 500)
    return buf.tobytes()


def encode_png_data_uri(rgb: np.ndarray) -> str:
    return "data:image/png;base64," + base64.b64encode(encode_png_bytes(rgb)).decode("ascii")


def png_download(data: bytes, filename: str) -> Response:
    return Response(data, mimetype="image/png", headers={
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(len(data)),
    })


def thumbnail(rgb: np.ndarray, longest: int = 240) -> np.ndarray:
    h, w = rgb.shape[:2]
    scale = min(1.0, longest / max(h, w))
    if scale >= 1.0:
        return rgb
    return cv2.resize(rgb, (max(1, int(w * scale)), max(1, int(h * scale))),
                      interpolation=cv2.INTER_AREA)


def b64_to_bytes(data_uri_or_b64: str) -> bytes:
    """Strip an optional data: URI prefix and base64-decode -- shared by every upload path."""
    raw = data_uri_or_b64.split(",", 1)[1] if data_uri_or_b64.startswith("data:") else data_uri_or_b64
    try:
        return base64.b64decode(raw)
    except Exception:
        raise ApiError("upload is not valid base64", 400)


def decode_upload_pages(data_uri_or_b64: str, filename: str = "") -> list:
    """Base64-decode an upload and hand it to imageio_any -- ANY format it supports
    (PNG/JPEG/BMP/TIFF/WEBP/GIF/PDF), never PNG-only. Returns one imageio_any.Page per
    page (more than one only for a multi-page PDF; imageio_any.MAX_PAGES caps that)."""
    data = b64_to_bytes(data_uri_or_b64)
    try:
        return imageio_any.decode(data, filename=filename)
    except ValueError as exc:
        # imageio_any raises plain ValueError for every failure mode (bad/garbage format,
        # decompression-bomb guard, corrupt PDF, missing pypdfium2 -- with a pip-install
        # hint already in the message). `guarded` would 400 a bare ValueError anyway, but
        # wrapping it here keeps every user-facing failure in this file going through
        # ApiError, per the file's convention.
        raise ApiError(str(exc), 400)


def select_page(pages: list, body: dict) -> tuple:
    """Pick the 1-based 'page' field (default 1); validate it against how many pages
    this upload actually has. Returns (page, page_num, pages_available)."""
    n = len(pages)
    try:
        page_num = int(body.get("page") or 1)
    except (TypeError, ValueError):
        raise ApiError("page must be an integer", 400)
    if not (1 <= page_num <= n):
        raise ApiError(f"page must be between 1 and {n} -- this upload has {n} page(s)", 400)
    return pages[page_num - 1], page_num, n


_LOSSY_UPLOAD_EXPLANATION = (
    "{note} The watermark lives entirely in the two least-significant bits (LSBs) of "
    "every pixel; any lossy re-encode -- JPEG, (assumed-lossy) WEBP, GIF's palette "
    "quantization, or a rasterised PDF page -- overwrites those bits with new values. "
    "A file that was ever saved through one of those has permanently lost its watermark: "
    "there is nothing left to verify, no matter what format it is re-saved as afterwards."
)


def reject_lossy_format(raw: bytes) -> None:
    """Verify-path gate on the SNIFFED FORMAT, applied BEFORE any decode is attempted.

    The ordering is load-bearing, not tidiness. A JPEG that is truncated or corrupt
    fails to decode, so with the gate after the decode the user got Pillow's "cannot
    identify image file" -- a decoder's complaint about a symptom -- instead of the one
    thing they need to be told, which is that a JPEG cannot carry this watermark at
    all and no amount of re-saving will bring it back. The format IS the reason for the
    refusal, so the format is what gets checked first.

    PDF deliberately passes through: a PDF is a container, not a codec, and whether a
    given page is lossy is only knowable after extraction -- reject_if_lossy() handles
    that. An unrecognised format also passes through, so that decode can raise the
    better error naming what it actually saw.
    """
    fmt = imageio_any.sniff(raw)
    if fmt == "pdf" or fmt == "unknown" or fmt in imageio_any.LOSSLESS:
        return
    raise ApiError(_LOSSY_UPLOAD_EXPLANATION.format(
        note=f"This file is {fmt.upper()} (detected from its magic bytes, not its "
             f"name)."), 400)


def reject_if_lossy(page) -> None:
    """Verify-path gate: the uploaded pixels must be able to carry the watermark at all.
    `page.lossy` already covers both cases the contract calls out -- jpeg/webp/gif (not
    in imageio_any.LOSSLESS) AND a rasterised PDF page -- so one check handles both."""
    if page.lossy:
        raise ApiError(_LOSSY_UPLOAD_EXPLANATION.format(
            note=page.note or f"{page.fmt} is a lossy source for this purpose."), 400)


# ---------------------------------------------------------------------------
# Small pixel helpers -- UI-only, never part of the measured pipeline
# ---------------------------------------------------------------------------

def amplify_diff(a: np.ndarray, b: np.ndarray, factor: int = 50) -> np.ndarray:
    diff = cv2.absdiff(a, b).astype(np.int16) * factor
    return np.clip(diff, 0, 255).astype(np.uint8)


def overlay_block_mask(img: np.ndarray, block_mask: np.ndarray, block: int,
                        color=(255, 45, 85), alpha: float = 0.62) -> np.ndarray:
    """Saturated, opaque, hard-edged highlight -- never a soft/blurred glow."""
    pixel_mask = expand_mask(block_mask, block).astype(bool)
    return overlay_pixel_mask(img, pixel_mask, color, alpha)


def overlay_pixel_mask(img: np.ndarray, pixel_mask: np.ndarray,
                        color=(255, 45, 85), alpha: float = 0.62) -> np.ndarray:
    mask = np.asarray(pixel_mask, dtype=bool)
    out = img.astype(np.float32).copy()
    tint = np.array(color, dtype=np.float32)
    out[mask] = out[mask] * (1 - alpha) + tint * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def paint_unrecoverable(img: np.ndarray, unrecoverable_block_mask: np.ndarray, block: int
                        ) -> np.ndarray:
    """Solid magenta fill WITH a diagonal hatch -- colour and pattern both carry the
    meaning, per the accessibility rule: never colour alone."""
    out = img.copy()
    pixel_mask = expand_mask(unrecoverable_block_mask, block).astype(bool)
    if not pixel_mask.any():
        return out
    h, w = out.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    hatch = ((xx + yy) % 10) < 3  # seamless diagonal stripes across block boundaries
    magenta = np.array([213, 0, 249], dtype=np.uint8)
    dark = np.array([58, 0, 66], dtype=np.uint8)
    fill = np.where(hatch[..., None], dark, magenta)
    out[pixel_mask] = fill[pixel_mask]
    return out


def rect_noise_tamper(img: np.ndarray, y0: int, x0: int, y1: int, x1: int, seed: int
                      ) -> tuple[np.ndarray, np.ndarray]:
    """Full destructive overwrite of an EXACT caller-given rectangle.

    tamper.py's tamper_noise_corruption has the identical pixel effect but only ever
    at a RANDOM region (by design, for statistical experiments over many trials) --
    this reproduces that same effect at a presenter-chosen exact rectangle instead,
    for the interactive corner/middle/custom-area presets, which need guaranteed
    placement a random-region generator cannot give.
    """
    h, w = img.shape[:2]
    y0, y1 = max(0, min(y0, h)), max(0, min(y1, h))
    x0, x1 = max(0, min(x0, w)), max(0, min(x1, w))
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    if x1 <= x0:
        x1 = min(w, x0 + 1)
    rng = np.random.default_rng(seed)
    out = img.copy()
    shape = out[y0:y1, x0:x1].shape
    out[y0:y1, x0:x1] = rng.integers(0, 256, shape, dtype=np.uint8)
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return out, mask


def preset_rect(h: int, w: int, kind: str, ratio: float) -> tuple[int, int, int, int]:
    size = max(1, int(round((ratio * h * w) ** 0.5)))
    size = min(size, h, w)
    if kind == "corner":
        return 0, 0, size, size
    y0, x0 = max(0, h // 2 - size // 2), max(0, w // 2 - size // 2)
    return y0, x0, min(h, y0 + size), min(w, x0 + size)


def scatter_damage(img: np.ndarray, image_id_str: str, ratio: float, seed: int = 2026
                   ) -> tuple[np.ndarray, np.ndarray, float]:
    """'Scatter damage' = a real tamper.py 'noise' overwrite at a random-but-
    deterministic location (unlike the corner/middle presets, scatter is not meant
    to be pinned anywhere in particular) -- genuinely exercises the frozen module."""
    r = apply_tamper(img, "noise", ratio, image_id_str, base_seed=seed)
    return r["tampered_image"], r["gt_mask_px"], r["achieved_ratio"]


def audit_json(rec: dict) -> dict:
    out = dict(rec)
    for k in ("stored_tag", "recomputed_tag"):
        out[k] = bytes(np.packbits(out[k])).hex()
    return out


def load_manifest() -> list[dict]:
    with open(SAMPLES_DIR / "manifest.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_block_variant(body: dict) -> tuple[int, str]:
    """Shared block/variant parsing + validation for /api/protect and /api/protect/all.

    Root-caused here once rather than duplicated per route: variant C is a block=8-only
    descriptor (src/payload.py's C_DESC_BITS table only exists at that width), so a
    request combining C with block=4 must be rejected explicitly and loudly -- never
    silently coerced to a different block or a different variant.
    """
    block = int(body.get("block", 8))
    if block not in (4, 8):
        raise ApiError("block size must be 4 or 8", 400)
    variant = body.get("variant") or "C"
    if variant not in ("A", "B", "C"):
        raise ApiError("variant must be 'A', 'B', or 'C'", 400)
    if variant == "C" and block != 8:
        raise ApiError(
            "variant C requires block size 8 (it is a rate-distortion-optimized DCT "
            "descriptor defined only at that width) -- pick block 8, or use variant "
            "'A' or 'B' for other block sizes.", 400)
    return block, variant


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/api/samples")
@guarded
def api_samples():
    # Only offer samples whose file is actually on disk. manifest.csv is committed to
    # the repository but the 21 MB of third-party corpus images are not, so on a fresh
    # clone this listed 32 photographs that did not exist -- and the very first thing a
    # new user does (leave "Sample image" selected, press Protect) failed with a raw
    # filesystem path. Reporting an empty list plus a hint is the honest answer.
    rows = load_manifest()
    samples, missing = [], 0
    for r in rows:
        if not (SAMPLES_DIR / r["relpath"]).exists():
            missing += 1
            continue
        samples.append(
            {"dataset": r["dataset"], "filename": r["filename"], "relpath": r["relpath"],
             "width": int(r["width"]), "height": int(r["height"])})
    resp = {"samples": samples, "missing": missing, "total": len(rows)}
    if not samples:
        resp["hint"] = ("The sample corpus has not been downloaded yet. Run "
                        "'python samples/fetch_corpus.py' to fetch it, or just upload "
                        "your own PNG instead -- everything works either way.")
    elif missing:
        resp["hint"] = (f"{missing} of {len(rows)} corpus images are missing from disk; "
                        "run 'python samples/fetch_corpus.py' to complete the set.")
    return ok(**resp)


@app.route("/api/protect", methods=["POST"])
@guarded
def api_protect():
    body = request.get_json(force=True, silent=True) or {}
    key = (body.get("key") or "").strip() or "watermark-secret"
    block, variant = parse_block_variant(body)

    upload_b64 = body.get("upload_b64")
    sample = body.get("sample")
    source_note = ""
    page_num, pages_available = 1, 1
    if upload_b64:
        filename = body.get("filename") or "upload"
        pages = decode_upload_pages(upload_b64, filename=filename)
        page, page_num, pages_available = select_page(pages, body)
        # Never reject a protect upload for being lossy: the source pixels only need to
        # be decodeable, because the protected output is always a fresh PNG, applied to
        # whatever pixels came out of imageio_any -- lossy in is fine, the watermark goes
        # on losslessly either way. `note` (e.g. "JPEG re-encodes pixels lossily...") is
        # surfaced as source_note purely so the UI can tell the user what they started from.
        rgb, stem, source_note = page.rgb, page.name, page.note
    elif sample:
        match = next((r for r in load_manifest() if r["relpath"] == sample), None)
        if match is None:
            raise ApiError(f"unknown sample {sample!r}", 400)
        rgb = load_image(SAMPLES_DIR / match["relpath"])
        stem = Path(match["filename"]).stem
    else:
        raise ApiError("provide either 'sample' or 'upload_b64'", 400)

    cropped_original, _ = crop_to_blocks(rgb, block)
    image_id_str = (body.get("image_id") or "").strip()
    image_id = (image_id_str.encode("utf-8") if image_id_str
                else default_image_id(stem, cropped_original.shape, block))

    try:
        wm, info = embed_image(rgb, key, image_id, block, variant)
    except ValueError as exc:
        # The only ValueError embed_image can raise here (dtype/channel-count are
        # already guaranteed by imageio_any.decode/load_image above) is build_map's
        # "K<3 blocks" case -- see blockmap.py's docstring.
        raise ApiError(
            f"This image is too small for block size {block}: the recovery-descriptor "
            "map needs at least 3 blocks -- use an image of at least 24x24 pixels at "
            f"block=8 (12x12 at block=4), or switch block size. ({exc})", 400)

    wm_png = encode_png_bytes(wm)
    con = db.connect()
    try:
        record_id = db.insert(
            con, name=f"{stem}.png", height=wm.shape[0], width=wm.shape[1],
            block=block, variant=variant, key=key, image_id=image_id, png=wm_png,
            psnr=info["psnr"], ssim=info["ssim"], blocks=info["K"])
        library_size = db.count(con)
    finally:
        con.close()

    SESSION.clear()
    SESSION.update(original=cropped_original, watermarked=wm, key=key, image_id=image_id,
                   block=block, variant=variant, embed_info=info,
                   record_id=record_id, name=f"{stem}.png")

    return ok(
        original=encode_png_data_uri(cropped_original),
        watermarked=encode_png_data_uri(wm),
        diff=encode_png_data_uri(amplify_diff(cropped_original, wm)),
        psnr=info["psnr"], ssim=info["ssim"], blocks=info["K"],
        block=block, variant=variant, image_id=image_id.decode("utf-8", "replace"),
        width=int(wm.shape[1]), height=int(wm.shape[0]),
        record_id=record_id, name=f"{stem}.png", library_size=library_size,
        sha256=db.sha256_hex(wm_png), bytes=len(wm_png),
        source_note=source_note, pages_available=pages_available, page=page_num,
    )


@app.route("/api/protect/all", methods=["POST"])
@guarded
def api_protect_all():
    """Protect EVERY page of one upload in one shot (the multi-page-PDF case) -- each
    page becomes its own library record, and all of them download together as a zip.

    SESSION still holds only the single-image model (see module docstring): it is left
    pointing at the LAST page protected, purely so the existing single-image UI has
    something coherent to show after this runs, not as a real multi-page session.
    """
    body = request.get_json(force=True, silent=True) or {}
    key = (body.get("key") or "").strip() or "watermark-secret"
    block, variant = parse_block_variant(body)

    upload_b64 = body.get("upload_b64")
    if not upload_b64:
        raise ApiError("provide 'upload_b64' -- protect/all works on an uploaded file's "
                       "every page", 400)
    filename = body.get("filename") or "upload"
    base_stem = Path(filename).stem
    # imageio_any.decode() already caps a multi-page PDF at imageio_any.MAX_PAGES pages
    # -- nothing further to enforce here.
    pages = decode_upload_pages(upload_b64, filename=filename)
    image_id_str = (body.get("image_id") or "").strip()

    results = []
    protected_pngs: dict[str, bytes] = {}
    con = db.connect()
    try:
        for i, page in enumerate(pages, start=1):
            name = f"{base_stem} p{i}"
            cropped_original, _ = crop_to_blocks(page.rgb, block)
            image_id = (image_id_str.encode("utf-8") if image_id_str
                       else default_image_id(name, cropped_original.shape, block))
            try:
                wm, info = embed_image(page.rgb, key, image_id, block, variant)
            except ValueError as exc:
                raise ApiError(
                    f"page {i} ('{name}') is too small for block size {block}: the "
                    "recovery-descriptor map needs at least 3 blocks -- use an image of "
                    "at least 24x24 pixels at block=8 (12x12 at block=4), or switch "
                    f"block size. ({exc})", 400)

            wm_png = encode_png_bytes(wm)
            record_id = db.insert(
                con, name=name, height=wm.shape[0], width=wm.shape[1],
                block=block, variant=variant, key=key, image_id=image_id, png=wm_png,
                psnr=info["psnr"], ssim=info["ssim"], blocks=info["K"])
            protected_pngs[name] = wm_png
            results.append(dict(
                record_id=record_id, name=name, psnr=info["psnr"], ssim=info["ssim"],
                blocks=info["K"], thumb=encode_png_data_uri(thumbnail(wm))))

            SESSION.clear()
            SESSION.update(original=cropped_original, watermarked=wm, key=key,
                           image_id=image_id, block=block, variant=variant,
                           embed_info=info, record_id=record_id, name=name)
        library_size = db.count(con)
    finally:
        con.close()

    if not results:
        raise ApiError("upload decoded to zero pages", 400)  # imageio_any never returns this

    SESSION["protect_all_pngs"] = protected_pngs
    SESSION["protect_all_stem"] = base_stem
    return ok(results=results, count=len(results), library_size=library_size)


@app.route("/api/protect/all/download")
@guarded
def api_protect_all_download():
    pngs = SESSION.get("protect_all_pngs")
    if not pngs:
        raise ApiError("there is nothing to download yet -- run /api/protect/all first", 409)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, png_bytes in pngs.items():
            zf.writestr(f"{name}.png", png_bytes)
    data = buf.getvalue()
    stem = SESSION.get("protect_all_stem") or "protected"
    return Response(data, mimetype="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{stem}_pages.zip"',
        "Content-Length": str(len(data)),
    })


@app.route("/api/damage", methods=["POST"])
@guarded
def api_damage():
    wm = require("watermarked", "Protect an image first (Step 1).")
    block = SESSION["block"]
    body = request.get_json(force=True, silent=True) or {}
    h, w = wm.shape[:2]

    if body.get("rect"):
        y0, x0, y1, x1 = (int(v) for v in body["rect"])
        tampered, mask = rect_noise_tamper(wm, y0, x0, y1, x1, seed=99)
        kind = "exact"
    else:
        kind = body.get("kind", "corner")
        ratio = min(max(float(body.get("ratio", 0.15)), 0.01), 0.6)
        if kind in ("corner", "middle"):
            y0, x0, y1, x1 = preset_rect(h, w, kind, ratio)
            tampered, mask = rect_noise_tamper(wm, y0, x0, y1, x1, seed=11 if kind == "corner" else 22)
        elif kind == "scatter":
            image_id_str = SESSION["image_id"].decode("utf-8", "replace")
            tampered, mask, _ = scatter_damage(wm, image_id_str, ratio)
            ys, xs = np.nonzero(mask)
            y0, x0 = (int(ys.min()), int(xs.min())) if ys.size else (0, 0)
            y1, x1 = (int(ys.max()) + 1, int(xs.max()) + 1) if ys.size else (0, 0)
        else:
            raise ApiError("kind must be 'corner', 'middle', or 'scatter' -- or send 'rect'", 400)

    mask = np.asarray(mask, dtype=bool)
    achieved_ratio = float(mask.sum() / mask.size)
    SESSION.update(tampered=tampered, gt_mask_px=mask, det=None, rec=None)
    return ok(tampered=encode_png_data_uri(tampered), achieved_ratio=achieved_ratio,
              kind=kind, rect=[y0, x0, y1, x1])


@app.route("/api/check", methods=["POST"])
@guarded
def api_check():
    tampered = require("tampered", "Damage the image first (Step 2).")
    key, image_id = SESSION["key"], SESSION["image_id"]
    block, variant = SESSION["block"], SESSION["variant"]
    body = request.get_json(force=True, silent=True) or {}
    tau = int(body.get("tau", 7))
    refine = bool(body.get("refine", True))

    det = detect_image(tampered, key, image_id, block, variant, tau=tau, refine=refine)
    SESSION["det"] = det

    gt_mask_px = SESSION.get("gt_mask_px")
    gt_block = (block_mask_from_pixel_mask(gt_mask_px, block) if gt_mask_px is not None
                else np.zeros_like(det.block_mask, dtype=bool))
    tp, fp, fn, tn = confusion_counts(det.block_mask, gt_block)
    loc = loc_scores(tp, fp, fn, tn)

    resp = dict(
        verdict="TAMPERED" if det.block_mask.sum() > 0 else "AUTHENTIC",
        flagged_blocks=int(det.block_mask.sum()), total_blocks=int(det.info["K"]),
        precision=loc["precision"], recall=loc["recall"], f1=loc["f1"], iou=loc["iou"],
        raw_overlay=encode_png_data_uri(overlay_block_mask(tampered, det.raw_mask, block)),
        refined_overlay=encode_png_data_uri(overlay_block_mask(tampered, det.block_mask, block)),
        pixel_overlay=encode_png_data_uri(overlay_pixel_mask(tampered, det.pixel_mask)),
        tau=tau, refine=refine,
    )
    if det.info.get("suspect_message"):
        resp["suspect_message"] = det.info["suspect_message"]
    return ok(**resp)


@app.route("/api/repair", methods=["POST"])
@guarded
def api_repair():
    det = require("det", "Check the image first (Step 3).")
    tampered, wm = SESSION["tampered"], SESSION["watermarked"]
    block, variant = SESSION["block"], SESSION["variant"]

    rec = recover_image(tampered, det, block, variant)
    SESSION["rec"] = rec
    SESSION["repaired_image"] = rec.image  # makes /api/download/repaired available

    unrec_px = expand_mask(rec.unrecoverable_mask, block)
    gt_mask_px = SESSION.get("gt_mask_px")
    if gt_mask_px is None:
        gt_mask_px = expand_mask(det.block_mask, block).astype(bool)
    rm = recovery_metrics(wm, rec.image, gt_mask_px, unrec_px)

    return ok(
        repaired=encode_png_data_uri(rec.image),
        overlay=encode_png_data_uri(paint_unrecoverable(rec.image, rec.unrecoverable_mask, block)),
        rho=rec.rho, counts=rec.counts,
        psnr_in_region=rm["psnr_in_region"], ssim_in_region=rm["ssim_in_region"],
        psnr_whole=rm["psnr_whole"], ssim_whole=rm["ssim_whole"],
    )


@app.route("/api/attack/transplant", methods=["POST"])
@guarded
def api_attack_transplant():
    wm = require("watermarked", "Protect an image first (Step 1).")
    key, image_id = SESSION["key"], SESSION["image_id"]
    block, variant = SESSION["block"], SESSION["variant"]
    h, w = wm.shape[:2]
    rg, cg = h // block, w // block
    body = request.get_json(force=True, silent=True) or {}
    dst_idx = max(0, min(int(body.get("block_index", (rg // 2) * cg + cg // 2)), rg * cg - 1))

    blocks = to_blocks(wm[:, :, 0], block)
    means = blocks.astype(np.float64).mean(axis=(1, 2))
    diffs = np.abs(means - means[dst_idx])
    diffs[dst_idx] = np.inf
    src_idx = int(np.argmin(diffs))

    dr, dc = divmod(dst_idx, cg)
    sr, sc = divmod(src_idx, cg)
    transplanted = wm.copy()
    transplanted[dr * block:(dr + 1) * block, dc * block:(dc + 1) * block] = \
        wm[sr * block:(sr + 1) * block, sc * block:(sc + 1) * block]

    det = detect_image(transplanted, key, image_id, block, variant)
    flagged_raw = bool(det.raw_mask[dr, dc])
    flagged_after = bool(det.block_mask[dr, dc])

    if flagged_raw:
        explanation = (
            f"Block #{dst_idx} now holds pixels physically copied from block #{src_idx} of "
            "this same watermarked image -- every byte in it carries a genuinely valid "
            "signature. Detection still fired because that signature is bound to the "
            "image's identity AND the block's own position, not to content alone: a tag "
            "copied to a new position is a tag FOR THE WRONG POSITION, and recomputing the "
            "expected tag there fails. This is what defeats the classic block-collage "
            "counterfeiting attack.")
    else:
        explanation = ("Detection did not fire -- the source and destination blocks were "
                        "already too similar at this position. Pick a different target block.")

    return ok(
        watermarked=encode_png_data_uri(wm), transplanted=encode_png_data_uri(transplanted),
        source_block=src_idx, dest_block=dst_idx,
        detection_fired=flagged_raw, survives_refinement=flagged_after,
        explanation=explanation, audit=audit_json(det.audit(dst_idx)),
    )


@app.route("/api/attack/coincidence", methods=["POST"])
@guarded
def api_attack_coincidence():
    wm = require("watermarked", "Protect an image first (Step 1).")
    key, image_id = SESSION["key"], SESSION["image_id"]
    block, variant = SESSION["block"], SESSION["variant"]
    h, w = wm.shape[:2]
    rg, cg = h // block, w // block
    body = request.get_json(force=True, silent=True) or {}
    idx = max(0, min(int(body.get("block_index", (rg // 2) * cg + cg // 2)), rg * cg - 1))

    det0 = detect_image(wm, key, image_id, block, variant)  # clean detect, just to read the map
    partner = int(det0.m[idx])

    rng = np.random.default_rng(77)
    forced = wm.copy()
    for i in (idx, partner):
        r, c = divmod(i, cg)
        y0, x0 = r * block, c * block
        shape = forced[y0:y0 + block, x0:x0 + block].shape
        forced[y0:y0 + block, x0:x0 + block] = rng.integers(0, 256, shape, dtype=np.uint8)

    # refine=False: this deliberately tampers an exact, isolated pair of far-apart single
    # blocks to test the recovery-honesty guarantee precisely, independent of the
    # majority-vote smoothing heuristic meant for realistic contiguous damage.
    det_f = detect_image(forced, key, image_id, block, variant, refine=False)
    rec_f = recover_image(forced, det_f, block, variant)
    unrecoverable = bool(rec_f.unrecoverable_mask.sum() > 0)

    if unrecoverable:
        explanation = (
            f"Block #{idx} was destroyed, and so was block #{partner} -- the ONE other "
            f"block that held block #{idx}'s recovery backup. With no intact copy anywhere, "
            "the system reports UNRECOVERABLE rather than inventing plausible-looking pixels.")
    else:
        explanation = ("Both target blocks were damaged, but recovery still found a way "
                        "through -- try a different block index.")

    return ok(
        tampered=encode_png_data_uri(forced),
        repaired_overlay=encode_png_data_uri(paint_unrecoverable(rec_f.image, rec_f.unrecoverable_mask, block)),
        block_index=idx, partner_index=partner,
        unrecoverable=unrecoverable, rho=rec_f.rho, counts=rec_f.counts,
        explanation=explanation,
    )


@app.route("/api/audit/<int:block>")
@guarded
def api_audit(block):
    # Per-block evidence needs a detection to report on, but requiring the user to
    # have run one first made the panel dead on arrival in the attack lab (protecting
    # an image clears any earlier detection). Running one here on whatever image is
    # current is the same detection they would have got, so refusing to do it added
    # nothing but a dead end.
    det = SESSION.get("det")
    if det is None:
        img = (SESSION["tampered"] if SESSION.get("tampered") is not None
               else SESSION.get("watermarked"))
        if img is None:
            raise ApiError("Protect or verify an image first -- there is no image to audit yet.",
                           409)
        det = detect_image(img, SESSION["key"], SESSION["image_id"], SESSION["block"],
                           SESSION["variant"])
        SESSION["det"] = det
    channel = int(request.args.get("channel", 0))
    K, channels = int(det.info["K"]), int(det.info["channels"])
    if not (0 <= block < K):
        raise ApiError(f"block index must be between 0 and {K - 1}", 400)
    if not (0 <= channel < channels):
        raise ApiError(f"channel must be between 0 and {channels - 1}", 400)
    return ok(**audit_json(det.audit(block, channel)))


# ---------------------------------------------------------------------------
# Library: the database of protected images, and downloads
# ---------------------------------------------------------------------------

@app.route("/api/library")
@guarded
def api_library():
    con = db.connect()
    try:
        return ok(records=db.list_all(con))
    finally:
        con.close()


@app.route("/api/library/<int:rid>/download")
@guarded
def api_library_download(rid):
    con = db.connect()
    try:
        row = db.get(con, rid)
        if row is None:
            raise ApiError(f"no protected image with id {rid}", 404)
        stem = Path(row["name"]).stem
        return png_download(bytes(row["png"]), f"{stem}_protected.png")
    finally:
        con.close()


@app.route("/api/library/<int:rid>/thumb")
@guarded
def api_library_thumb(rid):
    con = db.connect()
    try:
        row = db.get(con, rid)
        if row is None:
            raise ApiError(f"no protected image with id {rid}", 404)
        rgb = decode_png_bytes(bytes(row["png"]))
        return Response(encode_png_bytes(thumbnail(rgb)), mimetype="image/png",
                        headers={"Cache-Control": "no-store"})
    finally:
        con.close()


@app.route("/api/library/<int:rid>", methods=["DELETE"])
@guarded
def api_library_delete(rid):
    con = db.connect()
    try:
        if not db.delete(con, rid):
            raise ApiError(f"no protected image with id {rid}", 404)
        return ok(deleted=rid, library_size=db.count(con))
    finally:
        con.close()


# Which in-memory image each /api/download/<what> name refers to, and the suffix
# its filename gets. Keeping it as a table means adding a downloadable artefact is
# one line, and an unknown name can never fall through to something unintended.
_DOWNLOADABLE = {
    "protected": ("watermarked", "protected"),
    "damaged": ("tampered", "damaged"),
    "repaired": ("repaired_image", "repaired"),
    "restored": ("restored_image", "restored"),
}


@app.route("/api/download/<what>")
@guarded
def api_download(what):
    if what not in _DOWNLOADABLE:
        raise ApiError(f"nothing downloadable is called {what!r}", 404)
    session_key, suffix = _DOWNLOADABLE[what]
    img = SESSION.get(session_key)
    if img is None:
        raise ApiError(f"there is no {what} image yet -- run that step first", 409)
    stem = Path(SESSION.get("name") or "image").stem
    return png_download(encode_png_bytes(img), f"{stem}_{suffix}.png")


# ---------------------------------------------------------------------------
# Verify an uploaded file against the library
# ---------------------------------------------------------------------------

# How identification decides. A block "verifies" only when all three of its channel
# tags reproduce, so under the WRONG key or wrong image identity a block verifies
# with probability 2^-96; across a 4096-block image the expected number of
# accidentally-verifying blocks is about 5e-26. Under the RIGHT record, every block
# the tamper did not touch verifies. So the question is not "what fraction failed"
# but "did anything verify at all", and a handful of verifying blocks is already
# overwhelming evidence.
#
# This replaces an earlier flag-rate cutoff (accept if under 95% of blocks failed),
# which was worse in both directions: it rejected a 95.3%-destroyed image that had
# 192 blocks still verifying -- proof beyond any doubt of which record it was --
# while resting on a threshold with no principled value behind it. The rule below
# is both stricter against false matches and far more tolerant of real damage.
#
# The honest limit remains: an image with NO surviving watermarked block cannot be
# identified, because there is nothing left to identify it by.
IDENT_MIN_VERIFYING_BLOCKS = 8


def decode_png_bytes(data: bytes) -> np.ndarray:
    bgr = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise ApiError("stored PNG could not be decoded", 500)
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)


def identify(rgb: np.ndarray, con) -> dict:
    """Find which library record an uploaded image is, by keyed verification.

    No perceptual hashing, no filename matching, no metadata: the only evidence
    used is whether the record's key and image identity actually verify against
    these pixels. That means identification cannot be fooled by renaming a file,
    and it inherits the watermark's own security argument.
    """
    h, w = rgb.shape[:2]
    rows = db.candidates_for_shape(con, h, w)
    if not rows:
        raise ApiError(
            f"No protected image in the library is {w}x{h} pixels, so this file cannot "
            "be one of them. Protect an image first, download it, and upload that file "
            "(or a tampered copy of it) here.", 404)

    tried = []
    best = None
    for row in rows:
        block = int(row["block"])
        if h % block or w % block:
            continue  # geometry cannot line up; a verification here is meaningless
        det = detect_image(rgb, row["key"], bytes(row["image_id"]), block, row["variant"],
                           refine=False)
        total = int(det.raw_mask.size)
        verifying = total - int(det.raw_mask.sum())
        rate = float(det.raw_mask.sum() / total)
        tried.append({"id": int(row["id"]), "name": row["name"], "flag_rate": rate,
                      "verifying_blocks": verifying, "total_blocks": total})
        if best is None or verifying > best[1]:
            best = (row, verifying, rate)

    if best is None:
        raise ApiError("no library record has a block geometry compatible with this image", 404)

    row, verifying, rate = best
    tried.sort(key=lambda t: -t["verifying_blocks"])
    runner_up = tried[1] if len(tried) > 1 else None
    if verifying < IDENT_MIN_VERIFYING_BLOCKS:
        raise ApiError(
            f"This file matches no protected image in the library. The closest record "
            f"(\"{row['name']}\") has only {verifying} block(s) that still verify, below the "
            f"{IDENT_MIN_VERIFYING_BLOCKS} needed to identify a file with confidence -- which is "
            "what a wrong key, a different image, or a totally overwritten one looks like. "
            "Either this image was never protected by this app, or it was resized, cropped, or "
            "re-encoded (JPEG/WEBP) somewhere along the way, any of which destroys a fragile "
            "watermark by design.", 404)
    return {"row": row, "flag_rate": rate, "verifying_blocks": verifying,
            "runner_up": runner_up, "candidates_tried": tried}


def truth_compare(stored: np.ndarray, uploaded: np.ndarray, block: int) -> dict:
    """Ground truth: where the uploaded file actually differs from the stored copy.

    This is the honest scoring reference and NOTHING more -- detection never sees it.
    It exists so the localization claim can be checked against the real answer
    instead of being taken on trust.
    """
    changed_px = np.any(stored != uploaded, axis=2) if stored.ndim == 3 else (stored != uploaded)
    changed_px = np.asarray(changed_px, dtype=bool)
    return {
        "pixel_mask": changed_px,
        "block_mask": block_mask_from_pixel_mask(changed_px, block),
        "changed_pixels": int(changed_px.sum()),
        "total_pixels": int(changed_px.size),
        "changed_ratio": float(changed_px.sum() / changed_px.size),
    }


@app.route("/api/verify", methods=["POST"])
@guarded
def api_verify():
    body = request.get_json(force=True, silent=True) or {}
    upload_b64 = body.get("upload_b64")
    if not upload_b64:
        raise ApiError("upload a file to verify", 400)
    raw = b64_to_bytes(upload_b64)
    filename = body.get("filename") or "upload.png"
    reject_lossy_format(raw)      # before decode -- see the docstring for why
    pages = decode_upload_pages(upload_b64, filename=filename)
    page, page_num, pages_available = select_page(pages, body)
    # The uploaded pixels must be ABLE to carry the watermark. jpeg/webp/gif (not in
    # imageio_any.LOSSLESS) and a rasterised PDF page are both `lossy=True` -- reject
    # before wasting a detection pass on pixels that can never verify.
    reject_if_lossy(page)
    uploaded = page.rgb

    con = db.connect()
    try:
        digest = db.sha256_hex(raw)
        exact = db.by_sha(con, digest)
        match = identify(uploaded, con)
        row = match["row"]
        block, variant = int(row["block"]), row["variant"]
        key, image_id = row["key"], bytes(row["image_id"])
        stored = decode_png_bytes(bytes(row["png"]))
        meta = db.row_meta(row)
    finally:
        con.close()

    # Byte-identical means the file was never touched at all -- a strictly stronger
    # statement than "the watermark verifies", and free to check, so report both.
    byte_identical = exact is not None and int(exact["id"]) == int(row["id"])

    tau = int(body.get("tau", 7))
    det = detect_image(uploaded, key, image_id, block, variant, tau=tau, refine=True)
    truth = truth_compare(stored, uploaded, block)
    tp, fp, fn, tn = confusion_counts(det.block_mask, truth["block_mask"])
    loc = loc_scores(tp, fp, fn, tn)

    SESSION.clear()
    SESSION.update(watermarked=stored, tampered=uploaded, original=stored, key=key,
                   image_id=image_id, block=block, variant=variant, det=det,
                   record_id=int(row["id"]), name=Path(filename).name,
                   gt_mask_px=truth["pixel_mask"])

    flagged = int(det.block_mask.sum())
    resp = dict(
        verdict="TAMPERED" if flagged > 0 else "AUTHENTIC",
        matched=meta, byte_identical=byte_identical,
        uploaded_sha256=digest, stored_sha256=row["sha256"],
        identification=dict(
            flag_rate=match["flag_rate"], verifying_blocks=match["verifying_blocks"],
            runner_up=match["runner_up"], candidates_tried=match["candidates_tried"],
            min_verifying_blocks=IDENT_MIN_VERIFYING_BLOCKS),
        flagged_blocks=flagged, total_blocks=int(det.info["K"]),
        changed_pixels=truth["changed_pixels"], total_pixels=truth["total_pixels"],
        changed_ratio=truth["changed_ratio"],
        precision=loc["precision"], recall=loc["recall"], f1=loc["f1"], iou=loc["iou"],
        uploaded_image=encode_png_data_uri(uploaded),
        stored_image=encode_png_data_uri(stored),
        detected_overlay=encode_png_data_uri(overlay_block_mask(uploaded, det.block_mask, block)),
        truth_overlay=encode_png_data_uri(
            overlay_pixel_mask(uploaded, truth["pixel_mask"], color=(0, 200, 120))),
        diff=encode_png_data_uri(amplify_diff(stored, uploaded)),
        repairable=flagged > 0,
        pages_available=pages_available, page=page_num,
    )
    if det.info.get("suspect_message"):
        resp["suspect_message"] = det.info["suspect_message"]
    return ok(**resp)


@app.route("/api/verify/repair", methods=["POST"])
@guarded
def api_verify_repair():
    det = require("det", "Verify an uploaded image first.")
    uploaded = require("tampered", "Verify an uploaded image first.")
    stored, block, variant = SESSION["watermarked"], SESSION["block"], SESSION["variant"]

    rec = recover_image(uploaded, det, block, variant)
    SESSION["rec"] = rec
    SESSION["repaired_image"] = rec.image

    unrec_px = expand_mask(rec.unrecoverable_mask, block)
    gt_mask_px = SESSION.get("gt_mask_px")
    if gt_mask_px is None:
        gt_mask_px = expand_mask(det.block_mask, block).astype(bool)
    # Reference is the stored protected copy -- the genuine article, straight from the
    # library. These numbers are measured against what the file really was, not
    # against the damaged upload.
    rm = recovery_metrics(stored, rec.image, gt_mask_px, unrec_px)

    return ok(
        repaired=encode_png_data_uri(rec.image),
        overlay=encode_png_data_uri(paint_unrecoverable(rec.image, rec.unrecoverable_mask, block)),
        rho=rec.rho, counts=rec.counts,
        psnr_in_region=rm["psnr_in_region"], ssim_in_region=rm["ssim_in_region"],
        psnr_whole=rm["psnr_whole"], ssim_whole=rm["ssim_whole"],
        record_id=SESSION.get("record_id"),
    )


@app.route("/api/verify/restore", methods=["POST"])
@guarded
def api_verify_restore():
    """Exact library-backed restore -- a sibling of /api/verify/repair, not a
    replacement. Requires the same session state /api/verify/repair does (a prior
    /api/verify that identified a library record); both stay available.

    The reasoning, which is why this is safe to do with a straight pixel copy instead
    of any reconstruction: a block only "passes" verification because its 32-bit tag
    (an HMAC over that block's 6 MSB planes AND the 96 descriptor bits it carries) was
    recomputed and matched. Those 512 bits are exactly what an 8x8 block holds, so a
    passing block is provably bit-identical to the archive copy already -- nothing
    about it is uncertain. The DETECTED (never ground-truth) mask below is therefore
    exactly the set of pixels that still need copying from the archive; copying just
    those must reproduce the archive file exactly, which is the one fact this endpoint
    checks on every call rather than assuming.
    """
    det = require("det", "Verify an uploaded image first.")
    uploaded = require("tampered", "Verify an uploaded image first.")
    stored = SESSION["watermarked"]

    mask = np.asarray(det.pixel_mask, dtype=bool)  # DETECTED mask -- never ground truth
    pixels_changed = int(np.count_nonzero(np.any(uploaded != stored, axis=2)))
    out = uploaded.copy()
    out[mask] = stored[mask]

    # The keystone property this endpoint rests on, checked for real rather than taken
    # on faith: restoring only the flagged blocks from the archive must reproduce the
    # archive file exactly. If this ever fails, something upstream is badly wrong (a
    # shape mismatch, the wrong record, a crop disagreement) -- let it crash loudly
    # (-> a clean 500 via `guarded`) instead of silently handing back a wrong image.
    assert np.array_equal(out, stored)

    SESSION["restored_image"] = out

    return ok(
        restored=encode_png_data_uri(out),
        blocks_restored=int(det.block_mask.sum()),
        total_blocks=int(det.info["K"]),
        bit_exact=bool(np.array_equal(out, stored)),
        pixels_changed=pixels_changed,
        record_id=SESSION.get("record_id"),
        note=(
            "This is an EXACT restore from the stored archive copy, not a "
            "reconstruction: every pixel in the flagged region is copied byte-for-byte "
            "from the library record verification identified. The watermark's only job "
            "here is proving this upload IS that record and pinpointing exactly which "
            "blocks changed -- the returned pixels come from the archive, not from the "
            "watermark. Contrast with /api/verify/repair, which reconstructs the flagged "
            "region from the watermark's own recovery descriptors alone and needs no "
            "archive copy at all -- more self-contained, but only ever as good as what "
            "the descriptors could carry, never bit-exact."
        ),
    )


if __name__ == "__main__":
    # ponytail: argparse over a hardcoded port. Two flags, and it stops the tool
    # being unusable the moment 8765 is already taken -- which is exactly what
    # happened while screenshotting this app: a script passed --port, the flag was
    # silently ignored, the server bound 8765 anyway, and the caller polled a dead
    # port until it timed out. Binding stays on loopback by default; this is a
    # single-user local tool, not a service.
    import argparse

    ap = argparse.ArgumentParser(description="Fragile Watermark Recovery -- local web app")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    print(f"Fragile Watermark Recovery -- open http://{args.host}:{args.port}/ in your browser")
    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
