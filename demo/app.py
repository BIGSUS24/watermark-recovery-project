"""Streamlit demo for the self-embedding fragile watermarking project.

Live-panel demo, not a measurement tool: every number shown comes straight from
src/ (embed.py / detect.py / recover.py / metrics.py / tamper.py) with zero
duplicated numerics here. This file only adds a handful of small, plain,
UI-specific helpers (rectangle tampering at a presenter-chosen box, the
tag-transplant attack, the unrecoverable-partner attack, mask-stage rendering,
partner-link/magenta drawing) that are NOT part of the measured pipeline --
each is a pure function taking/returning arrays so the headless smoke test at
the bottom can exercise the exact same functions the UI calls.

Run:      streamlit run demo/app.py
Smoke test (no server): python demo/app.py
"""

import csv
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import cv2
import numpy as np
import streamlit as st

from blockmap import build_map
from detect import DetectResult, detect_image, expand_mask
from embed import embed_image
from metrics import confusion_counts, image_metrics, loc_scores, recovery_metrics
from payload import crop_to_blocks, default_image_id
from recover import RecoverResult, recover_image
from tamper import block_mask_from_pixel_mask

APP_DIR = Path(__file__).resolve().parent
SAMPLES_DIR = APP_DIR.parent / "samples"
MAX_DEMO_DIM = 1024

TAMPER_CLASS_LABELS = {
    "noise": "Noise overwrite",
    "solid": "Solid deletion",
    "inpaint": "Diffusion inpainting",
}


# ===========================================================================
# Plain, testable helpers -- no Streamlit calls below this banner until main()
# ===========================================================================

def load_manifest() -> list[dict]:
    """samples/manifest.csv -> list of row dicts. Stdlib csv, no pandas -- 32 rows."""
    with open(SAMPLES_DIR / "manifest.csv", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def decode_image_bytes(img_bytes: bytes) -> tuple[np.ndarray, bool]:
    """PNG bytes -> (RGB uint8 array, was_resized).

    cv2.imdecode(..., IMREAD_COLOR) forces 8-bit 3-channel BGR in one call --
    this silently handles the 16-bit/wide-gamut guard AND the RGBA guard at
    once (OpenCV drops alpha and downconverts bit depth itself), so there is
    no separate branch for either case. Downscales to MAX_DEMO_DIM on the long
    side, matching the stage-safety table's "large image" guard.
    """
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        raise ValueError("could not decode image bytes")
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    resized = False
    h, w = rgb.shape[:2]
    if max(h, w) > MAX_DEMO_DIM:
        scale = MAX_DEMO_DIM / max(h, w)
        rgb = cv2.resize(rgb, (max(1, int(round(w * scale))), max(1, int(round(h * scale)))),
                          interpolation=cv2.INTER_AREA)
        resized = True
    return rgb, resized


def sniff_image_format(data: bytes) -> str:
    """Identify an image's on-disk format by magic bytes -- never by filename extension.

    Only PNG/BMP/TIFF are genuinely lossless. WEBP can be either lossy or lossless, but
    telling them apart needs parsing the RIFF chunk header, which is deliberately not
    attempted here -- WEBP is reported distinctly so the caller can reject it with its
    own message rather than folding it into "unknown".
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:2] == b"BM":
        return "BMP"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return "TIFF"
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return "unknown"


def effective_variant(block: int, variant: str) -> str:
    """Variant C is a block-8 format; degrade to A at block 4 instead of raising.

    Called from BOTH places that consume (block, variant) -- the sidebar control and
    the tamper-preview path, which read the same two session_state keys independently.
    Guarding only the sidebar would leave the other one passing C with block 4 straight
    into embed_image(), which correctly refuses. One helper, so they cannot disagree.
    """
    return "A" if variant == "C" and block != 8 else variant


@st.cache_data(show_spinner="Embedding watermark...")
def embed_pipeline(img_bytes: bytes, key_str: str, image_id: str, block: int, variant: str
                   ) -> tuple[np.ndarray, np.ndarray, dict, bool]:
    """Cache key is (bytes, str, str, int, str) only -- never a numpy array (see spec).

    Decodes inside the cached function; returns the block-cropped ORIGINAL (so
    every downstream array shares one exact shape) plus the watermarked image.
    """
    rgb, resized = decode_image_bytes(img_bytes)
    original, _ = crop_to_blocks(rgb, block)
    wm, info = embed_image(original, key_str, image_id, block, variant)
    return original, wm, info, resized


def amplify_diff(a: np.ndarray, b: np.ndarray, factor: int = 50) -> np.ndarray:
    """Per spec: clipped, integer-safe x50 absolute difference."""
    return np.clip(cv2.absdiff(a, b).astype(np.int16) * factor, 0, 255).astype(np.uint8)


def rect_tamper(img: np.ndarray, y0: int, x0: int, y1: int, x1: int, tclass: str, seed: int = 0
                ) -> tuple[np.ndarray, np.ndarray]:
    """Tamper the exact rectangle [y0:y1, x0:x1] with one of three simple realizations.

    Ground truth is the region itself (decided before any pixel is written), matching
    tamper.py's own convention -- never a before/after diff.
    """
    h, w = img.shape[:2]
    y0, y1 = max(0, min(y0, h)), max(0, min(y1, h))
    x0, x1 = max(0, min(x0, w)), max(0, min(x1, w))
    if y1 <= y0:
        y1 = min(h, y0 + 1)
    if x1 <= x0:
        x1 = min(w, x0 + 1)
    out = img.copy()
    region_shape = out[y0:y1, x0:x1].shape
    if tclass == "noise":
        rng = np.random.default_rng(seed)
        out[y0:y1, x0:x1] = rng.integers(0, 256, region_shape, dtype=np.uint8)
    elif tclass == "solid":
        out[y0:y1, x0:x1] = 0
    else:  # "inpaint" -- realistic diffusion fill, mirrors tamper.py's tamper_inpaint_removal
        mask_u8 = np.zeros((h, w), dtype=np.uint8)
        mask_u8[y0:y1, x0:x1] = 255
        flags = cv2.INPAINT_TELEA
        filled = cv2.inpaint(img, mask_u8, inpaintRadius=3, flags=flags)
        out = img.copy()
        out[y0:y1, x0:x1] = filled[y0:y1, x0:x1]
    mask = np.zeros((h, w), dtype=bool)
    mask[y0:y1, x0:x1] = True
    return out, mask


def scatter_tamper(img: np.ndarray, ratio: float, seed: int, patch: int
                   ) -> tuple[np.ndarray, np.ndarray]:
    """Many small ISOLATED noise patches covering ~ratio of the image area.

    Deliberately isolated (never adjacent) rather than a blob: this is the tamper
    shape that demonstrates refine_mask's documented recall cost on scattered,
    single-block-sized damage (see detect.py's refine_mask docstring).
    """
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    out = img.copy()
    mask = np.zeros((h, w), dtype=bool)
    target = ratio * h * w
    attempts = 0
    while mask.sum() < target and attempts < 10_000:
        attempts += 1
        y0 = int(rng.integers(0, max(1, h - patch + 1)))
        x0 = int(rng.integers(0, max(1, w - patch + 1)))
        y1, x1 = min(h, y0 + patch), min(x0 + patch, w)
        region_shape = out[y0:y1, x0:x1].shape
        out[y0:y1, x0:x1] = rng.integers(0, 256, region_shape, dtype=np.uint8)
        mask[y0:y1, x0:x1] = True
    return out, mask


def inject_synthetic_bit_errors(img: np.ndarray, block: int, n: int = 3, seed: int = 0,
                                 exclude_block_mask: np.ndarray | None = None
                                ) -> tuple[np.ndarray, list[tuple[int, int]]]:
    """Flip ONE MSB-plane bit (0x04) in each of n mutually-isolated, untampered blocks.

    Demonstration-only device (never touches a measurement path): with a correct
    HMAC, a clean image has raw_mask.sum() == 0, so there is nothing for the
    refinement pass to visibly clean up. This creates a couple of isolated false
    positives on purpose so Stage 1 -> Stage 2 has something to show.
    """
    h, w = img.shape[:2]
    rg, cg = h // block, w // block
    rng = np.random.default_rng(seed)
    avoid = np.zeros((rg, cg), dtype=bool)
    if exclude_block_mask is not None:
        avoid |= np.asarray(exclude_block_mask, dtype=bool)
    out = img.copy()
    chosen: list[tuple[int, int]] = []
    attempts = 0
    while len(chosen) < n and attempts < 2000:
        attempts += 1
        r, c = int(rng.integers(0, rg)), int(rng.integers(0, cg))
        if avoid[r, c]:
            continue
        neighbours_hit = False
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                rr, cc = r + dr, c + dc
                if 0 <= rr < rg and 0 <= cc < cg and avoid[rr, cc]:
                    neighbours_hit = True
        if neighbours_hit:
            continue
        chosen.append((r, c))
        avoid[r, c] = True
        py, px = r * block + block // 2, c * block + block // 2
        if out.ndim == 2:
            out[py, px] = out[py, px] ^ np.uint8(0x04)
        else:
            out[py, px, 0] = out[py, px, 0] ^ np.uint8(0x04)
    return out, chosen


def tag_transplant(wm: np.ndarray, block: int, dst_row: int, dst_col: int
                   ) -> tuple[np.ndarray, int, int]:
    """Copy the nearest-mean-intensity block's pixels into (dst_row, dst_col).

    The copied region carries a genuinely valid HMAC tag -- for ITS OWN original
    index -- which is exactly the Holliman-Memon (2000) collage-attack setup.
    """
    h, w = wm.shape[:2]
    rg, cg = h // block, w // block
    dst_idx = dst_row * cg + dst_col
    if wm.ndim == 2:
        blocks = wm.reshape(rg, block, cg, block).transpose(0, 2, 1, 3).reshape(rg * cg, block, block)
        means = blocks.astype(np.float64).mean(axis=(1, 2))
    else:
        per_ch = [wm[:, :, ch].reshape(rg, block, cg, block).transpose(0, 2, 1, 3).reshape(rg * cg, block, block)
                  for ch in range(wm.shape[2])]
        means = np.stack(per_ch, axis=1).astype(np.float64).mean(axis=(1, 2, 3))
    diffs = np.abs(means - means[dst_idx])
    diffs[dst_idx] = np.inf
    src_idx = int(np.argmin(diffs))
    sr, sc = divmod(src_idx, cg)
    dr, dc = divmod(dst_idx, cg)
    out = wm.copy()
    out[dr * block:(dr + 1) * block, dc * block:(dc + 1) * block] = \
        wm[sr * block:(sr + 1) * block, sc * block:(sc + 1) * block]
    return out, src_idx, dst_idx


def unrecoverable_demo_tamper(wm: np.ndarray, key: str, image_id: str, block: int, variant: str,
                              block_idx: int, seed: int = 0) -> tuple[np.ndarray, int, int]:
    """Destroy block `block_idx` AND its backup partner (m[block_idx]) in one action."""
    det0 = detect_image(wm, key, image_id, block, variant)  # clean detect, just to read m
    partner = int(det0.m[block_idx])
    rg, cg = det0.block_mask.shape
    out = wm.copy()
    rng = np.random.default_rng(seed)
    for idx in (block_idx, partner):
        r, c = divmod(idx, cg)
        y0, x0 = r * block, c * block
        region_shape = out[y0:y0 + block, x0:x0 + block].shape
        out[y0:y0 + block, x0:x0 + block] = rng.integers(0, 256, region_shape, dtype=np.uint8)
    return out, block_idx, partner


def draw_partner_links(img: np.ndarray, block_indices, m: np.ndarray, block: int,
                       blocks_per_row: int, cap: int = 25) -> np.ndarray:
    """Line + circles from each block's centre to its backup-holder block's centre.

    centre = (col*B + B//2, row*B + B//2), per the spec formula -- capped at `cap`
    lines so the overlay stays legible instead of turning into visual noise.
    """
    canvas = img.copy()
    if canvas.ndim == 2:
        canvas = cv2.cvtColor(canvas, cv2.COLOR_GRAY2RGB)
    for i in list(block_indices)[:cap]:
        i = int(i)
        row, col = divmod(i, blocks_per_row)
        centre = (col * block + block // 2, row * block + block // 2)
        j = int(m[i])
        rowj, colj = divmod(j, blocks_per_row)
        centre_j = (colj * block + block // 2, rowj * block + block // 2)
        cv2.line(canvas, centre, centre_j, (255, 0, 255), 1)
        cv2.circle(canvas, centre, 3, (0, 255, 255), -1)
        cv2.circle(canvas, centre_j, 3, (255, 0, 255), -1)
    return canvas


def paint_unrecoverable_magenta(img: np.ndarray, unrecoverable_block_mask: np.ndarray, block: int
                                ) -> np.ndarray:
    """Solid magenta overlay over flagged blocks -- DISPLAY ONLY.

    recover_image's own mark_value=0 (black) is what the measured pipeline and the
    smoke test check; this paints a copy for the audience so "unrecoverable" cannot
    read as "did nothing" on a projector.
    """
    out = img.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2RGB)
    cg = unrecoverable_block_mask.shape[1]
    for idx in np.flatnonzero(unrecoverable_block_mask.ravel()):
        r, c = divmod(int(idx), cg)
        y0, x0 = r * block, c * block
        cv2.rectangle(out, (x0, y0), (x0 + block - 1, y0 + block - 1), (255, 0, 255), -1)
    return out


def cosmetic_fill(img: np.ndarray, unrecoverable_block_mask: np.ndarray, block: int
                  ) -> np.ndarray:
    """Interpolate the marked blocks away. COSMETIC ONLY -- see webapp/server.py's
    twin for the full argument.

    Short version: these pixels have no cryptographic provenance. Every other pixel
    in a repair came from a descriptor carried by a block whose tag verified; these
    came from an interpolator guessing at the neighbours. It runs on a copy,
    downstream of recover_image, and its output reaches no metric -- rho, the
    unrecoverable count and every PSNR/SSIM below are computed from recover_image's
    real output, where these blocks are still flat mark_value.
    """
    out = img.copy()
    if out.ndim == 2:
        out = cv2.cvtColor(out, cv2.COLOR_GRAY2RGB)
    px = expand_mask(unrecoverable_block_mask, block).astype(np.uint8)
    if not px.any():
        return out
    bgr = np.ascontiguousarray(out[:, :, ::-1])
    return cv2.inpaint(bgr, px, 3, cv2.INPAINT_TELEA)[:, :, ::-1].copy()


MASK_STAGE_LABELS = [
    "Stage 1 -- raw block flags (pre-refinement)",
    "Stage 2 -- majority-refined block flags",
    "Stage 3 -- expanded pixel mask",
]


def mask_stage_image(det: DetectResult, stage: int) -> tuple[np.ndarray, str, str]:
    """(display image 0/255 uint8, stage label, flagged-count caption) for stage in {0,1,2}."""
    if stage == 0:
        m = det.raw_mask
        return (m * 255).astype(np.uint8), MASK_STAGE_LABELS[0], f"{int(m.sum())} blocks flagged"
    if stage == 1:
        m = det.block_mask
        return (m * 255).astype(np.uint8), MASK_STAGE_LABELS[1], f"{int(m.sum())} blocks flagged"
    m = det.pixel_mask
    return ((m * 255).astype(np.uint8), MASK_STAGE_LABELS[2],
            f"{int(det.block_mask.sum())} blocks -> {int(m.sum())} pixels flagged")


# ===========================================================================
# Streamlit UI -- widgets, session_state, rendering only. No numerics live here.
# ===========================================================================

def _in_streamlit() -> bool:
    """True when actually served by `streamlit run`, False for a plain `python` run.

    st.runtime.exists() is the documented modern check (replaces the older
    get_script_run_ctx()-is-not-None idiom); __name__ alone cannot distinguish the
    two cases because Streamlit's script runner also executes the file as "__main__".
    """
    try:
        return st.runtime.exists()
    except Exception:
        return False


def _preset_callback(kind: str) -> None:
    """on_click callback for the three preset buttons.

    Runs BEFORE the script body's widgets are (re)instantiated on this rerun, which
    is the only place session_state for widget-backed keys (the rect sliders) may be
    written -- writing to them after their widgets have rendered in the same run
    raises. This is also where the actual tamper is applied, so one preset click is
    a complete action (set rect + apply), matching "lead with presets on stage".
    """
    img_bytes = st.session_state["current_img_bytes"]
    key_str = st.session_state["secret_key"]
    image_id = st.session_state["image_id"]
    block = st.session_state["block"]
    variant = effective_variant(block, st.session_state["variant"])
    tclass = st.session_state["tamper_class"]
    _, wm, _, _ = embed_pipeline(img_bytes, key_str, image_id, block, variant)
    h, w = wm.shape[:2]

    if kind == "corner":
        size = max(block, min(h, w) // 4)
        y0, x0, y1, x1 = 0, 0, size, size
        tampered, mask = rect_tamper(wm, y0, x0, y1, x1, tclass, seed=1)
        desc = "Preset: damaged a corner"
    elif kind == "centre":
        size = max(block, min(h, w) // 4)
        y0, x0 = h // 2 - size // 2, w // 2 - size // 2
        y1, x1 = y0 + size, x0 + size
        tampered, mask = rect_tamper(wm, y0, x0, y1, x1, tclass, seed=2)
        desc = "Preset: damaged the centre"
    else:  # "scatter"
        y0, x0, y1, x1 = 0, 0, h, w
        tampered, mask = scatter_tamper(wm, 0.20, seed=3, patch=block)
        desc = "Preset: scattered noise across ~20% of the image"

    st.session_state["rect_y0"], st.session_state["rect_x0"] = y0, x0
    st.session_state["rect_y1"], st.session_state["rect_x1"] = y1, x1
    st.session_state["tampered_img"] = tampered
    st.session_state["gt_mask_px"] = mask
    st.session_state["tamper_desc"] = desc
    st.session_state["det_result"] = None
    st.session_state["rec_result"] = None
    st.session_state["mask_stage"] = 0
    st.session_state["transplant_result"] = None
    st.session_state["unrecoverable_result"] = None


def main() -> None:
    st.set_page_config(page_title="Is This Photo Real? -- Watermarking Demo",
                       page_icon="\U0001f6e1️", layout="wide",
                       initial_sidebar_state="collapsed")
    st.markdown("""
    <style>
    .block-container { padding-top: 1.6rem; padding-bottom: 2.5rem; }
    div.stButton > button { border-radius: 8px; font-weight: 600; }
    div.stButton > button[kind="primary"] { padding: 0.55rem 1.3rem; font-size: 1.05rem; }
    [data-testid="stExpander"] summary p { font-weight: 600; }
    hr { margin: 1.4rem 0; }
    </style>
    """, unsafe_allow_html=True)

    st.title("Is This Photo Real?")
    st.caption("Self-embedding fragile watermarking, live -- protect a photo, damage it, then "
              "watch the system prove exactly what changed and repair what it can.")

    with st.expander("What is this? (start here)", expanded=not st.session_state.get("protected", False)):
        st.write(
            "This tool hides an invisible watermark in a photo, lets you damage the photo, "
            "then proves -- mathematically, with a check anyone holding the password could "
            "redo by hand -- exactly what changed, and repairs whatever it safely can."
        )
        st.markdown(
            "1. **Protect the photo** -- hide an invisible watermark in it.\n"
            "2. **Damage it** -- simulate someone tampering with the photo.\n"
            "3. **Check it** -- get a plain verdict: unchanged or edited, and where.\n"
            "4. **Repair it** -- reconstruct what can be reconstructed, honestly."
        )

    # ======================================================================
    # STEP 1 -- Protect the photo
    # ======================================================================
    with st.container(border=True):
        st.subheader("Step 1 · Protect the photo")
        st.caption("Pick a photo, then press the button below to hide an invisible watermark in it.")

        manifest = load_manifest()
        options = [f"{r['dataset']}/{r['filename']}" for r in manifest]
        default_idx = next((i for i, r in enumerate(manifest) if r["filename"].lower().startswith("lena")), 0)
        src1, src2 = st.columns(2)
        choice = src1.selectbox("Choose a sample photo", options, index=default_idx)
        uploaded = src2.file_uploader("...or upload your own (PNG only)", type=["png"])

        if uploaded is not None:
            data = uploaded.getvalue()
            fmt = sniff_image_format(data)
            if fmt == "WEBP":
                st.error("This looks like a WEBP file. This tool cannot tell a lossless WEBP apart "
                         "from a lossy one just by looking at it (that needs parsing the RIFF chunk "
                         "header), so it plays safe and asks for PNG instead -- convert and re-upload.")
                st.stop()
            if fmt not in ("PNG", "BMP", "TIFF"):
                shown = fmt if fmt != "unknown" else "an unrecognized format"
                st.error(f"This tool only works with lossless image files (PNG, BMP, or TIFF) -- this "
                         f"upload looks like {shown}. That is by design, not a bug: the watermark lives "
                         "in exact pixel values, and lossy re-compression (like JPEG) destroys it on "
                         "purpose-built grounds (see Limitations in the paper). Convert to PNG and "
                         "re-upload.")
                st.stop()
            img_bytes = data
            stem = Path(uploaded.name).stem
        else:
            row = manifest[options.index(choice)]
            img_bytes = (SAMPLES_DIR / row["relpath"]).read_bytes()
            stem = Path(row["filename"]).stem
        st.session_state["current_img_bytes"] = img_bytes

        # default-once guard; see spec item 5
        if "secret_key" not in st.session_state:
            st.session_state["secret_key"] = "demo-secret-key"
        key_str = st.text_input(
            "Secret password", key="secret_key",
            help="The cryptographic key used to both protect and check the photo -- like a lock "
                 "and its matching key. Change it and old protection/checks no longer match.")

        source_hash = hashlib.sha256(img_bytes).hexdigest()
        image_changed = st.session_state.get("source_hash") != source_hash
        if image_changed:
            rgb0, resized0 = decode_image_bytes(img_bytes)
            original0, _ = crop_to_blocks(rgb0, st.session_state.get("block", 8))
            st.session_state["source_hash"] = source_hash
            st.session_state["image_id"] = default_image_id(
                stem, original0.shape, st.session_state.get("block", 8)).decode()
            st.session_state["tampered_img"] = None
            st.session_state["gt_mask_px"] = None
            st.session_state["tamper_desc"] = None
            st.session_state["det_result"] = None
            st.session_state["rec_result"] = None
            st.session_state["mask_stage"] = 0
            st.session_state["transplant_result"] = None
            st.session_state["unrecoverable_result"] = None
            st.session_state["protected"] = False
            h0, w0 = original0.shape[:2]
            box = max(8, min(h0, w0) // 4)
            st.session_state["rect_y0"], st.session_state["rect_x0"] = h0 // 4, w0 // 4
            st.session_state["rect_y1"] = min(h0, h0 // 4 + box)
            st.session_state["rect_x1"] = min(w0, w0 // 4 + box)

        image_id = st.text_input(
            "Photo name/ID", key="image_id",
            help="A label baked into the protection, like a filename tied to a lock combination. "
                 "Change it and any earlier protection under the old name no longer matches.")

        with st.expander("Advanced settings (for the technical audience)", expanded=False):
            adv1, adv2, adv3 = st.columns(3)
            block = adv1.radio(
                "Block size", [8, 4], key="block", horizontal=True,
                help="Each photo is split into small squares of this many pixels per side before "
                     "protecting or checking it.")
            variant = adv2.radio(
                "Descriptor variant", ["C", "A", "B"], key="variant", horizontal=True,
                help="Which recipe each square's backup uses to store its recovery data. "
                     "C is the default and recovers roughly 3.4 dB better than A "
                     "(variable-width DCT coefficients, block size 8 only); A uses 12 "
                     "fixed-width DCT coefficients; B uses simple averages.")
            if effective_variant(block, variant) != variant:
                st.warning("Variant C needs block size 8 — using variant A at block 4.")
            variant = effective_variant(block, variant)
            if "tau" not in st.session_state:
                st.session_state["tau"] = 7
            tau = adv3.number_input(
                "Verification strictness (tau)", min_value=0, max_value=8, key="tau",
                help="How many of a square's 8 neighbours must also look damaged before an "
                     "isolated result gets smoothed over. Default 7 matches the published method.")
            st.caption("Damage area for the manual rectangle option in Step 2 (pixels):")
            rc1, rc2, rc3, rc4 = st.columns(4)
            rc1.slider("Damage area -- top", 0, MAX_DEMO_DIM, key="rect_y0")
            rc2.slider("Damage area -- left", 0, MAX_DEMO_DIM, key="rect_x0")
            rc3.slider("Damage area -- bottom", 1, MAX_DEMO_DIM, key="rect_y1")
            rc4.slider("Damage area -- right", 1, MAX_DEMO_DIM, key="rect_x1")

        # Changing block/variant/key/image-ID/tau invalidates any PRIOR detect/recover result
        # (computed under the old geometry) AND the tampered pixels + ground-truth mask -- the
        # tamper was carved into a watermark that no longer exists once any of these change, so
        # leaving it in place produced a meaningless "100% tampered" result with nothing on screen
        # to explain it. source_hash covers a changed source image too.
        stale_guard = (block, variant, key_str, image_id, source_hash, tau)
        if st.session_state.get("_stale_guard") != stale_guard:
            st.session_state["_stale_guard"] = stale_guard
            st.session_state["det_result"] = None
            st.session_state["rec_result"] = None
            st.session_state["mask_stage"] = 0
            st.session_state["transplant_result"] = None
            st.session_state["unrecoverable_result"] = None
            st.session_state["tampered_img"] = None
            st.session_state["gt_mask_px"] = None
            st.session_state["tamper_desc"] = None

        try:
            original, wm, embed_info, resized = embed_pipeline(img_bytes, key_str, image_id, block, variant)
        except ValueError as exc:
            st.error(
                "This photo is too small to protect -- it needs to be split into at least a "
                "handful of equal-size squares first. Use a photo of at least 24x24 pixels "
                "(12x12 if you switch to the smaller block size in Advanced settings), or pick "
                f"a bigger photo. Technical detail: {exc}"
            )
            st.stop()
        h, w = wm.shape[:2]
        if resized:
            st.caption(f"This photo was shrunk to fit the demo (max {MAX_DEMO_DIM}px on the long "
                      "side) -- still the same photo underneath.")

        protect_clicked = st.button("Protect this photo", type="primary")
        if protect_clicked:
            st.session_state["protected"] = True
        protected = st.session_state.get("protected", False)

        if protected:
            pc1, pc2 = st.columns(2)
            pc1.image(original, caption="Before", width="stretch")
            pc2.image(wm, caption="After -- protected", width="stretch")
            st.caption("These look identical -- that is the point. The protection lives in bits no eye can see.")
            amplify_on = st.checkbox(
                "Show me the hidden watermark", value=False,
                help="x50-exaggerated difference between the two photos above -- reveals where "
                     "the invisible protection data lives.")
            if amplify_on:
                st.image(amplify_diff(original, wm),
                         caption="Where the protection lives (difference between the two photos "
                                 "above, exaggerated 50x)",
                         width="stretch")
        else:
            st.caption("Choose a photo above, then press 'Protect this photo' to continue.")

    # ======================================================================
    # STEP 2 -- Damage it
    # ======================================================================
    with st.container(border=True):
        st.subheader("Step 2 · Damage it")
        st.caption("Simulate someone tampering with the protected photo.")
        disabled2 = not protected

        st.radio(
            "How to damage it", list(TAMPER_CLASS_LABELS.keys()),
            format_func=lambda k: TAMPER_CLASS_LABELS[k], key="tamper_class",
            help="Noise overwrite: random static. Solid deletion: blacked out. Diffusion "
                 "inpainting: an AI-style smart fill that tries to hide the damage.")

        d1, d2, d3 = st.columns(3)
        d1.button("Damage a corner", disabled=disabled2, width="stretch",
                 on_click=_preset_callback, args=("corner",))
        d2.button("Damage the middle", disabled=disabled2, width="stretch",
                 on_click=_preset_callback, args=("centre",))
        d3.button("Scatter damage", disabled=disabled2, width="stretch",
                 on_click=_preset_callback, args=("scatter",))

        with st.expander("Or damage an exact rectangle (advanced)", expanded=False):
            st.caption("Uses the top/left/bottom/right pixel values set in Step 1's Advanced settings.")
            if st.button("Damage this photo (custom area)", disabled=disabled2):
                ry0 = st.session_state["rect_y0"]
                rx0 = st.session_state["rect_x0"]
                ry1 = st.session_state["rect_y1"]
                rx1 = st.session_state["rect_x1"]
                tampered, mask = rect_tamper(wm, ry0, rx0, ry1, rx1, st.session_state["tamper_class"], seed=1)
                st.session_state["tampered_img"] = tampered
                st.session_state["gt_mask_px"] = mask
                st.session_state["tamper_desc"] = f"Manual rectangle [{ry0}:{ry1}, {rx0}:{rx1}]"
                st.session_state["det_result"] = None
                st.session_state["rec_result"] = None
                st.session_state["mask_stage"] = 0
                st.session_state["transplant_result"] = None
                st.session_state["unrecoverable_result"] = None

        if disabled2:
            st.caption("Protect a photo first (Step 1).")

        tampered_img = st.session_state.get("tampered_img")
        if tampered_img is not None:
            st.image(tampered_img, caption=f"Damaged -- {st.session_state.get('tamper_desc', '')}",
                     width="stretch")
        elif protected:
            st.caption("Pick a preset above (or the advanced rectangle option) to damage the photo.")

    # ======================================================================
    # STEP 3 -- Check it
    # ======================================================================
    with st.container(border=True):
        st.subheader("Step 3 · Check it")
        st.caption("Ask the system whether this exact photo still matches what was protected. "
                  "Works whether or not you damaged it in Step 2.")
        check_target = tampered_img if tampered_img is not None else wm
        disabled3 = not protected
        check_clicked = st.button("Check this photo", disabled=disabled3, type="primary")
        if disabled3:
            st.caption("Protect a photo first (Step 1).")

        if check_clicked:
            st.session_state["det_result"] = detect_image(
                check_target, key_str, image_id, block, variant, tau=tau)
            st.session_state["rec_result"] = None
            st.session_state["mask_stage"] = 0

        det_result: DetectResult | None = st.session_state.get("det_result")

        if det_result is not None:
            flagged = int(det_result.block_mask.sum())
            total = int(det_result.info["K"])
            if flagged == 0:
                st.success(f"## ✅ THIS PHOTO IS UNCHANGED — all {total:,} areas verified")
            else:
                st.error(f"## ⚠️ THIS PHOTO WAS EDITED — {flagged:,} of {total:,} "
                        "areas do not match")

            if det_result.info.get("suspect_parameters"):
                st.warning("⚠️ " + det_result.info["suspect_message"])

            show_synthetic = st.checkbox(
                "Add a couple of fake glitches to show the cleanup step "
                "(demonstration only -- not part of any measured result)",
                value=False,
                help="Flips a bit in a couple of untampered squares so the raw-to-cleaned-up "
                     "stages below have something to show. Never affects the verdict above.")

            display_det = det_result
            if show_synthetic:
                gt_mask_px = st.session_state.get("gt_mask_px")
                excl = block_mask_from_pixel_mask(gt_mask_px, block) if gt_mask_px is not None else None
                injected_img, injected_blocks = inject_synthetic_bit_errors(
                    check_target, block, n=3, seed=99, exclude_block_mask=excl)
                display_det = detect_image(injected_img, key_str, image_id, block, variant, tau=tau)
                st.caption("Fake glitches added for this demonstration only -- not part of any "
                          "measured result.")

            st.markdown("**How it finds the damage**")
            stage = st.session_state.get("mask_stage", 0)
            bcol1, _, bcol3 = st.columns([1, 4, 1])
            if bcol1.button("<- Back", disabled=stage == 0):
                st.session_state["mask_stage"] = max(0, stage - 1)
            if bcol3.button("Next ->", disabled=stage == 2):
                st.session_state["mask_stage"] = min(2, stage + 1)
            stage_img, stage_label, stage_suffix = mask_stage_image(
                display_det, st.session_state.get("mask_stage", 0))
            st.image(stage_img, caption=f"{stage_label} -- {stage_suffix}", width="stretch", clamp=True)

            show_links = st.checkbox(
                "Show which square backed up which", value=False,
                help="Draws a line from every repaired square to the distant square that held "
                     "its backup data (the partner-block link).")
            if show_links:
                rec_for_links = st.session_state.get("rec_result")
                if rec_for_links is not None:
                    idxs = np.flatnonzero(rec_for_links.recovered_mask.ravel())
                    cg_links = display_det.block_mask.shape[1]
                    linked = draw_partner_links(wm, idxs, display_det.m, block, cg_links, cap=25)
                    st.image(linked, width="stretch",
                            caption=f"Showing {min(25, len(idxs))} of {len(idxs)} backup links "
                                    "(repaired square -> the distant square that held its backup)")
                else:
                    st.caption("Repair the damage (Step 4) to see this.")

            with st.expander("Show me the evidence for one square"):
                st.caption("Pick any square and see exactly why it passed or failed -- the same "
                          "check anyone holding the secret password could redo by hand.")
                flagged_idxs = np.flatnonzero(det_result.block_mask.ravel())
                default_block = int(flagged_idxs[0]) if flagged_idxs.size else 0
                block_idx = st.number_input(
                    "Square number", min_value=0, max_value=total - 1, value=default_block,
                    help="Squares are numbered left-to-right, top-to-bottom, starting at 0.")
                audit = det_result.audit(int(block_idx))
                icon = {"AUTHENTIC": "✅", "RECOVERABLE": "\U0001f6e0️",
                       "UNRECOVERABLE": "\U0001f6ab",
                       "FLAGGED_BY_REFINEMENT": "\U0001f50e"}.get(audit["decision"], "")
                st.markdown(f"**Square #{audit['block']} -- {icon} {audit['decision']}**")
                st.write(audit["reason"])
                ac1, ac2 = st.columns(2)
                ac1.write("Tag stored in the photo:")
                ac1.code("".join(str(b) for b in audit["stored_tag"]))
                ac2.write("Tag recomputed with the password:")
                ac2.code("".join(str(b) for b in audit["recomputed_tag"]))
                st.caption(f"Tags match: {'yes' if audit['tag_matched'] else 'no'}. Backup "
                          f"partner square: #{audit['partner_block']} "
                          f"({'also flagged' if audit['partner_flagged'] else 'intact'}).")
        else:
            st.caption("Click 'Check this photo' to get a plain verdict.")

    # ======================================================================
    # STEP 4 -- Repair it
    # ======================================================================
    with st.container(border=True):
        st.subheader("Step 4 · Repair it")
        st.caption("Reconstruct whatever the damaged squares' backups allow.")
        disabled4 = det_result is None
        repair_clicked = st.button("Repair the damage", disabled=disabled4, type="primary")
        if disabled4:
            st.caption("Check the photo first (Step 3).")

        if repair_clicked:
            st.session_state["rec_result"] = recover_image(check_target, det_result, block, variant)

        rec_result: RecoverResult | None = st.session_state.get("rec_result")

        if rec_result is not None:
            disp = rec_result.image
            note = ""
            if rec_result.unrecoverable_mask.sum() > 0:
                # Offered only when there is something to fill: an interpolation
                # switch on a gapless image invites the audience to believe
                # something was filled in.
                fill = st.checkbox(
                    "Fill the magenta gaps by interpolation (cosmetic only -- guessed "
                    "from neighbouring pixels, not recovered from the watermark)",
                    value=False, key="cosmetic_fill")
                if fill:
                    disp = cosmetic_fill(rec_result.image, rec_result.unrecoverable_mask, block)
                    note = (" -- gaps interpolated: those pixels are a guess from their "
                            "neighbours, not watermark data, and are excluded from every "
                            "number below")
                else:
                    disp = paint_unrecoverable_magenta(rec_result.image,
                                                       rec_result.unrecoverable_mask, block)
                    note = " -- magenta = could not be repaired (shown honestly, never faked)"
            st.image(disp, caption=f"Repaired{note}", width="stretch")

            gt_mask_px = st.session_state.get("gt_mask_px")
            if gt_mask_px is not None:
                gt_block = block_mask_from_pixel_mask(gt_mask_px, block)
                tp, fp, fn, tn = confusion_counts(det_result.block_mask, gt_block)
                loc = loc_scores(tp, fp, fn, tn)
                unrec_px = expand_mask(rec_result.unrecoverable_mask, block)
                rm = recovery_metrics(wm, rec_result.image, gt_mask_px, unrec_px)
                p_embed, s_embed = image_metrics(original, wm)

                st.markdown("**The numbers, explained**")
                m1, m2, m3 = st.columns(3)
                m1.metric("How invisible is it?", f"{p_embed:.2f} dB",
                         help="Peak signal-to-noise ratio between the original and protected "
                              "photo. Above 40 dB means the human eye cannot tell them apart.")
                m2.metric("Did we find the damage?", f"{loc['recall'] * 100:.1f}%",
                         help="Recall -- the share of truly damaged squares that were correctly "
                              "flagged. 100% means every damaged square was caught.")
                m3.metric("Alarm accuracy", f"{loc['precision'] * 100:.1f}%",
                         help="Precision -- of the squares flagged as damaged, how many really were.")
                m4, m5, m6 = st.columns(3)
                m4.metric("False alarms", f"{fp}",
                         help="Number of undamaged squares wrongly flagged as damaged. 0 is best.")
                m5.metric("How much could we repair?", f"{rec_result.rho * 100:.1f}%",
                         help="Recoverability rate. The rest had its backup destroyed too -- "
                              "repairing it would mean inventing pixels, which this tool refuses to do.")
                m6.metric("Repair quality", f"{rm['psnr_in_region']:.2f} dB",
                         help="Peak signal-to-noise ratio of the repaired area against the "
                              "original. Lower than 'how invisible is it' -- a slightly soft "
                              "reconstruction, not pixel-perfect.")

                with st.expander("More numbers (for the technical audience)"):
                    e1, e2, e3 = st.columns(3)
                    e1.metric("F1", f"{loc['f1']:.3f}", help="Harmonic mean of precision and recall.")
                    e2.metric("IoU", f"{loc['iou']:.3f}",
                             help="Intersection-over-union of the flagged area against the true damage.")
                    ssim_disp = f"{rm['ssim_in_region']:.4f}" if np.isfinite(rm["ssim_in_region"]) else "n/a"
                    e3.metric("SSIM (repaired region)", ssim_disp,
                             help="Structural similarity of the repaired area against the "
                                  "original. 1.0 = identical structure.")
        else:
            st.caption("Click 'Repair the damage' once you've checked the photo.")

    # ======================================================================
    # Try to break it -- adversarial set-pieces
    # ======================================================================
    st.divider()
    with st.container(border=True):
        st.subheader("Try to break it")
        st.caption("Two adversarial demonstrations built to stress-test the honesty of the system above.")
        disabled5 = not protected
        if disabled5:
            st.caption("Protect a photo first (Step 1).")

        acol1, acol2 = st.columns(2)
        run_transplant = acol1.button(
            "Try the copy-paste trick", disabled=disabled5, width="stretch",
            help="Also called the tag-transplant / block-collage attack (Holliman-Memon, 2000).")
        run_unrec = acol2.button(
            "Try destroying the backup too", disabled=disabled5, width="stretch",
            help="Forces one square and the only square holding its backup to both be damaged at once.")

        if run_transplant:
            ry0 = st.session_state["rect_y0"]
            rx0 = st.session_state["rect_x0"]
            dst_row = min(max(0, ry0 // block), h // block - 1)
            dst_col = min(max(0, rx0 // block), w // block - 1)
            transplanted, src_idx, dst_idx = tag_transplant(wm, block, dst_row, dst_col)
            det_tr = detect_image(transplanted, key_str, image_id, block, variant, tau=tau)
            st.session_state["transplant_result"] = (transplanted, src_idx, dst_idx, det_tr)

        if run_unrec:
            rg, cg = h // block, w // block
            block_idx = (rg // 2) * cg + (cg // 2)
            forced, i, partner = unrecoverable_demo_tamper(wm, key_str, image_id, block, variant, block_idx)
            # refine=False: this deliberately tampers an exact, isolated pair of far-apart single
            # blocks to test the recovery-honesty guarantee precisely. The majority-vote refinement
            # pass is a smoothing heuristic for realistic contiguous damage (see refine_mask's
            # docstring) and would clear both isolated blocks before recovery ever saw them.
            det_f = detect_image(forced, key_str, image_id, block, variant, refine=False)
            rec_f = recover_image(forced, det_f, block, variant)
            st.session_state["unrecoverable_result"] = (forced, i, partner, rec_f)

        tr = st.session_state.get("transplant_result")
        if tr is not None:
            transplanted, src_idx, dst_idx, det_tr = tr
            rg2, cg2 = det_tr.block_mask.shape
            dr, dc = divmod(dst_idx, cg2)
            # raw_mask, NOT block_mask: the security property under test is the per-block HMAC
            # check itself (raw_mask IS that check, pre-refinement). refine_mask's majority-vote
            # smoothing is a separate, orthogonal heuristic that can clear an isolated single
            # flagged block -- documented in detect.py's own refine_mask docstring -- and is not
            # part of the cryptographic claim this set-piece demonstrates.
            flagged_raw = bool(det_tr.raw_mask[dr, dc])
            survived_refine = bool(det_tr.block_mask[dr, dc])
            tc1, tc2 = st.columns(2)
            tc1.image(wm, caption="Protected photo (source of the genuine tag)", width="stretch")
            tc2.image(transplanted,
                     caption=f"After the trick: square #{dst_idx} <- pixels copied from square #{src_idx}",
                     width="stretch")
            if flagged_raw:
                st.error(
                    f"\U0001f6ab **The trick failed.** Every byte in this area carries a genuinely "
                    f"valid tag -- cut straight from square #{src_idx} of this same photo. The check "
                    f"still fired at square #{dst_idx}, because the tag is bound to *which square it "
                    "is*, not just what it contains. This is exactly what defeats the classic "
                    "Holliman-Memon (2000) copy-paste (block-collage) attack.")
                if not survived_refine:
                    st.caption(
                        "Note: this single copied square has no damaged neighbours, so the cleanup "
                        "pass (Step 3's 'How it finds the damage') clears it as a lone flag -- a "
                        "separate smoothing rule, not the underlying tag check itself. Tick 'Add a "
                        "couple of fake glitches' in Step 3 to see that same lone-flag rule in action.")
            else:
                st.warning("The check did not fire -- source and destination squares were the same "
                          "one; move the Advanced rectangle's top-left corner and try again.")

        ur = st.session_state.get("unrecoverable_result")
        if ur is not None:
            forced, i, partner, rec_f = ur
            uc1, uc2 = st.columns(2)
            uc1.image(forced,
                     caption=f"Damaged: square #{i} AND its only backup, square #{partner}, both "
                             "destroyed at once", width="stretch")
            uc2.image(paint_unrecoverable_magenta(rec_f.image, rec_f.unrecoverable_mask, block),
                     caption="Repair result (magenta = could not be repaired)", width="stretch")
            st.error(
                f"\U0001f6ab **Correctly refuses to guess.** Square #{i}'s only backup (square "
                f"#{partner}) was destroyed in the same attack, so there is nothing left to rebuild "
                "from. The system reports UNRECOVERABLE instead of inventing pixels.")


# ===========================================================================
# Headless smoke test -- scripts all three set-pieces through the exact same
# helper functions main() calls above. Run: python demo/app.py
# ===========================================================================

def _smoke_test() -> None:
    print("=== demo/app.py headless smoke test ===")
    key_str, image_id, block, variant = "smoke-key", "lena-smoke", 8, "A"
    lena_bytes = (SAMPLES_DIR / "usc_sipi" / "lena.png").read_bytes()

    original, wm, info, resized = embed_pipeline(lena_bytes, key_str, image_id, block, variant)
    assert 40.0 <= info["psnr"] <= 45.0, info["psnr"]
    assert info["ssim"] > 0.96, info["ssim"]
    print(f"embed: shape={wm.shape} psnr={info['psnr']:.2f} ssim={info['ssim']:.4f} resized={resized}")

    h, w = wm.shape[:2]
    y0, x0, y1, x1 = h // 4, w // 4, h // 4 + 64, w // 4 + 64
    tampered, gt_mask = rect_tamper(wm, y0, x0, y1, x1, "noise", seed=1)
    det = detect_image(tampered, key_str, image_id, block, variant)
    assert det.block_mask.sum() > 0, "tamper -> detect: nothing flagged"
    rec = recover_image(tampered, det, block, variant)
    region = (slice(y0, y1), slice(x0, x1))
    assert not np.array_equal(rec.image[region], tampered[region]), "recovery did not change the region"
    print(f"(a) tamper->detect->recover: flagged_blocks={int(det.block_mask.sum())} rho={rec.rho:.3f}")

    dst_row, dst_col = y0 // block, x0 // block
    transplanted, src_idx, dst_idx = tag_transplant(wm, block, dst_row, dst_col)
    det_tr = detect_image(transplanted, key_str, image_id, block, variant)
    rg, cg = det_tr.block_mask.shape
    dr, dc = divmod(dst_idx, cg)
    # raw_mask (the per-block HMAC check itself), not block_mask: see the comment beside the
    # matching UI code in main() -- refine_mask's isolated-positive-clear rule is a separate,
    # documented spatial heuristic and can legitimately clear a lone transplanted block that has
    # no tampered neighbours.
    assert det_tr.raw_mask[dr, dc] == 1, "transplanted block did not fail HMAC verification"
    print(f"(b) tag-transplant: src_block={src_idx} dst_block={dst_idx} "
          f"still fails HMAC (raw_mask=1), survives refinement={bool(det_tr.block_mask[dr, dc])} -- OK")

    K = (h // block) * (w // block)
    block_idx = K // 2
    forced, i, partner = unrecoverable_demo_tamper(wm, key_str, image_id, block, variant, block_idx)
    det_u = detect_image(forced, key_str, image_id, block, variant, refine=False)  # see main(): isolated pair
    rec_u = recover_image(forced, det_u, block, variant)
    assert rec_u.unrecoverable_mask.sum() > 0, "expected an unrecoverable block"
    ri, ci = divmod(i, cg)
    marker_patch = rec_u.image[ri * block:(ri + 1) * block, ci * block:(ci + 1) * block]
    assert np.all(marker_patch == 0), "unrecoverable block is not the marker value"
    assert not np.array_equal(marker_patch, forced[ri * block:(ri + 1) * block, ci * block:(ci + 1) * block]), \
        "unrecoverable block still shows tampered content instead of the marker"
    print(f"(c) unrecoverable demo: block={i} partner={partner} "
          f"unrecoverable_blocks={int(rec_u.unrecoverable_mask.sum())} -- OK")

    injected, chosen = inject_synthetic_bit_errors(wm, block, n=3, seed=7)
    assert len(chosen) >= 1, "no synthetic bit-errors injected"
    det_syn = detect_image(injected, key_str, image_id, block, variant)
    assert det_syn.raw_mask.sum() >= 1, "injected bit-errors did not surface in raw_mask"
    print(f"(d) synthetic injection: {len(chosen)} isolated blocks flagged pre-refinement -- OK")

    linked = draw_partner_links(wm, np.flatnonzero(det.block_mask.ravel())[:25], det.m, block, cg)
    assert linked.shape[:2] == wm.shape[:2]
    painted = paint_unrecoverable_magenta(rec_u.image, rec_u.unrecoverable_mask, block)
    assert painted.shape[:2] == wm.shape[:2]
    print("(e) visualization helpers (partner links, magenta paint) ran without error -- OK")

    print("=== all smoke assertions passed ===")


if __name__ == "__main__" and not _in_streamlit():
    _smoke_test()
else:
    main()
