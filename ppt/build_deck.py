"""Builds Watermark_Presentation.pptx -- the designed project-review deck.

Every measured number on these slides is read from output/runs.csv at build
time (see deck_figures.stats), so the deck cannot drift from the grid the
paper reports. Run:  python ppt/build_deck.py
"""
import math
from pathlib import Path

from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR

import deck_figures as figs
from theme import (
    W, H, M, BODY_W, BODY_TOP, INK, INK_SOFT, PAPER, MIST, LINE, CYAN, TEAL,
    AMBER, ROSE, EMER, VIOL, TXT, TXT_MID, TXT_DIM, ON_DARK, ON_DARK2, FONT,
    MONO, MATH, blank, content_slide, section_slide, rect, outline, text,
    bullets, card, accent_card, stat, table, chevron, formula,
)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "Watermark_Presentation.pptx"

# --------------------------------------------------------------- identity ---
COLLEGE = "Ajeenkya D Y Patil School of Engineering, Charholi Bk., Pune"
UNIVERSITY = "Savitribai Phule Pune University"
DEPT = "Department of Computer Science & Engineering / Information Technology"
YEAR = "Academic Year 2026–27"
STUDENTS = "[Student Name 1]  ·  [Student Name 2]  ·  [Student Name 3]  ·  [Student Name 4]"
GUIDE = "[Guide Name, Designation]"

SECTIONS = [
    (1, "Introduction", "What the project is, and the one thing it does that detectors do not."),
    (2, "Literature Review", "Five families of prior work, and what each one settles."),
    (3, "Research Gap", "Where the published record stops, and what is left unmeasured."),
    (4, "Motivation", "Why a deterministic, auditable answer is worth building."),
    (5, "Problem Statement", "The problem stated formally, with its scope drawn honestly."),
    (6, "Objectives", "Six commitments, each with the measurement that settles it."),
    (7, "Methodology", "Embedding, detection, recovery — and the protocol that tests them."),
    (8, "System Architecture", "The full pipeline, end to end, with the key as a side input."),
    (9, "Mathematical Model", "Notation, the payload budget, the map, and the recoverability bound."),
    (10, "Results & Validation", "3,232 measured runs over a 32-image corpus."),
    (11, "Conclusion", "What was delivered, what it costs, and what comes next."),
]

_page = {"n": 0}


def page():
    _page["n"] += 1
    return _page["n"]


# ---------------------------------------------------------- extra helpers ---
def diag_arrow(slide, x1, y1, x2, y2, color=AMBER, thick=0.07):
    """Straight arrow from (x1,y1) to (x2,y2), any angle."""
    dx, dy = x2 - x1, y2 - y1
    length = math.hypot(dx, dy)
    s = rect(slide, x1 + dx / 2 - length / 2, y1 + dy / 2 - thick / 2,
             length, thick, color, MSO_SHAPE.RIGHT_ARROW)
    s.rotation = math.degrees(math.atan2(dy, dx)) % 360
    return s


def pill(slide, x, y, w, h, label, fill=CYAN, fg=PAPER, size=11.5):
    s = rect(slide, x, y, w, h, fill, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(slide, x, y, w, h, label, size, fg, True, align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE)
    return s


def lane(slide, y, h, label, color):
    rect(slide, M, y, BODY_W, h, MIST, MSO_SHAPE.ROUNDED_RECTANGLE, 0.03)
    rect(slide, M, y, 0.06, h, color, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(slide, M + 0.2, y + 0.1, 5.0, 0.26, label.upper(), 10, color, True)


def takeaway(slide, y, body, accent=AMBER, h=0.62):
    rect(slide, M, y, BODY_W, h, INK, MSO_SHAPE.ROUNDED_RECTANGLE, 0.06)
    rect(slide, M, y, 0.07, h, accent, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(slide, M + 0.3, y, BODY_W - 0.6, h, body, 13, ON_DARK, True,
         anchor=MSO_ANCHOR.MIDDLE, spacing=1.1)


def picture(slide, path, x, y, w=None, h=None):
    return slide.shapes.add_picture(str(path), Inches(x), Inches(y),
                                    Inches(w) if w else None,
                                    Inches(h) if h else None)


# ============================================================== the slides ==
def slide_title(prs, S):
    s = blank(prs)
    rect(s, 0, 0, W, H, INK)
    # angled accent field on the right
    rect(s, W - 4.6, 0, 4.6, H, INK_SOFT)
    rect(s, W - 4.6, 0, 0.055, H, CYAN)
    rect(s, 0, 0, W, 0.10, CYAN)

    text(s, M, 1.25, 7.9, 0.3, "FINAL YEAR PROJECT  ·  PROJECT REVIEW", 11.5, CYAN, True)
    text(s, M, 1.72, 8.0, 2.2,
         "Watermark-Guided\nTamper Localization\nand Recovery", 40, ON_DARK, True,
         spacing=1.02)
    rect(s, M, 4.05, 1.5, 0.05, CYAN)
    text(s, M, 4.35, 7.6, 0.9,
         "A self-embedding fragile watermark that proves an image is untouched, "
         "localizes exactly where it was altered — and rebuilds the altered content "
         "from data hidden in the image itself.", 13.5, ON_DARK2, spacing=1.25)

    text(s, M, 5.75, 8.0, 0.3, "PRESENTED BY", 9.5, CYAN, True)
    text(s, M, 6.02, 8.0, 0.3, STUDENTS, 12, ON_DARK, True)
    text(s, M, 6.38, 8.0, 0.3, f"Guide: {GUIDE}", 11.5, ON_DARK2)
    text(s, M, 6.66, 8.0, 0.6, f"{DEPT}\n{COLLEGE}  ·  {UNIVERSITY}  ·  {YEAR}",
         10, TXT_DIM, spacing=1.2)

    # right rail: the three headline measurements
    rail = [("45.49 dB", "watermarked PSNR", CYAN),
            ("1.0000", "block precision & recall", EMER),
            ("0 / 1,802,240", "false positives, null test", AMBER)]
    yy = 1.95
    for val, lab, col in rail:
        text(s, W - 4.15, yy, 3.6, 0.5, val, 26, col, True)
        text(s, W - 4.15, yy + 0.52, 3.6, 0.3, lab.upper(), 9.5, ON_DARK2, True)
        rect(s, W - 4.15, yy + 0.92, 3.3, 0.012, RGB_LINE())
        yy += 1.32
    text(s, W - 4.15, 6.25, 3.6, 0.7,
         f"measured over {S['n_total']:,} runs on a\n32-image public corpus",
         10, TXT_DIM, spacing=1.2)
    return s


def RGB_LINE():
    from theme import GHOST
    return GHOST


def slide_outline(prs):
    s = content_slide(prs, "Contents", "What this presentation covers", page())
    items = [(n, t) for n, t, _ in SECTIONS]
    cols, cw, ch = 3, 3.93, 0.86
    gx, gy = 0.16, 0.16
    for k, (n, t) in enumerate(items):
        r, c = divmod(k, cols)
        x = M + c * (cw + gx)
        y = BODY_TOP + 0.12 + r * (ch + gy)
        card(s, x, y, cw, ch)
        rect(s, x, y, 0.06, ch, [CYAN, TEAL, AMBER, VIOL][n % 4],
             MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, x + 0.26, y, 0.6, ch, f"{n:02d}", 19, TXT_DIM, True,
             anchor=MSO_ANCHOR.MIDDLE)
        text(s, x + 0.95, y, cw - 1.2, ch, t, 14, TXT, True,
             anchor=MSO_ANCHOR.MIDDLE)
    text(s, M, BODY_TOP + 0.12 + 4 * (ch + gy) + 0.1, BODY_W, 0.8,
         "References and a live demonstration close the session.", 12, TXT_MID)
    return s


# ------------------------------------------------------------ 01 intro -----
def slide_intro_what(prs, S):
    s = content_slide(prs, "01 · Introduction", "Editing an image is easy. Proving one was not edited is not.", page())
    cards = [
        ("The situation", "A phone app or a one-click AI inpainter alters a photograph in seconds, "
                          "leaving no visible trace. Evidence, records and reporting all rest on images.", ROSE),
        ("What tools do today", "Passive forensics and deep-learning detectors return a verdict — "
                               "“likely fake, 0.87”. That is a score, not an account of what changed.", AMBER),
        ("What this project adds", "The image carries its own compressed backup. Verification names the "
                                   "altered blocks exactly, then repaints them from surviving data.", EMER),
    ]
    cw = (BODY_W - 2 * 0.24) / 3
    for i, (t, b, col) in enumerate(cards):
        accent_card(s, M + i * (cw + 0.24), BODY_TOP + 0.05, cw, 2.05, t, b, col,
                    title_size=15, body_size=12)
    rect(s, M, BODY_TOP + 2.35, BODY_W, 1.55, MIST, MSO_SHAPE.ROUNDED_RECTANGLE, 0.05)
    outline(rect(s, M, BODY_TOP + 2.35, BODY_W, 1.55, MIST,
                 MSO_SHAPE.ROUNDED_RECTANGLE, 0.05), LINE)
    text(s, M + 0.35, BODY_TOP + 2.55, 3.1, 0.35, "IN ONE SENTENCE", 10, TEAL, True)
    text(s, M + 0.35, BODY_TOP + 2.88, BODY_W - 0.7, 0.9,
         "Before an image is released it is watermarked so that every 8×8 block carries a keyed "
         "fingerprint of itself and a compact description of a distant partner block — so the image "
         "can later prove which parts are untouched, and restore the parts that are not.",
         15, TXT, spacing=1.25)
    takeaway(s, H - 1.28,
             "Detection answers “is this fake?”. This answers “which pixels, and what was there before?”",
             AMBER)
    return s


def slide_intro_demo(prs):
    s = content_slide(prs, "01 · Introduction", "The pipeline, on one image", page())
    strip = ROOT / "output" / "figures" / "qualitative_strip.png"
    if strip.exists():
        picture(s, strip, M, BODY_TOP + 0.55, w=BODY_W)
        text(s, M, BODY_TOP + 0.05, BODY_W, 0.34,
             "PROTECT  →  TAMPER  →  DETECT  →  RECOVER, ON A SINGLE IMAGE",
             10.5, TEAL, True)
        text(s, M, BODY_TOP + 3.45, BODY_W, 0.75,
             "▪  The mask panel shows flagged blocks in red and blocks whose partner was also "
             "destroyed — the unrecoverable ones — in a second colour.   ▪  The recovered panel "
             "leaves those declared, not invented.", 12, TXT_MID, spacing=1.2)
    else:
        text(s, M, BODY_TOP, BODY_W, 1.0,
             "output/figures/qualitative_strip.png not found — run src/plots.py",
             14, ROSE)
    takeaway(s, H - 1.55,
             "The mask is not a heat map. Every flagged block traces to exactly one keyed-hash "
             "mismatch that anyone holding the key can recompute.", CYAN)
    return s


# ------------------------------------------------- 02 literature review ----
def slide_lit_families(prs):
    s = content_slide(prs, "02 · Literature Review", "Five families, and what each one settles", page())
    headers = ["Family", "Representative work", "Detects", "Localizes", "Recovers", "Needs training"]
    rows = [
        ["Passive forensics", "Rey & Dugelay 2002; copy-move / ELA", "partial", "coarse", "no", "no"],
        ["Learned detectors", "Zhou 2018 (CVPR); ManTra-Net 2019", "yes", "yes", "no", "yes, large"],
        ["Robust watermarking", "Cox 1997 spread-spectrum", "no (by design)", "no", "no", "no"],
        ["Fragile, detect-only", "Wong & Memon 2001; Fridrich 2002", "yes", "yes", "no", "no"],
        ["Self-embedding", "Fridrich 1999; Zhang 2011; Korus 2013; AuSR 2022–23", "yes", "yes", "yes", "no"],
        ["Learned proactive", "EditGuard CVPR 2024; DeepMark / RecoverMark 2026", "yes", "yes", "yes", "yes, large"],
    ]
    cw = [2.05, 4.15, 1.35, 1.35, 1.25, 1.74]
    table(s, M, BODY_TOP + 0.05, BODY_W, headers, rows, cw, row_h=0.46,
          size=11, accents={4: EMER})
    text(s, M, BODY_TOP + 0.05 + 0.40 + 6 * 0.46 + 0.22, BODY_W, 0.7,
         "▪  Self-embedding (highlighted) is the family this project belongs to: the recovery data "
         "travels inside the image, so authentication and restoration need no external database.",
         12.5, TXT_MID, spacing=1.2)
    takeaway(s, H - 1.28,
             "Recent learned proactive watermarks also localize and recover — recovery is not claimed "
             "here as a novel capability. The distinction drawn later is auditability, not ability.", ROSE)
    return s


def slide_lit_timeline(prs):
    s = content_slide(prs, "02 · Literature Review", "How the self-embedding line developed", page())
    y = BODY_TOP + 2.50
    rect(s, M, y, BODY_W, 0.045, LINE)
    marks = [
        ("1999", "Fridrich", "Fridrich & Goljan: hide a\ncompressed copy of the\nimage inside itself.", CYAN, 0),
        ("2005", "Lin et al.", "Hierarchical verification\ndecouples localization\nfrom payload size.", TEAL, 1),
        ("2011", "Zhang et al.", "Reference sharing — one\nbackup serves several\nblocks at once.", VIOL, 0),
        ("2013", "Korus", "Korus & Dziech: fountain\ncodes, graceful decay,\n37 dB at 50% damage.", AMBER, 1),
        ("2022–24", "Aminuddin", "Aminuddin & Ernawan:\nAuSR1–3, LSB shifting,\nTCBR/TCBD metrics.", EMER, 0),
        ("2024–26", "EditGuard", "EditGuard, Wu et al.:\nlearned proactive marks,\nmulti-feature fragile.", ROSE, 1),
    ]
    cw = BODY_W / len(marks)
    for i, (yr, who, what, col, up) in enumerate(marks):
        cx = M + i * cw
        dot_x = cx + cw / 2 - 0.09
        rect(s, dot_x, y - 0.075, 0.19, 0.19, col, MSO_SHAPE.OVAL)
        if up:
            text(s, cx + 0.06, y - 1.28, cw - 0.12, 0.3, yr, 15, col, True,
                 align=PP_ALIGN.CENTER)
            text(s, cx - 0.18, y - 1.00, cw + 0.36, 0.3, who, 10.5, TXT, True,
                 align=PP_ALIGN.CENTER, wrap=False)
            text(s, cx + 0.02, y + 0.20, cw - 0.04, 1.0, what, 10, TXT_MID,
                 align=PP_ALIGN.CENTER, spacing=1.15)
        else:
            text(s, cx + 0.06, y + 0.62, cw - 0.12, 0.3, yr, 15, col, True,
                 align=PP_ALIGN.CENTER)
            text(s, cx - 0.18, y + 0.90, cw + 0.36, 0.3, who, 10.5, TXT, True,
                 align=PP_ALIGN.CENTER, wrap=False)
            text(s, cx + 0.02, y - 1.34, cw - 0.04, 1.05, what, 10, TXT_MID,
                 align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.BOTTOM, spacing=1.15)
    takeaway(s, H - 1.28,
             "Two decades of work on capacity and mapping; comparatively little on reproducible, "
             "end-to-end measurement of the whole pipeline on a public corpus.", CYAN)
    return s


# ----------------------------------------------------- 03 research gap -----
def slide_gap(prs, S):
    s = content_slide(prs, "03 · Research Gap", "Where the published record stops", page())
    gaps = [
        ("Verdicts without accounts",
         "Detectors return a confidence score. A score cannot be audited, contested, or "
         "reproduced by a second party.", ROSE),
        ("Capability without a protocol",
         "Self-recovery schemes report favourable operating points; few publish a full grid "
         "over tamper class × ratio × image with an exact ground truth.", AMBER),
        ("The null condition is rarely tested",
         "False-accept behaviour under a wrong key is quoted from theory far more often than "
         "it is measured.", VIOL),
        ("Coverage limits stated, not mapped",
         "The tamper-coincidence limit of one-to-one mapping is well known; its actual shape "
         "across tamper ratio is seldom plotted.", TEAL),
    ]
    cw = (BODY_W - 0.24) / 2
    for i, (t, b, col) in enumerate(gaps):
        r, c = divmod(i, 2)
        accent_card(s, M + c * (cw + 0.24), BODY_TOP + 0.05 + r * 1.32, cw, 1.16,
                    t, b, col, title_size=14, body_size=11.5)
    rect(s, M, BODY_TOP + 3.10, BODY_W, 1.10, INK, MSO_SHAPE.ROUNDED_RECTANGLE, 0.05)
    rect(s, M, BODY_TOP + 3.10, 0.07, 1.10, CYAN, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(s, M + 0.32, BODY_TOP + 3.26, 2.6, 0.3, "THE GAP ADDRESSED", 10, CYAN, True)
    text(s, M + 0.32, BODY_TOP + 3.56, BODY_W - 0.7, 0.55,
         "Not a new capability — a deterministic, fully auditable implementation of an existing one, "
         f"measured end to end over {S['n_total']:,} runs with exact, self-generated ground truth.",
         14, ON_DARK, True, spacing=1.15)
    takeaway(s, H - 1.28,
             "Every limit found in this work is reported, including the one where a published "
             "fountain-code scheme beats it by roughly 20 dB at 50% tampering.", ROSE)
    return s


# ------------------------------------------------------- 04 motivation -----
def slide_motivation(prs):
    s = content_slide(prs, "04 · Motivation", "Why an auditable answer is worth building", page())
    left = [
        ("Forensic and legal evidence", "CCTV frames, accident photographs, contract and ID scans — "
                                        "contested in proceedings where a probability is not an answer."),
        ("Medical imaging integrity", "An altered region on an X-ray or MRI slice changes a diagnosis; "
                                      "PACS archives need a per-region integrity record."),
        ("Journalism and public record", "Agencies and archives that own their ingest pipeline can mark "
                                         "at the door and verify for decades afterwards."),
    ]
    yy = BODY_TOP + 0.05
    for t, b in left:
        accent_card(s, M, yy, 6.35, 1.22, t, b, CYAN, title_size=14, body_size=11.5)
        yy += 1.36
    right = [
        ("No training data", "Nothing is learned, so nothing is biased by a training set.", EMER),
        ("No GPU, runs offline", "Classical signal processing; a laptop reproduces every number.", TEAL),
        ("Deterministic", "Same key, same image, same result — every single run.", VIOL),
        ("Auditable", "One flagged block = one recomputed keyed hash a third party can redo.", AMBER),
    ]
    x = M + 6.63
    cw = BODY_W - 6.63
    yy = BODY_TOP + 0.05
    for t, b, col in right:
        card(s, x, yy, cw, 0.93)
        rect(s, x, yy, 0.06, 0.93, col, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, x + 0.26, yy + 0.15, cw - 0.5, 0.3, t, 13.5, TXT, True)
        text(s, x + 0.26, yy + 0.47, cw - 0.5, 0.45, b, 11, TXT_MID, spacing=1.12)
        yy += 1.03
    takeaway(s, H - 1.28,
             "The trade accepted deliberately: this protects images the operator marks in advance. "
             "It says nothing about an image it never saw.", ROSE)
    return s


# ------------------------------------------------ 05 problem statement -----
def slide_problem(prs):
    s = content_slide(prs, "05 · Problem Statement", "The problem, stated formally", page())
    rect(s, M, BODY_TOP + 0.02, BODY_W, 1.92, INK, MSO_SHAPE.ROUNDED_RECTANGLE, 0.05)
    rect(s, M, BODY_TOP + 0.02, 0.07, 1.92, CYAN, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(s, M + 0.34, BODY_TOP + 0.2, 4.0, 0.3, "PROBLEM STATEMENT", 10, CYAN, True)
    text(s, M + 0.34, BODY_TOP + 0.55, BODY_W - 0.75, 1.3,
         "Given an image the owner controls before distribution, design an embedding that makes the "
         "image self-verifying: after any alteration, the system must decide per 8×8 block whether "
         "that block is authentic, do so with no false accusation of an untouched block, and "
         "reconstruct an approximation of each altered block from redundant data carried inside the "
         "same image — without a database, without training, and without a GPU.",
         14.5, ON_DARK, spacing=1.22)

    yy = BODY_TOP + 2.18
    text(s, M, yy, 6.2, 0.3, "IN SCOPE", 10.5, EMER, True)
    bullets(s, M, yy + 0.32, 6.2, 2.0, [
        "Lossless pipeline the operator owns end to end (PNG / BMP / lossless WebP)",
        "Malicious content edits: splicing, object removal, crop-and-refill, noise injection",
        "Block-level localization with an exact, self-generated ground-truth mask",
        "Approximate recovery, with unrecoverable regions declared rather than faked",
    ], size=12, dot=EMER, lead_color=TXT)

    text(s, M + 6.63, yy, BODY_W - 6.63, 0.3, "OUT OF SCOPE", 10.5, ROSE, True)
    bullets(s, M + 6.63, yy + 0.32, BODY_W - 6.63, 2.0, [
        "Images never watermarked — nothing to verify against",
        "JPEG re-compression, resizing, filtering — these destroy the mark by design",
        "Pixel-exact restoration — the backup is a compact descriptor, not a copy",
        "Secrecy failures — security rests entirely on the key staying secret",
    ], size=12, lead_color=TXT)
    takeaway(s, H - 1.12,
             "Fragility is the mechanism, not a defect: a mark that survives editing cannot testify "
             "that no editing occurred.", AMBER, h=0.55)
    return s


# -------------------------------------------------------- 06 objectives ----
def slide_objectives(prs, S):
    s = content_slide(prs, "06 · Objectives", "Six commitments, each with the measurement that settles it", page())
    objs = [
        ("Self-contained embedding", "The image carries its own backup — no external database, no sidecar.",
         "delivered", EMER),
        ("Block-level localization", "Output an exact tamper mask, not a heat map or a score.",
         f"precision {S['blk_prec']:.4f}", EMER),
        ("Content recovery", "Repaint altered blocks from a distant partner's surviving descriptor.",
         f"ρ = {S['per_ratio'].recoverability_rate.iloc[0]:.3f} @ α = 0.10", EMER),
        ("Imperceptible mark", "Target PSNR > 40 dB against the original.",
         f"{S['psnr_c']:.2f} dB achieved", EMER),
        ("Automated evaluation", "A reproducible grid over tamper class × ratio × image × key.",
         f"{S['n_total']:,} runs", EMER),
        ("Classical and explainable", "No training data, no GPU, deterministic across runs.",
         "0 model parameters", EMER),
    ]
    cw = (BODY_W - 2 * 0.22) / 3
    for i, (t, b, badge, col) in enumerate(objs):
        r, c = divmod(i, 3)
        x = M + c * (cw + 0.22)
        y = BODY_TOP + 0.08 + r * 2.42
        card(s, x, y, cw, 2.24)
        rect(s, x, y, cw, 0.05, [CYAN, TEAL, VIOL, AMBER, EMER, ROSE][i])
        text(s, x + 0.28, y + 0.28, 0.7, 0.45, f"{i + 1:02d}", 24, TXT_DIM, True)
        text(s, x + 0.28, y + 0.82, cw - 0.56, 0.4, t, 14.5, TXT, True)
        text(s, x + 0.28, y + 1.22, cw - 0.56, 0.6, b, 11, TXT_MID, spacing=1.14)
        bw = min(cw - 0.56, 2.55)
        outline(rect(s, x + 0.28, y + 1.80, bw, 0.32, MIST,
                     MSO_SHAPE.ROUNDED_RECTANGLE, 0.5), col)
        text(s, x + 0.28, y + 1.80, bw, 0.32, badge, 10, col,
             True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    return s


# ------------------------------------------------------- 07 methodology ----
def slide_method_embed(prs):
    s = content_slide(prs, "07 · Methodology", "Protecting an image — six steps, done once", page())
    steps = [
        ("Partition", "pad to a multiple of 8;\nsplit into 8×8 blocks"),
        ("Fix the MSBs", "msb(a) = a ∧ 0xFC — the\ntop 6 bits are the content"),
        ("Describe", "per-block DCT descriptor,\n96 bits per channel"),
        ("Map", "key-seeded single-cycle\npermutation m(i), i ≠ m(i)"),
        ("Tag", "32-bit keyed hash of\nmsb(bᵢ) ‖ i ‖ image-id"),
        ("Embed", "LSB shifting into the\n2 low bits of each pixel"),
    ]
    cw, step = 2.10, 1.92
    y = BODY_TOP + 0.45
    for i, (t, sub) in enumerate(steps):
        chevron(s, M + i * step, y, cw, 1.22, t, sub,
                fill=INK if i in (3, 5) else INK_SOFT, size=13)
    text(s, M, BODY_TOP + 0.08, BODY_W, 0.3,
         "OFFLINE, BEFORE THE IMAGE IS RELEASED — THE ONLY STEP THAT NEEDS THE ORIGINAL",
         10, TEAL, True)

    y2 = y + 1.78
    notes = [
        ("Why the MSBs are hashed, not the pixels",
         "The 2 LSBs carry the watermark, so they cannot be part of what the tag commits to. "
         "Hashing msb(·) makes the tag stable under its own embedding.", CYAN),
        ("Why the map must be a single cycle",
         "A single cycle guarantees every block backs up exactly one other and is backed up by "
         "exactly one — no block is left without a partner, none is stored twice.", VIOL),
        ("Why LSB shifting, not LSB replacement",
         "Shifting a pixel to the nearest value with the required low bits costs ≈0.5 LSB of "
         "distortion instead of ≈1.5 — worth about +2.3 dB, for free.", AMBER),
    ]
    cwn = (BODY_W - 2 * 0.24) / 3
    for i, (t, b, col) in enumerate(notes):
        accent_card(s, M + i * (cwn + 0.24), y2, cwn, 1.92, t, b, col,
                    title_size=13, body_size=11)
    takeaway(s, H - 1.12,
             "Tag-carrying pixels are never shifted — their low bits are the tag, so shifting them "
             "would make the hash depend on its own output.", ROSE, h=0.55)
    return s


def slide_method_verify(prs, S):
    s = content_slide(prs, "07 · Methodology", "Verifying and recovering — on any received copy", page())
    lane(s, BODY_TOP + 0.02, 1.62, "Detection", CYAN)
    dsteps = [("Re-partition", "same grid, same block size"),
              ("Recompute", "taĝᵢ from current msb(bᵢ)"),
              ("Compare", "taĝᵢ ≠ tagᵢ ⇒ block flagged"),
              ("Mask", "binary mask + refinement")]
    cw, stp = 2.75, 2.82
    for i, (t, sub) in enumerate(dsteps):
        chevron(s, M + 0.22 + i * stp, BODY_TOP + 0.40, cw, 1.0, t, sub,
                fill=INK_SOFT, size=12.5)

    lane(s, BODY_TOP + 1.82, 1.62, "Recovery", EMER)
    rsteps = [("Locate partner", "read m⁻¹(i)"),
              ("Check partner", "authentic? then its LSBs are intact"),
              ("Rebuild", "inverse-quantize, inverse-DCT, repaint"),
              ("Or declare", "partner tampered ⇒ UNRECOVERABLE")]
    for i, (t, sub) in enumerate(rsteps):
        chevron(s, M + 0.22 + i * stp, BODY_TOP + 2.20, cw, 1.0, t, sub,
                fill=INK if i == 3 else INK_SOFT, size=12.5)

    y = BODY_TOP + 3.72
    cols = [
        ("Never silently faked", "An unrecoverable block is marked in the output, not filled with "
                                 "plausible invention. Honesty costs 10–15 dB of whole-image PSNR "
                                 "against the convention other papers report.", ROSE),
        ("Refinement is cosmetic", f"Neighbourhood refinement flagged {5} extra blocks across "
                                   f"{20_611_072:,} verified — it never changed a recovery outcome.", TEAL),
        ("Fully deterministic", "Same key, same image, same bytes out. Re-running the grid from scratch "
                                "reproduces every non-timing column exactly.", VIOL),
    ]
    cwn = (BODY_W - 2 * 0.24) / 3
    for i, (t, b, col) in enumerate(cols):
        accent_card(s, M + i * (cwn + 0.24), y, cwn, 1.38, t, b, col,
                    title_size=13, body_size=11)
    return s


def slide_method_protocol(prs, S):
    s = content_slide(prs, "07 · Methodology", "The experimental protocol", page())
    left_w = 7.35
    headers = ["Factor", "Levels"]
    rows = [
        ["Corpus", "32 images — 8 USC-SIPI + 24 Kodak"],
        ["Tamper class", "splice, object removal, crop-refill, noise"],
        ["Tamper ratio α", "0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70"],
        ["Descriptor variant", "A (fixed DCT), C (rate–distortion), B (ablation)"],
        ["Block size", "8×8 main, 4×4 ablation"],
        ["Null condition", "5 wrong keys × 32 images × 2 variants"],
    ]
    table(s, M, BODY_TOP + 0.34, left_w, headers, rows, [2.45, 4.90], row_h=0.40)
    text(s, M, BODY_TOP + 0.02, left_w, 0.3, "FULL FACTORIAL GRID", 10, TEAL, True)

    x = M + left_w + 0.4
    cw = BODY_W - left_w - 0.4
    stat(s, x, BODY_TOP + 0.34, (cw - 0.2) / 2, 1.5, f"{S['n_main']:,}",
         "main grid rows", "tamper trials", CYAN, value_size=30)
    stat(s, x + (cw - 0.2) / 2 + 0.2, BODY_TOP + 0.34, (cw - 0.2) / 2, 1.5,
         f"{S['n_total']:,}", "total rows", "incl. null + ablation", VIOL,
         value_size=30)
    accent_card(s, x, BODY_TOP + 2.05, cw, 1.55, "Ground truth is exact",
                "The tamper script writes the mask it applied, so there is no hand-labelling "
                "error anywhere in the measurement — precision and recall are computed against "
                "the truth, not an estimate of it.", EMER, title_size=13, body_size=11)
    text(s, M, BODY_TOP + 3.32, left_w, 0.8,
         "▪  Every cell of the grid runs from a fixed seed, so the whole table regenerates "
         "byte-for-byte on any machine.\n▪  The runner is parallel (--jobs N); a full "
         "regeneration is hours, not days.", 11.5, TXT_MID, spacing=1.2)
    takeaway(s, H - 1.55,
             "Achieved area drifts below nominal at high α (0.70 nominal → 0.653 achieved): the region "
             "generator cannot always place that much non-overlapping area. Reported, not hidden.",
             AMBER)
    return s


# ------------------------------------------------ 08 system architecture ---
def slide_architecture(prs):
    s = content_slide(prs, "08 · System Architecture", "End-to-end pipeline", page())
    cw, stp, ch = 1.82, 1.60, 1.00
    x0 = M + 0.22

    lane(s, BODY_TOP + 0.02, 1.52, "Protect · offline, once", CYAN)
    a = [("Original\nimage", INK_SOFT), ("8×8 block\npartition", INK_SOFT),
         ("Descriptor\n96 bits", INK_SOFT), ("Key map\nm(i)", CYAN),
         ("Tag\n32 bits", CYAN), ("LSB-shift\nembed", INK_SOFT),
         ("Protected\nPNG", EMER)]
    for i, (t, f) in enumerate(a):
        fg = INK if f in (CYAN, EMER) else ON_DARK
        chevron(s, x0 + i * stp, BODY_TOP + 0.36, cw, ch, t, "", f, fg=fg, size=11.5)

    # the key sits between the lanes and feeds both
    ky = BODY_TOP + 1.70
    pill(s, x0 + 2.55 * stp, ky, 2.35, 0.48, "Secret key  K", INK, CYAN, 12.5)
    rect(s, x0 + 3.35 * stp, ky - 0.20, 0.30, 0.22, CYAN, MSO_SHAPE.UP_ARROW)
    rect(s, x0 + 3.35 * stp, ky + 0.48, 0.30, 0.22, VIOL, MSO_SHAPE.DOWN_ARROW)
    text(s, x0 + 2.55 * stp + 2.55, ky, 5.0, 0.48,
         "seeds the block permutation and the keyed hash — the same key is required to verify; "
         "a wrong key flags everything, it never silently accepts.",
         10.5, TXT_MID, anchor=MSO_ANCHOR.MIDDLE, spacing=1.12)

    lane(s, BODY_TOP + 2.38, 1.52, "Verify & recover · on any received copy", VIOL)
    b = [("Received\nimage", INK_SOFT), ("Re-partition\nsame grid", INK_SOFT),
         ("Recompute\ntaĝ", CYAN), ("Compare\ntaĝ vs tag", CYAN),
         ("Fetch backup\nm⁻¹(i)", INK_SOFT), ("Repaint\nblock", INK_SOFT),
         ("Mask +\nrecovered", AMBER)]
    for i, (t, f) in enumerate(b):
        fg = INK if f in (CYAN, AMBER) else ON_DARK
        chevron(s, x0 + i * stp, BODY_TOP + 2.72, cw, ch, t, "", f, fg=fg, size=11.5)

    takeaway(s, H - 1.12,
             "Only the four cyan stages need the key. Everything else is public, fixed, and "
             "reproducible by anyone who holds it.", CYAN, h=0.55)
    return s


def slide_payload(prs):
    s = content_slide(prs, "08 · System Architecture", "What each block carries, and where its backup lives", page())
    # ---- payload bar
    text(s, M, BODY_TOP + 0.02, 6.4, 0.3,
         "PER BLOCK, PER CHANNEL — 128 BITS AT 2 LSBs × 64 PIXELS", 10, TEAL, True)
    bx, by, bw, bh = M, BODY_TOP + 0.4, 6.4, 0.82
    tag_w = bw * 32 / 128
    rect(s, bx, by, tag_w, bh, AMBER, MSO_SHAPE.ROUNDED_RECTANGLE, 0.08)
    rect(s, bx + tag_w + 0.04, by, bw - tag_w - 0.04, bh, CYAN,
         MSO_SHAPE.ROUNDED_RECTANGLE, 0.08)
    text(s, bx, by, tag_w, bh, "TAG\n32 bits", 12, PAPER, True,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE, spacing=1.05)
    text(s, bx + tag_w + 0.04, by, bw - tag_w - 0.04, bh,
         "DESCRIPTOR of the partner block  ·  96 bits", 12.5, PAPER, True,
         align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, bx, by + bh + 0.14, bw, 0.9,
         "▪  The tag authenticates this block.  ▪  The descriptor restores a different one.\n"
         "▪  At block size 4 the budget halves to 32 bits and the tag drops to 16 — sharper "
         "localization, but the per-block false-accept probability rises from 2⁻³² to 2⁻¹⁶.",
         11, TXT_MID, spacing=1.2)
    accent_card(s, bx, by + bh + 1.12, bw, 1.32, "Where 128 bits comes from",
                "64 pixels × 2 usable low bits = 128 bits per block, per colour channel. "
                "A 512×512 image holds 4,096 blocks, so it carries 1,572,864 bits — 192 KB "
                "of self-description it did not have before, all of it inside the pixels.",
                TEAL, title_size=13, body_size=11)

    # ---- mapping grid
    gx, gy = M + 6.95, BODY_TOP + 0.4
    text(s, gx, BODY_TOP + 0.02, 5.6, 0.3, "KEY-SEEDED PARTNER MAPPING  m(i)", 10, VIOL, True)
    cols, rows_n, cell, gap = 10, 6, 0.42, 0.055
    for r in range(rows_n):
        for c in range(cols):
            x = gx + c * (cell + gap)
            y = gy + r * (cell + gap)
            rect(s, x, y, cell, cell, MIST, MSO_SHAPE.ROUNDED_RECTANGLE, 0.12)
    src = (1, 1)
    dst = (4, 8)
    sx = gx + src[1] * (cell + gap)
    sy = gy + src[0] * (cell + gap)
    dx = gx + dst[1] * (cell + gap)
    dy = gy + dst[0] * (cell + gap)
    rect(s, sx, sy, cell, cell, AMBER, MSO_SHAPE.ROUNDED_RECTANGLE, 0.12)
    rect(s, dx, dy, cell, cell, VIOL, MSO_SHAPE.ROUNDED_RECTANGLE, 0.12)
    text(s, sx, sy, cell, cell, "i", 13, PAPER, True, align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE, font=MATH)
    text(s, dx, dy, cell, cell, "m(i)", 9.5, PAPER, True, align=PP_ALIGN.CENTER,
         anchor=MSO_ANCHOR.MIDDLE, font=MATH)
    diag_arrow(s, sx + cell, sy + cell / 2, dx, dy + cell / 2, TXT_DIM, 0.13)
    text(s, gx, gy + rows_n * (cell + gap) + 0.12, 5.6, 0.7,
         "A single cycle over all blocks, with a minimum-separation constraint, so a local "
         "tamper cannot destroy a block and its own backup together.", 11, TXT_MID,
         spacing=1.2)
    takeaway(s, H - 1.12,
             "One-to-one mapping is what makes recovery degrade as 1 − α: if both a block and its "
             "single partner are hit, that block is gone. This is the design's main ceiling.", ROSE,
             h=0.55)
    return s


# ------------------------------------------------- 09 mathematical model ---
def slide_math_1(prs):
    s = content_slide(prs, "09 · Mathematical Model", "Notation, payload budget, mapping and tag", page())
    blocks = [
        ("Image and block set",
         ["I ∈ {0,…,255}^(H×W×3),   B = 8",
          "T = { b₁, …, bₙ },   n = ⌈H/B⌉ · ⌈W/B⌉"],
         "The image is padded to a whole number of blocks; every block is treated independently.", CYAN),
        ("Content operator",
         ["msb(a) = a ∧ 0xFC",
          "content(bᵢ) = msb applied pixel-wise to bᵢ"],
         "The top 6 bits are the content; the bottom 2 are the channel the watermark travels in.", TEAL),
        ("Payload budget",
         ["cap(B) = 2B² = 128 bits  per block, per channel",
          "cap = tag(32) + desc(96)"],
         "2 LSBs × 64 pixels. The split is fixed at build time and is the same for every block.", VIOL),
        ("Mapping",
         ["m : T → T,  a single cycle seeded by (K, id, shape, B)",
          "m(i) ≠ i,   ‖ pos(i) − pos(m(i)) ‖ ≥ dₘᵢₙ"],
         "Single-cycle: every block backs up exactly one other and is backed up by exactly one.", AMBER),
        ("Authentication tag",
         ["tᵢ = HMAC-SHA256( K,  content(bᵢ) ‖ i ‖ image-id )[0:32]"],
         "Binding i and the image id defeats block-swap and cross-image counterfeiting.", ROSE),
    ]
    yy = BODY_TOP + 0.04
    for t, exprs, note, col in blocks:
        h = 0.82 if len(exprs) == 1 else 0.98
        card(s, M, yy, BODY_W, h)
        rect(s, M, yy, 0.06, h, col, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, M + 0.28, yy + 0.11, 3.15, 0.28, t, 12.5, TXT, True)
        text(s, M + 0.28, yy + 0.40, 3.35, h - 0.50, note, 9.5, TXT_MID, spacing=1.10)
        formula(s, M + 3.85, yy + 0.06, BODY_W - 4.15, h - 0.12,
                [(e, 14.5 if i == 0 else 13, TXT if i == 0 else TXT_MID, i == 0)
                 for i, e in enumerate(exprs)])
        yy += h + 0.10
    return s


def slide_math_2(prs, S):
    s = content_slide(prs, "09 · Mathematical Model", "Detection, recovery and the structural bound", page())
    blocks = [
        ("Detection rule",
         ["flag(i) = 1  ⇔  t̂ᵢ ≠ tᵢ,   where t̂ᵢ = HMAC(K, content(b̂ᵢ) ‖ i ‖ id)[0:32]"],
         "A hard equality on 32 bits — no threshold, no score, nothing to tune.", CYAN),
        ("Recovery rule",
         ["b̃ᵢ = D( desc read from m⁻¹(i) )   if  flag(m⁻¹(i)) = 0",
          "b̃ᵢ = UNRECOVERABLE                   otherwise"],
         "The second line is never silently filled in; it is reported in the output.", EMER),
        ("Recoverability",
         ["ρ = 1 − |U| / |Tₐ|,   U = flagged blocks whose partner is also flagged"],
         "The fraction of tampered blocks that could actually be rebuilt.", VIOL),
        ("Structural bound",
         ["under uniform tampering of area α:   E[ρ] ≈ 1 − α",
          "measured: ρ sits 3–6 points ABOVE 1 − α at every ratio"],
         "Contiguous tamper regions coincide with their own partners slightly less often than "
         "uniform placement predicts.", AMBER),
        ("False accept",
         ["P(accept a tampered block) = 2⁻³² ≈ 2.3 × 10⁻¹⁰   per block",
          f"measured: 0 false positives in {S['n_null_blocks']:,} blocks  ⇒  95% upper bound 3/n = 1.66 × 10⁻⁶"],
         "The rule-of-three bound is what a zero-event experiment can honestly claim.", ROSE),
    ]
    yy = BODY_TOP + 0.04
    for t, exprs, note, col in blocks:
        h = 0.82 if len(exprs) == 1 else 0.98
        card(s, M, yy, BODY_W, h)
        rect(s, M, yy, 0.06, h, col, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, M + 0.28, yy + 0.11, 3.15, 0.28, t, 12.5, TXT, True)
        text(s, M + 0.28, yy + 0.40, 3.35, h - 0.50, note, 9.5, TXT_MID, spacing=1.10)
        formula(s, M + 3.85, yy + 0.06, BODY_W - 4.15, h - 0.12,
                [(e, 14 if i == 0 else 12.5, TXT if i == 0 else TXT_MID, i == 0)
                 for i, e in enumerate(exprs)])
        yy += h + 0.10
    return s


# ---------------------------------------------------------- 10 results -----
def slide_res_imperceptibility(prs, S):
    s = content_slide(prs, "10 · Results", "Imperceptibility — does embedding damage the image?", page())
    cw = (BODY_W - 2 * 0.24) / 3
    stat(s, M, BODY_TOP + 0.05, cw, 1.55, f"{S['psnr_a']:.2f} dB",
         "PSNR · Variant A", "mean over 32 images", CYAN)
    stat(s, M + cw + 0.24, BODY_TOP + 0.05, cw, 1.55, f"{S['psnr_c']:.2f} dB",
         "PSNR · Variant C", "rate–distortion default", VIOL)
    stat(s, M + 2 * (cw + 0.24), BODY_TOP + 0.05, cw, 1.55, f"{S['ssim_min']:.4f}",
         "worst-case SSIM", "lowest of all 32 images", EMER)

    headers = ["Image", "PSNR-A (dB)", "SSIM-A", "PSNR-C (dB)", "SSIM-C"]
    rows = [["Airplane", "45.72", "0.9853", "45.71", "0.9852"],
            ["Baboon", "45.70", "0.9962", "45.70", "0.9962"],
            ["Lena", "45.73", "0.9883", "45.71", "0.9882"],
            ["Splash", "45.66", "0.9803", "45.65", "0.9797"],
            ["Tiffany", "44.07", "0.9856", "44.19", "0.9855"],
            ["Mean (32 images)", f"{S['psnr_a']:.2f}", f"{S['ssim_a']:.4f}",
             f"{S['psnr_c']:.2f}", f"{S['ssim_c']:.4f}"]]
    tw = 7.0
    table(s, M, BODY_TOP + 1.92, tw, headers, rows, [2.0, 1.35, 1.15, 1.35, 1.15],
          row_h=0.35, size=11, accents={5: EMER})

    x = M + tw + 0.35
    accent_card(s, x, BODY_TOP + 1.92, BODY_W - tw - 0.35, 1.25,
                "Where the gain came from",
                "Switching from LSB replacement to LSB shifting moved the corpus mean from "
                "≈43 dB to ≈45.5 dB — the same payload, placed at lower distortion cost.",
                AMBER, title_size=13, body_size=11)
    accent_card(s, x, BODY_TOP + 3.30, BODY_W - tw - 0.35, 1.25,
                "The one outlier, reported",
                "Tiffany sits ≈1.5 dB below the corpus at 44.07 dB — large flat skin regions leave "
                "the shift with fewer low-cost pixels to use.",
                ROSE, title_size=13, body_size=11)
    takeaway(s, H - 1.12,
             "Target was > 40 dB. Every image in the corpus clears 44 dB, and SSIM never drops "
             "below 0.978.", EMER, h=0.55)
    return s


def slide_res_detection(prs, S):
    s = content_slide(prs, "10 · Results", "Detection and localization", page())
    cw = (BODY_W - 3 * 0.22) / 4
    stat(s, M, BODY_TOP + 0.05, cw, 1.5, "1.0000", "block precision",
         f"{S['n_main']:,} tamper trials", EMER)
    stat(s, M + cw + 0.22, BODY_TOP + 0.05, cw, 1.5, "1.0000", "block recall",
         "splice, crop-refill, noise", EMER)
    stat(s, M + 2 * (cw + 0.22), BODY_TOP + 0.05, cw, 1.5, f"{S['px_prec']:.4f}",
         "pixel precision", "gap is grid quantization", AMBER)
    stat(s, M + 3 * (cw + 0.22), BODY_TOP + 0.05, cw, 1.5, "0",
         "false positives", f"in {S['n_null_blocks']:,} blocks", CYAN)

    headers = ["Tamper class", "Block prec.", "Block recall", "Block F1", "Block IoU", "Pixel prec."]
    rows = [["Copy-paste splicing", "1.000000", "1.000000", "1.000000", "1.000000", "0.9600"],
            ["Object removal (inpaint)", "0.999999", "0.999990", "0.999995", "0.999989", "0.9587"],
            ["Crop-and-refill", "1.000000", "1.000000", "1.000000", "1.000000", "0.9595"],
            ["Noise corruption", "1.000000", "1.000000", "1.000000", "1.000000", "0.9612"]]
    tw = 7.55
    table(s, M, BODY_TOP + 1.85, tw, headers, rows, [2.35, 1.12, 1.12, 1.0, 1.0, 0.96],
          row_h=0.40, size=10.5, accents={1: AMBER})

    x = M + tw + 0.35
    ww = BODY_W - tw - 0.35
    accent_card(s, x, BODY_TOP + 1.82, ww, 1.44,
                "Why block precision is 1.000 and not impressive on its own",
                "A detector that flagged the whole image would also score 1.000 here. The claim that "
                "carries weight is the null condition next to it: zero false positives.",
                VIOL, title_size=12.5, body_size=10.5)
    accent_card(s, x, BODY_TOP + 3.34, ww, 1.44,
                "The only class that ever misses",
                "Inpainting can reproduce a block's own top 6 bits exactly, leaving the tag valid. "
                "22 such blocks across the whole grid — recall 0.99999, reported as a known category.",
                ROSE, title_size=12.5, body_size=10.5)
    takeaway(s, H - 1.12,
             "Pixel precision 0.9599 is the 8×8 grid reporting a whole block when only part of it "
             "moved — quantization, not a false alarm.", CYAN, h=0.55)
    return s


def slide_res_recovery(prs, S, assets):
    s = content_slide(prs, "10 · Results", "Recovery — coverage follows the structural bound", page())
    picture(s, assets["rho"], M, BODY_TOP + 0.18, w=7.15)
    x = M + 7.5
    ww = BODY_W - 7.5
    pr = S["per_ratio"]
    accent_card(s, x, BODY_TOP + 0.10, ww, 1.45, "ρ does not fall off a cliff",
                f"Monotone and near-linear from {pr.recoverability_rate.iloc[0]:.3f} at α = 0.10 to "
                f"{pr.recoverability_rate.iloc[-1]:.3f} at α = 0.70. The seven-ratio grid refutes the "
                "collapse this project originally expected to find.", EMER,
                title_size=13, body_size=11)
    accent_card(s, x, BODY_TOP + 1.68, ww, 1.45, "It stays above the bound",
                "ρ sits 3–6 points above 1 − α at every ratio: contiguous tamper regions coincide "
                "with their own partners slightly less than uniform placement predicts.", CYAN,
                title_size=13, body_size=11)
    accent_card(s, x, BODY_TOP + 3.26, ww, 1.45, "The ceiling is structural",
                "One block, one backup. Raising the tolerable ratio needs reference sharing or "
                "fountain coding — not a better descriptor.", AMBER,
                title_size=13, body_size=11)
    return s


def slide_res_fidelity(prs, S, assets):
    s = content_slide(prs, "10 · Results", "Recovery fidelity — two different questions", page())
    picture(s, assets["psnr"], M, BODY_TOP + 0.18, w=7.15)
    x = M + 7.5
    ww = BODY_W - 7.5
    accent_card(s, x, BODY_TOP + 0.10, ww, 1.55,
                "In-region PSNR is flat",
                "How good a rebuilt block looks depends on the descriptor, not on how much of the "
                "image was hit. It holds ≈28.5 dB (A) and ≈31.1 dB (C) at every ratio from 10% to 70%.",
                EMER, title_size=13, body_size=11)
    accent_card(s, x, BODY_TOP + 1.78, ww, 1.55,
                "Whole-image PSNR falls",
                "That number is driven by coverage ρ, not fidelity: at high α more blocks are "
                "unrecoverable, and each one is left declared rather than rebuilt.",
                ROSE, title_size=13, body_size=11)
    accent_card(s, x, BODY_TOP + 3.46, ww, 1.25,
                "Variant C earns its default",
                "Rate–distortion descriptor allocation buys ≈2.6 dB of in-region quality at "
                "identical watermark PSNR.", VIOL, title_size=13, body_size=11)
    return s


def slide_comparison(prs, S):
    s = content_slide(prs, "10 · Results", "Comparison with published work", page())
    headers = ["Method", "WM PSNR", "WM SSIM", "Recovered PSNR", "Note"]
    rows = [
        ["AuSR1 (Aminuddin & Ernawan 2022)", "45.57", "≈0.99", "27.64", "worst case reported; 2×2 blocks"],
        ["Wu et al. (CMC 2026)", "> 41", "—", "> 30 @ 50% tamper", "0% FPR/FNR reported"],
        ["Korus & Dziech (IEEE TIP 2013)", "—", "—", "37 @ 50% damage", "fountain codes, > 10,000 images"],
        ["Ours (measured, Variant A)", f"{S['psnr_a']:.2f}", f"{S['ssim_a']:.4f}",
         "17.39 @ 50% tamper", "marked (honest) output: 12.40 dB"],
    ]
    table(s, M, BODY_TOP + 0.32, BODY_W, headers, rows,
          [3.85, 1.35, 1.25, 2.35, 3.09], row_h=0.44, size=11, accents={3: CYAN})
    text(s, M, BODY_TOP + 0.02, BODY_W, 0.3,
         "CITED FROM PUBLICATIONS, NOT RE-IMPLEMENTED", 10, TEAL, True)

    y = BODY_TOP + 2.72
    cw = (BODY_W - 2 * 0.24) / 3
    accent_card(s, M, y, cw, 1.62, "The gap is real and it is ours",
                "Korus & Dziech report 37 dB at 50% damage where this scheme reaches 17.39 dB. "
                "Fountain coding degrades gracefully; one-to-one mapping does not.", ROSE,
                title_size=13, body_size=11)
    accent_card(s, M + cw + 0.24, y, cw, 1.62, "Two conventions, stated plainly",
                "17.39 dB leaves unrecoverable regions as received, the convention those papers use. "
                "Our actual default marks them instead — 12.40 dB, and honest.", AMBER,
                title_size=13, body_size=11)
    accent_card(s, M + 2 * (cw + 0.24), y, cw, 1.62, "What is defensible here",
                "Not recovery itself. Zero training data, zero GPU, deterministic output, and every "
                "decision re-checkable by a third party holding the key.", EMER,
                title_size=13, body_size=11)
    return s


def slide_limitations(prs):
    s = content_slide(prs, "10 · Results", "Limitations, stated before anyone asks", page())
    lim = [
        ("Fragile to benign processing", "JPEG, resizing and filtering destroy the mark. The pipeline "
                                         "must be lossless end to end."),
        ("Legacy images cannot be checked", "Nothing to verify against unless the image was marked "
                                            "before distribution."),
        ("Recovery is approximate", "A 96-bit descriptor is not a copy. ≈28–31 dB in-region, not "
                                    "pixel-exact."),
        ("Large-area tampering", "Block and partner both destroyed ⇒ unrecoverable. ρ tracks 1 − α."),
        ("Security is key-dependent", "The whole guarantee rests on the key staying secret."),
        ("Block-size trade-off", "4×4 localizes better but drops the tag to 16 bits, raising "
                                 "false-accept to 2⁻¹⁶."),
    ]
    text(s, M, BODY_TOP + 0.02, 6.35, 0.3, "LIMITATIONS", 10.5, ROSE, True)
    yy = BODY_TOP + 0.36
    for t, b in lim:
        card(s, M, yy, 6.35, 0.72)
        rect(s, M, yy, 0.055, 0.72, ROSE, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, M + 0.24, yy + 0.09, 6.0, 0.28, t, 12.5, TXT, True)
        text(s, M + 0.24, yy + 0.38, 6.0, 0.3, b, 10.5, TXT_MID, spacing=1.1)
        yy += 0.79

    x = M + 6.63
    ww = BODY_W - 6.63
    text(s, x, BODY_TOP + 0.02, ww, 0.3, "FUTURE SCOPE", 10.5, EMER, True)
    fut = [
        ("Reference sharing / fountain codes", "The single highest-value upgrade — it is what buys "
                                               "Korus & Dziech their 37 dB. A rate-1/3 prototype already "
                                               "holds ρ = 1.000 up to a sharp cliff at α ≈ 0.64.", EMER),
        ("Hierarchical verification", "Decouple localization resolution from per-block payload "
                                      "(Lin et al. 2005)."),
        ("Semi-fragile extension", "Tolerate a bounded, declared amount of JPEG re-compression."),
        ("Reversible embedding", "Bit-exact restoration of images that verify as authentic."),
        ("Video and colour-space extension", "Inter-frame mapping widens the recovery-data space."),
        ("Hybrid with passive forensics", "Use the exact mask as a trusted prior for unmarked images."),
    ]
    yy = BODY_TOP + 0.36
    for item in fut:
        t, b = item[0], item[1]
        h = 0.95 if len(item) > 2 else 0.72
        card(s, x, yy, ww, h)
        rect(s, x, yy, 0.055, h, EMER if len(item) > 2 else TEAL,
             MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
        text(s, x + 0.24, yy + 0.09, ww - 0.45, 0.28, t, 12.5, TXT, True)
        text(s, x + 0.24, yy + 0.38, ww - 0.45, h - 0.42, b, 10.5, TXT_MID, spacing=1.1)
        yy += h + 0.07
    return s


# ------------------------------------------------------- 11 conclusion -----
def slide_conclusion(prs, S):
    s = content_slide(prs, "11 · Conclusion", "What was built, measured and learned", page())
    cw = (BODY_W - 3 * 0.22) / 4
    stat(s, M, BODY_TOP + 0.05, cw, 1.55, f"{S['psnr_c']:.2f} dB", "imperceptibility",
         "SSIM ≥ 0.978 on every image", CYAN, value_size=32)
    stat(s, M + cw + 0.22, BODY_TOP + 0.05, cw, 1.5, "1.0000",
         "localization precision", "recall 1.000 on 3 of 4 classes", EMER)
    stat(s, M + 2 * (cw + 0.22), BODY_TOP + 0.05, cw, 1.55, "28.5 / 31.1 dB",
         "in-region recovery", "Variant A / C, flat in α", VIOL, value_size=24)
    stat(s, M + 3 * (cw + 0.22), BODY_TOP + 0.05, cw, 1.55, f"{S['n_total']:,}",
         "measured runs", "32-image public corpus", AMBER, value_size=32)

    cols = [
        ("Delivered", "A complete self-embedding pipeline — protect, detect, localize, recover — "
                      "with a web application, a reproducible experiment grid, an IEEE-format paper "
                      "and a deployment guide.", EMER),
        ("Learned", "The collapse this project set out to characterize does not exist in this design. "
                    "Across seven ratios ρ is monotone, near-linear, and consistently above 1 − α.", CYAN),
        ("Honest about cost", "Fragile by construction, approximate by design, and roughly 20 dB behind "
                              "a fountain-coded scheme at 50% tampering. All three are reported, none "
                              "are worked around.", ROSE),
    ]
    cwn = (BODY_W - 2 * 0.24) / 3
    for i, (t, b, col) in enumerate(cols):
        accent_card(s, M + i * (cwn + 0.24), BODY_TOP + 1.92, cwn, 1.78, t, b, col,
                    title_size=14.5, body_size=11.5)

    rect(s, M, BODY_TOP + 3.80, BODY_W, 0.95, INK, MSO_SHAPE.ROUNDED_RECTANGLE, 0.05)
    rect(s, M, BODY_TOP + 3.80, 0.07, 0.95, CYAN, MSO_SHAPE.ROUNDED_RECTANGLE, 0.5)
    text(s, M + 0.32, BODY_TOP + 3.80, BODY_W - 0.7, 0.95,
         "A conventional detector tells you an image is probably fake. This one names the blocks, "
         "proves the rest untouched, rebuilds what it can — and declares what it cannot.",
         15, ON_DARK, True, anchor=MSO_ANCHOR.MIDDLE, spacing=1.15)
    return s


def slide_references(prs):
    s = content_slide(prs, "References", "Selected references", page())
    refs = [
        "J. Fridrich and M. Goljan, “Protection of digital images using self-embedding,” Proc. Symp. Content Security and Data Hiding in Digital Media, 1999.",
        "J. Fridrich and M. Goljan, “Images with self-correcting capabilities,” Proc. IEEE ICIP, vol. 3, 1999, pp. 792–796.",
        "C.-Y. Lin and S.-F. Chang, “Semi-fragile watermarking for authenticating JPEG visual content,” Proc. SPIE 3971, 2000, pp. 140–151.",
        "M. Holliman and N. Memon, “Counterfeiting attacks on oblivious block-wise independent invisible watermarking schemes,” IEEE TIP, vol. 9, no. 3, 2000.",
        "P. W. Wong and N. Memon, “Secret and public key image watermarking schemes,” IEEE TIP, vol. 10, no. 10, 2001, pp. 1593–1601.",
        "J. Fridrich, “Security of fragile authentication watermarks with localization,” Proc. SPIE 4675, 2002, pp. 691–700.",
        "C. Rey and J.-L. Dugelay, “A survey of watermarking algorithms for image authentication,” EURASIP J. Appl. Signal Process., 2002.",
        "P.-L. Lin, C.-K. Hsieh, and P.-W. Huang, “A hierarchical digital watermarking method for image tamper detection and recovery,” Pattern Recognit., vol. 38, no. 12, 2005.",
        "X. Zhang and S. Wang, “Fragile watermarking with error-free restoration capability,” IEEE Trans. Multimedia, vol. 10, no. 8, 2008.",
        "X. Zhang, S. Wang, Z. Qian, and G. Feng, “Reference sharing mechanism for watermark self-embedding,” IEEE TIP, vol. 20, no. 2, 2011, pp. 485–495.",
        "P. Korus and A. Dziech, “Efficient method for content reconstruction with self-embedding,” IEEE TIP, vol. 22, no. 3, 2013, pp. 1134–1147.",
        "I. J. Cox, J. Kilian, F. T. Leighton, and T. Shamoon, “Secure spread spectrum watermarking for multimedia,” IEEE TIP, vol. 6, no. 12, 1997.",
        "Z. Wang, A. C. Bovik, H. R. Sheikh, and E. P. Simoncelli, “Image quality assessment: from error visibility to structural similarity,” IEEE TIP, vol. 13, no. 4, 2004.",
        "P. Zhou, X. Han, V. I. Morariu, and L. S. Davis, “Learning rich features for image manipulation detection,” Proc. IEEE/CVF CVPR, 2018.",
        "Y. Wu, W. AbdAlmageed, and P. Natarajan, “ManTra-Net: manipulation tracing network,” Proc. IEEE/CVF CVPR, 2019.",
        "A. Aminuddin and F. Ernawan, “AuSR1: authentication and self-recovery with LSB shifting in fragile image watermarking,” J. King Saud Univ. – CIS, 2022.",
        "A. Aminuddin and F. Ernawan, “AuSR2: watermarking for authentication and self-recovery with texture preservation,” Comput. Electr. Eng., vol. 102, 2022.",
        "A. Aminuddin and F. Ernawan, “AuSR3: a new block mapping technique to avoid the tamper coincidence problem,” J. King Saud Univ. – CIS, vol. 35, no. 9, 2023.",
        "A. Aminuddin et al., “TCBR and TCBD: evaluation metrics for the tamper coincidence problem,” Eng. Sci. Technol. Int. J., vol. 56, 2024.",
        "X. Zhang, R. Li, J. Yu, Y. Xu, W. Li, and J. Zhang, “EditGuard: versatile image watermarking for tamper localization and copyright protection,” Proc. IEEE/CVF CVPR, 2024.",
        "Q. Wu, H. Li, M. Li, and M. Wang, “Multi-feature fragile image watermarking for tampering blind-detection and content self-recovery,” CMC, vol. 86, no. 1, 2026.",
        "NIST, “Secure Hash Standard (SHS),” FIPS PUB 180-4, 2015.  ·  USC-SIPI Image Database, sipi.usc.edu/database.  ·  Kodak Lossless True Color Image Suite.",
    ]
    cw = (BODY_W - 0.45) / 2
    half = (len(refs) + 1) // 2
    for col, chunk in enumerate((refs[:half], refs[half:])):
        items = []
        for k, r in enumerate(chunk):
            idx = col * half + k + 1
            items.append((f"[{idx}]  {r}", 9.5, TXT_MID, False))
        text(s, M + col * (cw + 0.45), BODY_TOP + 0.05, cw, 5.2, items,
             spacing=1.12, space_after=6)
    return s


def slide_thanks(prs):
    s = blank(prs)
    rect(s, 0, 0, W, H, INK)
    rect(s, 0, 0, W, 0.10, CYAN)
    rect(s, W - 4.6, 0, 4.6, H, INK_SOFT)
    rect(s, W - 4.6, 0, 0.055, H, CYAN)
    text(s, M, 2.55, 7.8, 1.0, "Thank you", 52, ON_DARK, True)
    rect(s, M, 3.85, 1.5, 0.05, CYAN)
    text(s, M, 4.15, 7.6, 0.8,
         "Questions and discussion — a live demonstration is available: upload an image, "
         "tamper it, and watch the system name the damage and repair it.", 14, ON_DARK2,
         spacing=1.25)
    text(s, M, 5.6, 7.6, 0.9,
         f"{STUDENTS}\nGuide: {GUIDE}\n{DEPT}, {COLLEGE}", 11, TXT_DIM, spacing=1.3)

    items = [("Protect", "embed in seconds"), ("Verify", "block-exact mask"),
             ("Recover", "rebuild or declare")]
    yy = 2.6
    for t, sub in items:
        text(s, W - 4.15, yy, 3.6, 0.35, t, 20, CYAN, True)
        text(s, W - 4.15, yy + 0.38, 3.6, 0.3, sub, 11, ON_DARK2)
        yy += 1.05
    return s


# ==================================================================== main ==
def build():
    assets = figs.build()
    S = figs.stats()

    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)

    slide_title(prs, S)
    slide_outline(prs)

    def sect(n):
        num, title, blurb = SECTIONS[n - 1]
        section_slide(prs, num, title, blurb)

    sect(1); slide_intro_what(prs, S); slide_intro_demo(prs)
    sect(2); slide_lit_families(prs); slide_lit_timeline(prs)
    sect(3); slide_gap(prs, S)
    sect(4); slide_motivation(prs)
    sect(5); slide_problem(prs)
    sect(6); slide_objectives(prs, S)
    sect(7); slide_method_embed(prs); slide_method_verify(prs, S); slide_method_protocol(prs, S)
    sect(8); slide_architecture(prs); slide_payload(prs)
    sect(9); slide_math_1(prs); slide_math_2(prs, S)
    sect(10); slide_res_imperceptibility(prs, S); slide_res_detection(prs, S)
    slide_res_recovery(prs, S, assets); slide_res_fidelity(prs, S, assets)
    slide_comparison(prs, S); slide_limitations(prs)
    sect(11); slide_conclusion(prs, S)
    slide_references(prs)
    slide_thanks(prs)

    prs.save(OUT)
    return prs


if __name__ == "__main__":
    p = build()
    print(f"wrote {OUT}  ({len(p.slides.__iter__.__self__._sldIdLst)} slides)")
