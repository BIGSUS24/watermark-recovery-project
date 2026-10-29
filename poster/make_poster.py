r"""Build the A3 project poster as black-and-white A4 sheets that get trimmed and pasted.

An A3 chart is exactly two A4 sheets, so a poster made of four to six whole A4 prints
is geometrically impossible. This lays the poster out on A3 (297 x 420 mm) instead and
emits each piece centred on its own A4 page with cut marks:

    title band   271 x 40 mm   (A4 landscape)
    pieces 1-6   132 x 111 mm  (A4 portrait), column-major reading order

Page 1 of the PDF is the assembly map. Everything is greyscale and light on ink,
because it gets printed black and white on an office laser printer.

    python poster/make_poster.py              # demo assets are cached
    python poster/make_poster.py --refresh    # re-run the pipeline for them
    -> output/poster/Poster_A3_sheets.pdf     assembly map + 7 printable pieces
    -> output/poster/Poster_A3_preview.pdf    the finished poster on one A3 page

Numbers come from report/src/FACTS.md (the frozen fact sheet), output/runs.csv and one
re-run of the paper's worked example. Nothing is typed in by hand.
"""
import csv
import json
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "poster"
ASSETS = OUT / "assets"
MM = 1 / 25.4  # mm -> inch, so every figure comes out at true physical size

A4P, A4L, A3 = (210.0, 297.0), (297.0, 210.0), (297.0, 420.0)
MARGIN, GAP = 13.0, 7.0
BAND = (271.0, 40.0)
PANEL = (132.0, 111.0)

BAND_XY = (MARGIN, A3[1] - MARGIN - BAND[1])
COLS = (MARGIN, MARGIN + PANEL[0] + GAP)
ROWS = (BAND_XY[1] - GAP - PANEL[1],
        BAND_XY[1] - 2 * GAP - 2 * PANEL[1],
        MARGIN)
PANEL_XY = [(COLS[c], ROWS[r]) for c in (0, 1) for r in (0, 1, 2)]

INK, MID, PALE = "0.0", "0.35", "0.88"
RATIOS = (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)
CLS_LABEL = {"splice": "splicing", "inpaint_removal": "object removal",
             "crop_refill": "crop-and-refill", "noise": "noise"}
CLS_STYLE = {"splice": ("-", "o"), "inpaint_removal": ("--", "s"),
             "crop_refill": ("-.", "^"), "noise": (":", "D")}

RC = {"font.family": "serif", "font.size": 10, "mathtext.fontset": "dejavuserif",
      "pdf.fonttype": 42}


# --------------------------------------------------------------------------- assets

def gray(rgb) -> np.ndarray:
    return np.asarray(rgb, dtype=np.float64) @ np.array([0.299, 0.587, 0.114])


def build_assets(refresh: bool = False) -> dict:
    """Re-run the paper's worked example and store its panels as greyscale PNGs.

    The paper's own figure marks the repairable region red and the unrecoverable
    subset cyan. Desaturated for a black-and-white print those land at 76 and 178 grey
    over a busy photograph and stop being readable, so the mask panel is rebuilt here
    in ink-on-paper tones instead of being converted after the fact.
    """
    stats = ASSETS / "demo_stats.json"
    if stats.exists() and not refresh:
        return json.loads(stats.read_text(encoding="utf-8"))

    ASSETS.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / "paper" / "icip"))
    sys.path.insert(0, str(ROOT / "src"))
    import run_photo as rp

    raw = rp.prepare(rp.HERE / "photo_src.jpeg", ASSETS / "_photo_512.png")
    key = rp.make_key(0)
    iid = rp.default_image_id(rp.NAME, raw.shape, rp.BLOCK)
    wm, _ = rp.embed_image(raw, key, iid, block=rp.BLOCK, variant="A")

    def bw_mask(base, pred_px, unrec_px):
        """Tamper mask in print tones: near-black repairable, mid-grey unrecoverable."""
        out = gray(base) * 0.3 + 255.0 * 0.7  # photo washed out, kept only for context
        out[pred_px & ~unrec_px] = 25.0
        out[unrec_px] = 150.0
        return np.clip(out, 0, 255).astype(np.uint8)

    rp.overlay = bw_mask  # rp.trial() builds the strip through this name
    row, panels = rp.trial(raw, wm, key, iid, "splice", 0.30, "A")

    for i, img in enumerate(panels.values()):
        a = np.asarray(img)
        a = a if a.ndim == 2 else gray(a).astype(np.uint8)
        plt.imsave(ASSETS / f"demo{i}.png", a, cmap="gray", vmin=0, vmax=255)

    imp = rp.imperceptibility(raw, wm)
    out = {"titles": list(panels), "wm_psnr": imp["psnr"], "wm_ssim": imp["ssim"], **row}
    stats.write_text(json.dumps(out, indent=1), encoding="utf-8")
    return out


def rho_series() -> dict:
    """Mean recoverability rate per tamper class over the 32-image main grid."""
    rows = [r for r in csv.DictReader(open(ROOT / "output" / "runs.csv", encoding="utf-8"))
            if r["condition"] == "tamper" and r["recovery_variant"] == "A"
            and r["block_size"] == "8"]
    series = {}
    for cls in CLS_STYLE:
        ys = []
        for a in RATIOS:
            v = [float(r["recoverability_rate"]) for r in rows if r["tamper_class"] == cls
                 and abs(float(r["tamper_ratio_nominal"]) - a) < 1e-9]
            ys.append(sum(v) / len(v))
        series[cls] = ys
    return series


# ------------------------------------------------------------------- drawing helpers

def para(ax, x, y, text, size=8.6, lead=4.1, width=56, color=INK, weight="normal"):
    for line in textwrap.wrap(text, width):
        ax.text(x, y, line, ha="left", va="top", fontsize=size, color=color,
                fontweight=weight)
        y -= lead
    return y


def bullets(ax, x, y, items, size=8.6, lead=4.1, width=52, indent=3.4):
    for it in items:
        lines = textwrap.wrap(it, width)
        for i, line in enumerate(lines):
            ax.text(x + (0 if i == 0 else indent), y,
                    ("\u2022 " if i == 0 else "") + line,
                    ha="left", va="top", fontsize=size, color=INK)
            y -= lead
    return y


def steps(ax, x, y, items, size=8.0, lead=3.8, width=58, indent=3.0):
    """Numbered steps whose leading keyword is set in bold on its own baseline."""
    for n, (word, rest) in enumerate(items, 1):
        ax.text(x, y, f"{n}  {word}", ha="left", va="top", fontsize=size,
                color=INK, fontweight="bold")
        y -= lead
        for line in textwrap.wrap(rest, width):
            ax.text(x + indent, y, line, ha="left", va="top", fontsize=size, color=INK)
            y -= lead
        y -= 0.8
    return y


def callout(ax, x, y, w, text, size=7.9, lead=3.8, width=54, pad=2.2):
    lines = textwrap.wrap(text, width)
    h = len(lines) * lead + 2 * pad
    ax.add_patch(Rectangle((x, y - h), w, h, fc=PALE, ec=INK, lw=0.6))
    yy = y - pad
    for line in lines:
        ax.text(x + pad, yy, line, ha="left", va="top", fontsize=size, color=INK)
        yy -= lead
    return y - h - 3.0


def rule(ax, box, y, lw=0.5, color=MID, inset=4.0):
    ax.plot([inset, box[0] - inset], [y, y], color=color, lw=lw)
    return y - 4.0


def head(ax, box, n, title):
    """Numbered heading bar across the top of a panel. Returns the first content y."""
    h = 9.0
    ax.add_patch(Rectangle((0, box[1] - h), box[0], h, fc=INK, ec="none"))
    ax.text(4.0, box[1] - h / 2, str(n), ha="left", va="center", fontsize=12,
            color="white", fontweight="bold")
    ax.text(11.5, box[1] - h / 2, title, ha="left", va="center", fontsize=11.5,
            color="white", fontweight="bold")
    return box[1] - h - 4.5


# ----------------------------------------------------------------------- page frames

def sheet(size, box, piece, place):
    """One A4 page holding a single poster piece, with cut marks and a footer."""
    fig = plt.figure(figsize=(size[0] * MM, size[1] * MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, size[0])
    ax.set_ylim(0, size[1])
    ax.axis("off")

    x0, y0 = (size[0] - box[0]) / 2, (size[1] - box[1]) / 2
    for dx in (0, box[0]):
        for dy, s in ((0, -1), (box[1], 1)):
            ax.plot([x0 + dx, x0 + dx], [y0 + dy, y0 + dy + 5 * s], color=INK, lw=0.4)
            ax.plot([x0 + dx - 5, x0 + dx + 5], [y0 + dy, y0 + dy], color=INK, lw=0.4)
    ax.add_patch(Rectangle((x0, y0), box[0], box[1], fill=False, ec=MID, lw=0.4,
                           ls=(0, (4, 3))))
    ax.text(size[0] / 2, y0 - 9, f"{piece}  |  cut on the dashed line  |  {place}",
            ha="center", va="top", fontsize=7.5, color=MID)

    inner = fig.add_axes([x0 / size[0], y0 / size[1], box[0] / size[0], box[1] / size[1]])
    frame(inner, box)
    return fig, inner


def fits(fig, ax, box, pad=1.2):
    """Every text drawn in ax, measured, must sit inside the piece with a margin.

    Eyeballing the band was what let the e-mail line sit on the bottom rule, so the
    build measures it: rendered extents, converted back to mm, checked against the box.
    """
    fig.canvas.draw()
    inv = ax.transData.inverted()
    bad = []
    for t in ax.texts:
        bb = t.get_window_extent(fig.canvas.get_renderer())
        (x0, y0), (x1, y1) = inv.transform(((bb.x0, bb.y0), (bb.x1, bb.y1)))
        if x0 < pad or y0 < pad or x1 > box[0] - pad or y1 > box[1] - pad:
            bad.append(f"{t.get_text()[:34]!r} at x {x0:.1f}..{x1:.1f}, y {y0:.1f}..{y1:.1f}")
    return bad


def frame(ax, box, border=True):
    ax.set_xlim(0, box[0])
    ax.set_ylim(0, box[1])
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set(visible=border, color=INK, lw=0.9)
    return ax


# --------------------------------------------------------------------------- pieces

def title_band(ax, box):
    """Kept as ink on white: a 271 x 40 mm solid black block is a toner sink.

    Every line is placed from the top of the band, so the stack below is what keeps
    the e-mail line clear of the bottom rule -- it is the tightest fit in the piece.
    """
    ax.plot([0, box[0]], [box[1] - 2.2] * 2, color=INK, lw=2.6)
    ax.plot([0, box[0]], [2.2] * 2, color=INK, lw=2.6)
    ax.text(box[0] / 2, box[1] - 4.8,
            "Watermark-Guided Tamper Localization and Recovery",
            ha="center", va="top", fontsize=20, color=INK, fontweight="bold")
    ax.text(box[0] / 2, box[1] - 13.6,
            "A Key-Seeded Self-Embedding Fragile Watermarking Scheme with "
            "Joint Localization and Restoration Assessment",
            ha="center", va="top", fontsize=10, color=INK, style="italic")
    ax.plot([70, box[0] - 70], [box[1] - 18.8] * 2, color=MID, lw=0.5)
    ax.text(box[0] / 2, box[1] - 21.0,
            "Tejas Mane$^{1}$      Shivam Singh$^{2}$      Amol Hipparkar$^{3}$"
            "            Guide:  Dr. Deepti Varshney",
            ha="center", va="top", fontsize=11, color=INK)
    ax.text(box[0] / 2, box[1] - 27.4,
            "Department of Computer Engineering, Ajeenkya DY Patil School of "
            "Engineering, Pune, India",
            ha="center", va="top", fontsize=8.8, color=INK)
    ax.text(box[0] / 2, box[1] - 32.6,
            "$^{1}$manetejas710@gmail.com      $^{2}$notshivamsingh@gmail.com      "
            "$^{3}$amolhipparkar04@gmail.com",
            ha="center", va="top", fontsize=7.8, color=MID)


def panel1(ax, box, st):
    y = head(ax, box, 1, "The problem")
    y = para(ax, 4, y, "A photograph is evidence only if you can show it was not "
                       "edited after capture.", size=9.4, lead=4.4, width=49,
             weight="bold")
    y -= 2.0
    y = bullets(ax, 4, y, [
        "A competent edit is invisible. A doctored image looks exactly as credible "
        "as a real one.",
        "Detectors trained on today's forgeries degrade on tomorrow's generator, and "
        "give no way to audit their verdict.",
        "Knowing that an image was altered is not enough. A court, an insurer or a "
        "newsroom needs to know where, and what was there before.",
    ], size=8.8, lead=4.1, width=52)
    y = rule(ax, box, y - 1.0)
    y = para(ax, 4, y, "OBJECTIVE", size=8.8, lead=4.4, width=40, weight="bold")
    y = para(ax, 4, y, "Make the image carry its own proof and its own backup, so that "
                       "any later edit is detected, localized to an 8x8 block, and "
                       "repaired from data already inside the file itself.",
             size=8.8, lead=4.1, width=52)
    y -= 2.0
    return callout(ax, 4, y, box[0] - 8,
                   "No reference copy. No database. No training. No GPU. And nothing "
                   "is invented: a block that cannot be honestly restored is marked "
                   "black, never filled in with a guess.",
                   size=8.4, lead=4.0, width=52)


def panel2(ax, box, st):
    y = head(ax, box, 2, "How it works")
    img = plt.imread(ROOT / "output" / "figures" / "architecture.png")
    h, w = img.shape[:2]
    iw = 98.0
    ih = iw * h / w
    ax.imshow(img, extent=((box[0] - iw) / 2, (box[0] + iw) / 2, y - ih, y), zorder=2,
              cmap="gray")
    y = y - ih - 4.0
    return steps(ax, 4, y, [
        ("PARTITION", "into 8x8 blocks. The two low bit-planes of a block are 128 "
                      "free bits of carrier."),
        ("DESCRIBE", "each block in 96 bits: 12 zig-zag DCT coefficients quantized "
                     "at JPEG quality-50 step sizes."),
        ("SCATTER", "that descriptor to a partner block at least 0.25 min(M,N) away, "
                    "picked by a key-seeded single-cycle permutation."),
        ("AUTHENTICATE", "with a 32-bit truncated HMAC-SHA256 over the block's six "
                         "upper bit-planes and the descriptor it carries."),
        ("VERIFY AND REPAIR", "by recomputing every tag. A mismatch flags the block, "
                              "which is rebuilt from the copy its partner holds."),
    ], size=8.2, lead=3.8, width=61)


def panel3(ax, box, st):
    y = head(ax, box, 3, "The scheme")

    def eq(y, text, size=9.6, drop=8.5):
        ax.text(box[0] / 2, y, text, ha="center", va="top", fontsize=size, color=INK)
        return y - drop

    y = para(ax, 4, y, "Carrier capacity, split per block", size=8.8, lead=5.2,
             width=40, weight="bold")
    y = eq(y, r"$\mathrm{cap}(B)=2B^{2}=128$ bits $=$ 32-bit tag $+$ 96-bit descriptor",
           9.0, 9.0)
    y = para(ax, 4, y, "Keyed authentication tag", size=8.8, lead=5.2, width=40,
             weight="bold")
    y = eq(y, r"$a_i=\mathrm{Trunc}_{32}\!\left[\mathrm{HMAC}_{K_s}"
              r"\!\left(\mathrm{ID},\,i,\,\mathrm{MSB}(b_i),\,r_{m^{-1}(i)}\right)\right]$",
           9.2, 8.0)
    y = eq(y, r"$\mathrm{MSB}(a)=a\;\wedge\;\mathtt{0xFC}$", 9.2, 8.5)
    y = para(ax, 4, y, "Recoverability of a flagged set T", size=8.8, lead=5.2,
             width=40, weight="bold")
    y = eq(y, r"$\rho=1-\dfrac{|U|}{|T|},\qquad U=\{\,i\in T:\;m(i)\in T\,\}$",
           9.6, 11.0)
    y = eq(y, r"$\mathbb{E}[\rho]\;\approx\;1-\alpha$    (structural bound)", 9.2, 8.5)
    y = rule(ax, box, y)
    return para(ax, 4, y, "One keyed hash and one 8x8 transform per block, so the whole "
                          "pipeline is O(MN). No iteration, no optimization and no "
                          "learned parameters: the scheme sits in complexity class P, "
                          "and the same key reproduces the same bits every time.",
                size=8.8, lead=4.2, width=51)


def panel4(ax, box, st):
    y = head(ax, box, 4, "Measured results")
    y = para(ax, 4, y, "32 colour images (8 USC-SIPI + 24 Kodak), each pinned by "
                       "SHA-256. 3,232 runs: 1,792 main grid (4 tamper classes x 7 "
                       "ratios x 2 variants) + 320 null + 1,120 ablation. Automated "
                       "sanity gate 25/27.", size=8.0, lead=3.8, width=61, color=MID)
    y -= 3.0

    rows = [("Watermarked PSNR / SSIM", "45.48 dB / 0.9885"),
            ("Block-level recall", "1.0000   (0.99998 inpainting)"),
            ("Pixel-level precision", "0.9599"),
            ("False positives in 1,802,240 checks", "0   (95% bound 1.7e-6)"),
            ("Mean recoverability rate", "0.6482"),
            ("In-region recovered PSNR", "28.49 dB (A) / 31.13 dB (C)"),
            ("Runtime, 512x512", "473 ms embed / 197 ms verify")]
    rh = 6.1
    ax.plot([4, box[0] - 4], [y, y], color=INK, lw=0.8)
    for i, (k, v) in enumerate(rows):
        yy = y - i * rh
        if i % 2:
            ax.add_patch(Rectangle((4, yy - rh), box[0] - 8, rh, fc=PALE, ec="none"))
        ax.text(5.5, yy - rh / 2, k, ha="left", va="center", fontsize=8.4)
        ax.text(box[0] - 5.5, yy - rh / 2, v, ha="right", va="center", fontsize=8.4,
                fontweight="bold")
    y -= len(rows) * rh
    ax.plot([4, box[0] - 4], [y, y], color=INK, lw=0.8)
    y -= 5.0

    return callout(ax, 4, y, box[0] - 8,
                   "Reported honestly: block precision is 1.0000 only because the "
                   "ground-truth rule counts a block as tampered when the region "
                   "touches any of its pixels, so it is not evidence of detector "
                   "quality. The zero false positives are a determinism check across "
                   "images, variants and keys, not a measurement of the 2^-32 "
                   "cryptographic bound.", size=8.0, lead=3.8, width=58)


def panel5(ax, box, st):
    y = head(ax, box, 5, "On our own photograph")
    y = para(ax, 4, y, "512x512 capture, copy-paste splicing over 30% of the frame, "
                       "Variant A.", size=8.2, lead=3.9, width=58, color=MID)
    y -= 1.5

    caps = ["Original", "Watermarked", "Tampered 30%", "Detected mask", "Recovered"]
    for group, s in (([0, 1, 2], 23.0), ([3, 4], 30.0)):
        total = len(group) * s + (len(group) - 1) * 3.0
        x = (box[0] - total) / 2
        for i in group:
            ax.imshow(plt.imread(ASSETS / f"demo{i}.png"), cmap="gray",
                      extent=(x, x + s, y - s, y), zorder=2)
            ax.add_patch(Rectangle((x, y - s), s, s, fill=False, ec=INK, lw=0.5,
                                   zorder=3))
            ax.text(x + s / 2, y - s - 1.0, caps[i], ha="center", va="top", fontsize=7.4)
            x += s + 3.0
        y -= s + 5.6

    ax.text(box[0] / 2, y, "in the mask:  black = flagged and repairable,     "
                           "grey = flagged but unrecoverable",
            ha="center", va="top", fontsize=7.6, color=MID)
    y -= 5.0
    return para(ax, 4, y,
                f"Watermarked at {st['wm_psnr']:.3f} dB / SSIM {st['wm_ssim']:.5f}. Of "
                f"{st['n_tampered_blocks']:,} flagged blocks, "
                f"{st['n_unrecoverable_blocks']:,} are unrecoverable "
                f"(rho = {st['rho']:.4f}) and are left black rather than fabricated; "
                f"pixel precision {st['px_precision']:.4f}, in-region PSNR "
                f"{st['psnr_in_region']:.2f} dB -- about 5 dB under the corpus mean, "
                f"because dense foliage is what 12 DCT coefficients cannot hold. "
                f"Shown as the worst case, not the best.",
                size=7.8, lead=3.6, width=70)


def panel6(ax, box, st):
    y = head(ax, box, 6, "Recovery and conclusions")

    block_h = 42.0
    sub = ax.inset_axes([6 / box[0], (y - block_h + 8.5) / box[1],
                         (box[0] - 14) / box[0], 33 / box[1]])
    for cls, ys in rho_series().items():
        ls, mk = CLS_STYLE[cls]
        sub.plot(RATIOS, ys, ls=ls, marker=mk, ms=2.6, lw=1.0, color=INK, mfc="white",
                 label=CLS_LABEL[cls])
    sub.plot(RATIOS, [1 - a for a in RATIOS], ls=(0, (1, 1.4)), lw=1.0, color="0.45",
             label=r"bound $1-\alpha$")
    sub.set_xlabel(r"tamper ratio $\alpha$", fontsize=7.5, labelpad=1.0)
    sub.set_ylabel(r"recoverability $\rho$", fontsize=7.5, labelpad=1.5)
    sub.tick_params(labelsize=6.8, length=2, pad=1.5)
    sub.set_xlim(0.05, 0.75)
    sub.set_ylim(0.25, 1.0)
    sub.grid(alpha=0.35, lw=0.4)
    sub.legend(loc="upper right", frameon=False, fontsize=6.2, handlelength=2.4,
               labelspacing=0.25)
    y -= block_h

    y = bullets(ax, 4, y, [
        "Recoverability sits 3 to 6 points above its own structural bound at every "
        "ratio, falls monotonically, and never collapses.",
        "Recovered quality inside the tampered region is essentially flat across "
        "10-70% coverage (29.81 dB mean), so mapping coverage, not descriptor "
        "fidelity, is the binding constraint.",
    ], size=7.9, lead=3.7, width=64)
    y -= 1.5
    y = callout(ax, 4, y, box[0] - 8,
                "Limits we accept: the scheme is fragile by design, so any re-encode "
                "destroys it; the 8x8 grid caps pixel precision near 0.96; and 4x4 "
                "blocks buy a finer mask for 2.85 dB and a weaker 16-bit tag.",
                size=7.7, lead=3.6, width=65)
    return para(ax, 4, y, "Next: share each descriptor across several partners "
                          "(fountain coding) to break the coverage ceiling.      "
                          "github.com/BIGSUS24/watermark-recovery-project",
                size=7.6, lead=3.6, width=68, color=MID)


PANELS = [panel1, panel2, panel3, panel4, panel5, panel6]
PLACES = ["top-left", "middle-left", "bottom-left",
          "top-right", "middle-right", "bottom-right"]
STEPS = [
    "Print every page at 100% scale. Turn OFF 'fit to page' and 'shrink oversized "
    "pages', or the pieces will not line up with each other.",
    "Page 2 is A4 LANDSCAPE -- it is the wide title band. Pages 3 to 8 are A4 "
    "portrait.",
    "Cut each sheet on its dashed rectangle; the corner ticks mark where the cut "
    "line runs.",
    "Dry-fit all seven pieces on the chart before any glue. Margins are 13 mm at the "
    "edges of the A3 and 7 mm between pieces.",
    "Paste the left column top to bottom (1, 2, 3), then the right column (4, 5, 6). "
    "That is the reading order.",
    "Use a glue stick, not liquid glue, so the paper does not cockle. Press flat "
    "under a book for ten minutes.",
]


# ------------------------------------------------------------------- map and preview

def map_page(pdf):
    fig = plt.figure(figsize=(A4P[0] * MM, A4P[1] * MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, A4P[0])
    ax.set_ylim(0, A4P[1])
    ax.axis("off")
    ax.text(A4P[0] / 2, A4P[1] - 16, "ASSEMBLY MAP", ha="center", va="top", fontsize=17,
            fontweight="bold")
    ax.text(A4P[0] / 2, A4P[1] - 24.5,
            "Seven A4 sheets, trimmed, make one A3 poster. An A3 is exactly two A4s, "
            "so whole sheets cannot be used.",
            ha="center", va="top", fontsize=8.5, color=MID)

    s = 0.40
    ox, oy = (A4P[0] - A3[0] * s) / 2, 86.0
    ax.add_patch(Rectangle((ox, oy), A3[0] * s, A3[1] * s, fill=False, ec=INK, lw=1.2))
    ax.text(ox + A3[0] * s / 2, oy + A3[1] * s + 3,
            "A3 chart paper, portrait (297 x 420 mm)", ha="center", va="bottom",
            fontsize=8.5)

    def cell(xy, wh, label, sub):
        x, y = ox + xy[0] * s, oy + xy[1] * s
        w, h = wh[0] * s, wh[1] * s
        ax.add_patch(Rectangle((x, y), w, h, fc=PALE, ec=INK, lw=0.8))
        ax.text(x + w / 2, y + h / 2 + 2, label, ha="center", va="center", fontsize=11,
                fontweight="bold")
        ax.text(x + w / 2, y + h / 2 - 4, sub, ha="center", va="center", fontsize=6.6,
                color=MID)

    cell(BAND_XY, BAND, "TITLE", "271 x 40 mm  (page 2, landscape)")
    for i, xy in enumerate(PANEL_XY):
        cell(xy, PANEL, str(i + 1), f"132 x 111 mm  (page {i + 3})")

    y = oy - 10
    for n, line in enumerate(STEPS, 1):
        for j, ln in enumerate(textwrap.wrap(line, 84)):
            ax.text(16 if j == 0 else 21.5, y, (f"{n}.  " if j == 0 else "") + ln,
                    ha="left", va="top", fontsize=8.2)
            y -= 4.3
        y -= 1.2
    pdf.savefig(fig)
    plt.close(fig)
    return y


def preview(path, st):
    """The finished poster on a single A3 page, so the layout can be checked on screen."""
    fig = plt.figure(figsize=(A3[0] * MM, A3[1] * MM))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, A3[0])
    ax.set_ylim(0, A3[1])
    ax.axis("off")

    def place(xy, wh):
        a = fig.add_axes([xy[0] / A3[0], xy[1] / A3[1], wh[0] / A3[0], wh[1] / A3[1]])
        return frame(a, wh, border=wh != BAND)

    title_band(place(BAND_XY, BAND), BAND)
    for draw, xy in zip(PANELS, PANEL_XY):
        draw(place(xy, PANEL), PANEL, st)
    fig.savefig(path)
    plt.close(fig)


def main() -> int:
    st = build_assets("--refresh" in sys.argv)
    plt.rcParams.update(RC)
    OUT.mkdir(parents=True, exist_ok=True)

    sheets = OUT / "Poster_A3_sheets.pdf"
    with PdfPages(sheets) as pdf:
        last = map_page(pdf)
        print(f"  map page: assembly steps end {last:.1f} mm from the foot")
        assert last > 4, f"assembly steps run off the map page ({last:.1f} mm)"

        fig, ax = sheet(A4L, BAND, "TITLE BAND", "across the top of the chart")
        title_band(ax, BAND)
        over = fits(fig, ax, BAND)
        assert not over, "title band text runs off the piece: " + "; ".join(over)
        pdf.savefig(fig)
        plt.close(fig)

        for i, draw in enumerate(PANELS):
            fig, ax = sheet(A4P, PANEL, f"PIECE {i + 1} of 6", PLACES[i])
            bottom = draw(ax, PANEL, st)
            assert bottom is not None and bottom > 0.5, \
                f"panel {i + 1} overflows its box (ends {bottom:.1f} mm from the top)"
            pdf.savefig(fig)
            plt.close(fig)

    preview(OUT / "Poster_A3_preview.pdf", st)

    import pymupdf
    n = pymupdf.open(sheets).page_count
    assert n == 8, n
    assert pymupdf.open(OUT / "Poster_A3_preview.pdf")[0].rect.width > 800
    print(f"wrote {sheets}  ({n} pages: map + title band + 6 panels)")
    print(f"wrote {OUT / 'Poster_A3_preview.pdf'}  (assembled A3 preview)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
