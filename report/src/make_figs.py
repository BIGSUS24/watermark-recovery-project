"""All report figures, drawn black-and-white at 200 dpi.

The departmental format demands sharp black-and-white illustrations embedded in
text, so nothing here uses colour: fills are greys, series are separated by
marker and dash pattern. Pure matplotlib -- no graphviz, no plantuml, so the
figures rebuild anywhere the pipeline already runs.
"""
from pathlib import Path
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle, Circle, Ellipse, Polygon, FancyArrowPatch
import numpy as np

OUT = Path(__file__).resolve().parent / "figs"
OUT.mkdir(exist_ok=True)
REPO = Path("E:/cheat/Selection/watermark-recovery-project")

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["Times New Roman", "DejaVu Serif"],
    "text.color": "black", "axes.labelcolor": "black",
    "xtick.color": "black", "ytick.color": "black",
    "savefig.facecolor": "white", "figure.facecolor": "white",
})

WHITE, LIGHT, MID, DARK = "white", "#E8E8E8", "#C9C9C9", "#9A9A9A"


def canvas(w, h, xmax=100, ymax=100):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    ax.set_xlim(0, xmax); ax.set_ylim(0, ymax)
    ax.set_aspect("auto"); ax.axis("off")
    fig.subplots_adjust(left=0.005, right=0.995, top=0.995, bottom=0.005)
    return fig, ax


def box(ax, x, y, w, h, s, fs=8, fill=WHITE, round_=0.8, lw=1.1, style="round",
        ls="-", weight="normal"):
    pad = f"rounding_size={round_}" if style == "round" else ""
    p = FancyBboxPatch((x, y), w, h,
                       boxstyle=f"round,pad=0,{pad}" if style == "round" else "square,pad=0",
                       linewidth=lw, edgecolor="black", facecolor=fill, linestyle=ls,
                       mutation_aspect=1)
    ax.add_patch(p)
    if s:
        ax.text(x + w / 2, y + h / 2, s, ha="center", va="center", fontsize=fs,
                linespacing=1.25, fontweight=weight, zorder=5)
    return (x, y, w, h)


def arrow(ax, p, q, ls="-", lw=1.1, rad=0.0, text=None, fs=6.5, tdy=1.4, tdx=0.0,
          head=7):
    a = FancyArrowPatch(p, q, arrowstyle="-|>,head_width=0.22,head_length=0.42",
                        mutation_scale=head, linewidth=lw, linestyle=ls,
                        color="black", shrinkA=0, shrinkB=0,
                        connectionstyle=f"arc3,rad={rad}")
    ax.add_patch(a)
    if text:
        ax.text((p[0] + q[0]) / 2 + tdx, (p[1] + q[1]) / 2 + tdy, text, ha="center",
                va="bottom", fontsize=fs, style="italic")


def line(ax, p, q, ls="-", lw=1.1):
    ax.plot([p[0], q[0]], [p[1], q[1]], ls, color="black", lw=lw)


def right(b):   return (b[0] + b[2], b[1] + b[3] / 2)
def left(b):    return (b[0], b[1] + b[3] / 2)
def top(b):     return (b[0] + b[2] / 2, b[1] + b[3])
def bot(b):     return (b[0] + b[2] / 2, b[1])
def ctr(b):     return (b[0] + b[2] / 2, b[1] + b[3] / 2)


def save(fig, name):
    fig.savefig(OUT / f"{name}.png", dpi=200, bbox_inches="tight", pad_inches=0.04)
    plt.close(fig)
    print("wrote", name)


# ----------------------------------------------------------------- Fig 1.1
def fig_1_1():
    fig, ax = canvas(7.2, 3.2)
    ax.text(1, 94, "(a)  Passive forensic detection", fontsize=9, fontweight="bold")
    y = 68
    a = box(ax, 2, y, 19, 16, "Received\nimage")
    b = box(ax, 27, y, 22, 16, "Statistical\nanalysis", fill=LIGHT)
    c = box(ax, 55, y, 22, 16, "Suspect-region\nheat map", fill=LIGHT)
    d = box(ax, 83, y, 15, 16, "No\nrestoration", fill=MID, ls="--")
    for p, q in ((a, b), (b, c), (c, d)):
        arrow(ax, right(p), left(q))

    ax.plot([0, 100], [60, 60], "--", color=DARK, lw=0.9)
    ax.text(1, 52, "(b)  Active self-embedding (this project)", fontsize=9,
            fontweight="bold")
    y = 24
    s = [box(ax, 1.0, y, 14, 16, "Original\nimage"),
         box(ax, 17.5, y, 14, 16, "Embed\npayload", fill=LIGHT),
         box(ax, 34.0, y, 14, 16, "Distribute", fill=WHITE),
         box(ax, 50.5, y, 14, 16, "Tamper", fill=MID),
         box(ax, 67.0, y, 14, 16, "Verify and\nlocalize", fill=LIGHT),
         box(ax, 83.5, y, 15, 16, "Recover\ncontent", fill=LIGHT)]
    for p, q in zip(s, s[1:]):
        arrow(ax, right(p), left(q))
    k = box(ax, 30, 2, 26, 9, "secret key  K", fs=7.4, fill=MID)
    arrow(ax, (38, 11), (24.5, y - 0.4), ls=":", rad=-0.12)
    arrow(ax, (48, 11), (74.0, y - 0.4), ls=":", rad=0.10)
    ax.text(91, 6.5, "unrecoverable regions marked,\nnever fabricated",
            fontsize=6.6, ha="center", style="italic")
    save(fig, "fig1_1")


# ----------------------------------------------------------------- Fig 2.1
def fig_2_1():
    import matplotlib.image as mpimg
    names = [("splice", "Copy-paste splicing"),
             ("inpaint_removal", "Object removal by inpainting"),
             ("crop_refill", "Crop-and-refill"),
             ("noise", "Noise corruption")]
    fig, axes = plt.subplots(1, 4, figsize=(7.0, 2.1), dpi=200)
    for ax, (k, label) in zip(axes, names):
        img = np.asarray(mpimg.imread(REPO / f"output/images/lena_tampered_{k}.png"))[:, :, :3]
        ax.imshow(img @ [0.299, 0.587, 0.114], cmap="gray")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_linewidth(0.8)
        ax.set_xlabel(label, fontsize=7.5, labelpad=3)
    fig.subplots_adjust(wspace=0.06, left=0.004, right=0.996, top=0.99, bottom=0.11)
    save(fig, "fig2_1")


# ----------------------------------------------------------------- Fig 3.1
PHASES = [
    ("1  Literature survey and problem formulation", 0, 6, True),
    ("2  Scheme design: budget, tag, block map", 5, 5, True),
    ("3  Core pipeline implementation", 9, 7, True),
    ("4  Tamper harness and metrics", 14, 5, True),
    ("5  Full experimental grid and validation", 18, 6, True),
    ("6  Applications and adversarial testing", 22, 5, True),
    ("8  Variant C consolidation", 26, 3, True),
    ("7  Paper preparation and internal review", 27, 6, False),
    ("9  Reference-sharing extension", 32, 5, False),
    ("10  Final report, demonstration and viva", 35, 5, False),
]


def fig_3_1():
    fig, ax = plt.subplots(figsize=(7.0, 3.4), dpi=200)
    for i, (name, start, dur, done) in enumerate(PHASES):
        y = len(PHASES) - i - 1
        ax.barh(y, dur, left=start, height=0.56,
                color="#4A4A4A" if done else WHITE,
                edgecolor="black", linewidth=0.9,
                hatch="" if done else "///")
    ax.set_yticks(range(len(PHASES)))
    ax.set_yticklabels([p[0] for p in reversed(PHASES)], fontsize=7.5)
    ax.set_xlim(0, 40)
    ax.set_xticks(range(0, 41, 4))
    ax.set_xlabel("Week of the project calendar", fontsize=8.5)
    ax.tick_params(axis="x", labelsize=7.5, length=2)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color="#D5D5D5", lw=0.7)
    ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    done_p = plt.Rectangle((0, 0), 1, 1, facecolor="#4A4A4A", edgecolor="black", lw=0.9)
    todo_p = plt.Rectangle((0, 0), 1, 1, facecolor="white", edgecolor="black", lw=0.9,
                           hatch="///")
    ax.legend([done_p, todo_p], ["complete", "in progress / planned"],
              fontsize=7.5, frameon=False, loc="lower right", ncol=2,
              bbox_to_anchor=(1.0, -0.26))
    fig.tight_layout()
    save(fig, "fig3_1")


# ----------------------------------------------------------------- Fig 4.1
def fig_4_1():
    fig, ax = canvas(7.0, 3.1)
    incs = ["Increment 1\nPayload and tag", "Increment 2\nBlock mapping",
            "Increment 3\nEmbed and detect", "Increment 4\nRecovery and rho",
            "Increment 5\nHarness and metrics", "Increment 6\nGrid and gate",
            "Increment 7\nApplications"]
    w, gap = 12.4, 1.9
    x = 1.0
    base = 44
    tops = []
    for i, s in enumerate(incs):
        rise = 2.2 * i
        b = box(ax, x, base + rise, w, 19, s + "\n\ndesign > build > test", fs=6.5,
                fill=LIGHT)
        tops.append(b)
        if i:
            arrow(ax, (x - gap, base + 2.2 * (i - 1) + 14.0), (x - 0.3, base + rise + 9.5))
        x += w + gap
    ax.text(50, 95, "Each increment ends in a runnable end-to-end test, and the sanity "
                    "gate must run clean before the next one begins.", fontsize=7.2,
            ha="center", style="italic")
    fb = box(ax, 10, 10, 78, 11, "Measurement feedback: a defect or an unexpected result "
                                 "re-opens the increment that caused it", fs=7.4, fill=WHITE,
             ls="--")
    arrow(ax, (87, base + 2.2 * 6), (87, 21.4), ls="--")
    arrow(ax, (11, 21.4), (11, base - 0.4), ls="--")
    save(fig, "fig4_1")


# ----------------------------------------------------------------- Fig 5.1
def fig_5_1():
    fig, ax = canvas(7.2, 3.4)
    up = ["Original\nimage  I", "Block\npartition", "Descriptor\nencode",
          "Key-seeded\nblock map", "Keyed tag\n(HMAC)", "Watermarked\nimage  Iw"]
    lo = ["Received\nimage  I'", "LSB\nextract", "Recompute\ntags",
          "Tamper mask\n+ refine", "Recovery\nengine", "Repaired\nimage"]
    w, gap, h = 14.0, 2.6, 15
    ax.text(0.6, 92, "Stage 1 — Embedding", fontsize=8, fontweight="bold")
    xs = []
    x = 0.6
    for i, s in enumerate(up):
        fill = WHITE if i in (0, 5) else LIGHT
        xs.append(box(ax, x, 72, w, h, s, fs=7.2, fill=fill))
        x += w + gap
    for p, q in zip(xs, xs[1:]):
        arrow(ax, right(p), left(q))

    ax.text(0.6, 47, "Stages 3 and 4 — Verification and recovery", fontsize=8,
            fontweight="bold")
    ys = []
    x = 0.6
    for i, s in enumerate(lo):
        fill = WHITE if i in (0, 5) else LIGHT
        ys.append(box(ax, x, 27, w, h, s, fs=7.2, fill=fill))
        x += w + gap
    for p, q in zip(ys, ys[1:]):
        arrow(ax, right(p), left(q))

    # distribution path
    ax.plot([ctr(xs[5])[0], ctr(xs[5])[0]], [72, 60], "--", color="black", lw=1.0)
    ax.plot([ctr(xs[5])[0], ctr(ys[0])[0]], [60, 60], "--", color="black", lw=1.0)
    arrow(ax, (ctr(ys[0])[0], 60), (ctr(ys[0])[0], 42.4), ls="--")
    ax.text(50, 61, "Stage 2 — Distribution (tampering may occur here)", fontsize=7.2,
            ha="center", style="italic")

    ku = box(ax, 36, 90.5, 42, 8.5, "Secret key  Ks   +   image identifier  ID", fs=7.2,
             fill=MID)
    arrow(ax, (ctr(xs[3])[0], 90.3), (ctr(xs[3])[0], 87.2), ls=":")
    arrow(ax, (ctr(xs[4])[0], 90.3), (ctr(xs[4])[0], 87.2), ls=":")
    kl = box(ax, 36, 8, 42, 8.5, "Secret key  Ks   +   image identifier  ID", fs=7.2,
             fill=MID)
    arrow(ax, (ctr(ys[2])[0], 16.7), (ctr(ys[2])[0], 26.8), ls=":")
    arrow(ax, (ctr(ys[4])[0], 16.7), (ctr(ys[4])[0], 26.8), ls=":")
    save(fig, "fig5_1")


# ----------------------------------------------------------------- Fig 5.2
def fig_5_2():
    fig, ax = canvas(7.0, 2.9)
    ax.text(0.5, 93, "Per-block payload at B = 8:  cap(8) = 2 x 8^2 = 128 bits per channel",
            fontsize=8.5, fontweight="bold")
    y = 70
    tagw = 100 * 32 / 128
    box(ax, 0.5, y, tagw - 0.5, 15, "Authentication tag\n32 bits", fs=8, fill=MID,
        style="square")
    box(ax, tagw, y, 99.5 - tagw, 15, "Recovery descriptor of partner block\n96 bits",
        fs=8, fill=LIGHT, style="square")
    ax.annotate("", xy=(0.5, y + 18.5), xytext=(99.5, y + 18.5),
                arrowprops=dict(arrowstyle="<|-|>", lw=0.9, color="black",
                                mutation_scale=7))
    ax.text(50, y + 19.6, "128 bits", fontsize=7.5, ha="center")

    y2 = 42
    cw = 99.0 / 12
    for i in range(12):
        box(ax, 0.5 + i * cw, y2, cw - 0.6, 13, f"c{i+1}\n8 b", fs=6.4, fill=WHITE,
            style="square", lw=0.9)
    line(ax, (tagw, y), (0.5, y2 + 13), ls=":")
    line(ax, (99.5, y), (99.5, y2 + 13), ls=":")
    ax.text(50, y2 - 4.5, "12 zig-zag DCT coefficients, each quantized to a signed "
                          "8-bit value:  12 x 8 = 96 bits exactly",
            fontsize=7.4, ha="center", style="italic")

    y3 = 6
    ax.text(0.5, y3 + 17, "written into the two least-significant bit-planes of the "
                          "block's 64 pixels", fontsize=7.4, style="italic")
    for i in range(16):
        box(ax, 0.5 + i * 6.2, y3, 5.4, 9, "", fill=LIGHT, style="square", lw=0.8)
        ax.text(0.5 + i * 6.2 + 2.7, y3 + 4.5, "b1b0", fontsize=5.2, ha="center",
                va="center")
    ax.text(99.5, y3 + 4.5, "...", fontsize=8, ha="right", va="center")
    save(fig, "fig5_2")


# ----------------------------------------------------------------- Fig 5.3
def fig_5_3():
    fig, ax = canvas(6.6, 3.4)
    n, m = 8, 6
    cw, ch = 9.6, 12.2
    x0, y0 = 4.0, 14.0
    cen = {}
    for r in range(m):
        for c in range(n):
            x = x0 + c * cw
            y = y0 + (m - 1 - r) * ch
            box(ax, x, y, cw - 0.9, ch - 0.9, "", fill=WHITE, style="square", lw=0.7)
            cen[(r, c)] = (x + (cw - 0.9) / 2, y + (ch - 0.9) / 2)
    pairs = [((4, 1), (1, 6)), ((1, 2), (5, 5)), ((0, 5), (3, 0))]
    for a, b in pairs:
        for cell in (a, b):
            box(ax, x0 + cell[1] * cw, y0 + (m - 1 - cell[0]) * ch, cw - 0.9, ch - 0.9,
                "", fill=LIGHT, style="square", lw=0.7)
    for a, b in pairs:
        arrow(ax, cen[a], cen[b], rad=0.25, lw=1.3)
        ax.text(cen[a][0], cen[a][1], "i", fontsize=7.5, ha="center", va="center",
                fontweight="bold")
        ax.text(cen[b][0], cen[b][1], "m(i)", fontsize=6.4, ha="center", va="center")
    # separation indicator: a straight measured distance, not a circle, because the
    # two axes of this canvas do not share a scale
    pa, pb = cen[(4, 1)], cen[(1, 6)]
    ax.annotate("", xy=pa, xytext=pb,
                arrowprops=dict(arrowstyle="<|-|>", lw=0.9, color="black", ls=":",
                                mutation_scale=7, shrinkA=0, shrinkB=0))
    ax.text((pa[0] + pb[0]) / 2 + 3, (pa[1] + pb[1]) / 2 - 5.5,
            "separation >= d_min", fontsize=7.0, style="italic")
    ax.text(50, 95, "m is a single K-cycle: every block is visited exactly once, so no "
                    "block maps to itself and no two blocks map to each other",
            fontsize=7.2, ha="center", style="italic")
    ax.text(50, 5.0, "d_min = (1/4) min(M, N)", fontsize=7.8, ha="center")
    save(fig, "fig5_3")


# ------------------------------------------------------- DFD helpers / 5.4-5.6
def dfd_proc(ax, x, y, r, num, name, fs=7.0):
    c = Circle((x, y), r, facecolor=LIGHT, edgecolor="black", lw=1.1)
    ax.add_patch(c)
    ax.text(x, y + r * 0.30, num, fontsize=fs + 0.4, ha="center", va="center",
            fontweight="bold")
    ax.text(x, y - r * 0.25, name, fontsize=fs, ha="center", va="center",
            linespacing=1.2)
    return (x, y, r)


def dfd_store(ax, x, y, w, h, tag, name, fs=7.0):
    ax.add_patch(Rectangle((x, y), w, h, facecolor=WHITE, edgecolor="black", lw=1.1))
    ax.plot([x + w * 0.16, x + w * 0.16], [y, y + h], color="black", lw=1.1)
    ax.text(x + w * 0.08, y + h / 2, tag, fontsize=fs, ha="center", va="center")
    ax.text(x + w * 0.16 + (w * 0.84) / 2, y + h / 2, name, fontsize=fs, ha="center",
            va="center")
    return (x, y, w, h)


def pedge(p, q):
    """point on circle p facing q"""
    x, y, r = p
    dx, dy = q[0] - x, q[1] - y
    d = math.hypot(dx, dy) or 1
    return (x + dx / d * r, y + dy / d * r)


def fig_5_4():
    fig, ax = canvas(6.8, 3.2)
    owner = box(ax, 1, 62, 20, 16, "Content\nOwner", fs=8, style="square", fill=LIGHT)
    ver = box(ax, 1, 12, 20, 16, "Verifier", fs=8, style="square", fill=LIGHT)
    p = dfd_proc(ax, 57, 46, 17, "0", "Watermark-Guided\nTamper Localization\nand Recovery\nSystem", fs=6.8)
    d1 = dfd_store(ax, 76, 6, 23, 11, "D1", "Protected\nImage Library", fs=6.6)

    arrow(ax, (21.4, 74), pedge(p, (21.4, 74)))
    ax.text(23, 76.5, "original image, secret key", fontsize=6.3, style="italic")
    arrow(ax, pedge(p, (21.4, 62)), (21.4, 62))
    ax.text(23, 63.5, "watermarked image", fontsize=6.3, style="italic")
    arrow(ax, (21.4, 26), pedge(p, (21.4, 26)))
    ax.text(23, 28.0, "received image, secret key", fontsize=6.3, style="italic")
    arrow(ax, pedge(p, (21.4, 14)), (21.4, 14))
    ax.text(23, 15.5, "tamper map, repaired image, audit record", fontsize=6.3,
            style="italic")
    arrow(ax, pedge(p, (82, 17)), (82, 17.3))
    arrow(ax, (92, 17.3), pedge(p, (92, 17)))
    save(fig, "fig5_4")


def fig_5_5():
    fig, ax = canvas(7.2, 3.8)
    owner = box(ax, 1, 72, 17, 14, "Content\nOwner", fs=7.6, style="square", fill=LIGHT)
    ver = box(ax, 1, 10, 17, 14, "Verifier", fs=7.6, style="square", fill=LIGHT)
    p1 = dfd_proc(ax, 38, 79, 12.5, "1.0", "Embed\nWatermark", fs=6.6)
    p2 = dfd_proc(ax, 76, 79, 12.5, "2.0", "Store and\nDistribute", fs=6.6)
    p3 = dfd_proc(ax, 38, 21, 12.5, "3.0", "Verify and\nLocalize", fs=6.6)
    p4 = dfd_proc(ax, 76, 21, 12.5, "4.0", "Recover\nContent", fs=6.6)
    d1 = dfd_store(ax, 70, 52, 29, 9, "D1", "Protected Image Library", fs=6.3)
    k = box(ax, 24, 46, 28, 8, "key Ks  +  identifier ID", fs=6.8, fill=MID)

    arrow(ax, right(owner), pedge(p1, right(owner)))
    ax.text(21, 81.5, "image", fontsize=6.1, style="italic")
    arrow(ax, pedge(p1, (p2[0], p2[1])), pedge(p2, (p1[0], p1[1])))
    ax.text(57, 81.0, "watermarked image", fontsize=6.1, ha="center", style="italic")
    arrow(ax, pedge(p2, (ctr(d1)[0] + 6, 61)), (ctr(d1)[0] + 6, 61.2))
    arrow(ax, right(ver), pedge(p3, right(ver)))
    ax.text(21, 23.5, "received image", fontsize=6.1, style="italic")
    arrow(ax, pedge(p3, (p4[0], p4[1])), pedge(p4, (p3[0], p3[1])))
    ax.text(57, 23.0, "block mask", fontsize=6.1, ha="center", style="italic")
    arrow(ax, pedge(p3, (18.5, 13)), (18.6, 13))
    ax.text(20, 8.5, "audit record", fontsize=6.1, style="italic")
    arrow(ax, pedge(p4, (76, 6)), (76, 5.5))
    ax.plot([76, 20], [5.5, 5.5], "-", color="black", lw=1.1)
    arrow(ax, (20, 5.5), (18.6, 10.5))
    ax.text(48, 2.0, "repaired image and recoverability rate rho", fontsize=6.1,
            ha="center", style="italic")
    arrow(ax, top(k), pedge(p1, ctr(k)), ls=":")
    arrow(ax, bot(k), pedge(p3, ctr(k)), ls=":")
    arrow(ax, right(k), pedge(p4, ctr(k)), ls=":")
    arrow(ax, (ctr(d1)[0] - 6, 52), pedge(p4, (ctr(d1)[0] - 6, 52)), ls="--")
    save(fig, "fig5_5")


def fig_5_6():
    fig, ax = canvas(7.2, 3.8)
    ax.text(0.5, 96, "Process 3.0 — Verify and Localize", fontsize=8, fontweight="bold")
    a = dfd_proc(ax, 13, 76, 11.5, "3.1", "Extract LSB\nPayload", fs=6.3)
    b = dfd_proc(ax, 38, 76, 11.5, "3.2", "Recompute\nTags", fs=6.3)
    c = dfd_proc(ax, 63, 76, 11.5, "3.3", "Compare,\nBuild Block\nMask", fs=6.3)
    d = dfd_proc(ax, 88, 76, 11.5, "3.4", "Refine and\nExpand to\nPixel Mask", fs=6.3)
    for p, q in ((a, b), (b, c), (c, d)):
        arrow(ax, pedge(p, (q[0], q[1])), pedge(q, (p[0], p[1])))
    ax.text(25.5, 88.5, "128 bits", fontsize=6.1, ha="center", style="italic")
    ax.text(50.5, 88.5, "recomputed tag", fontsize=6.1, ha="center", style="italic")
    ax.text(75.5, 88.5, "per-channel OR", fontsize=6.1, ha="center", style="italic")

    ax.plot([0, 100], [57, 57], "--", color=DARK, lw=0.8)
    ax.text(0.5, 50, "Process 4.0 — Recover Content", fontsize=8, fontweight="bold")
    e = dfd_proc(ax, 14, 26, 11.5, "4.1", "Partition\nFlagged Set", fs=6.3)
    f = dfd_proc(ax, 45, 38, 11.5, "4.2", "Decode\nPartner\nDescriptor", fs=6.3)
    g = dfd_proc(ax, 76, 38, 11.5, "4.3", "Write\nRecovered\nPixels", fs=6.3)
    h = dfd_proc(ax, 45, 11, 11.5, "4.4", "Mark\nUnrecoverable", fs=6.3)
    arrow(ax, pedge(d, (d[0], 57)), pedge(e, (e[0], 45)), ls="--")
    ax.text(57, 59.5, "pixel mask and block mask pass to process 4.0", fontsize=6.4,
            ha="center", style="italic")
    arrow(ax, pedge(e, (f[0], f[1])), pedge(f, (e[0], e[1])))
    ax.text(28, 36.5, "partner intact", fontsize=6.1, style="italic")
    arrow(ax, pedge(f, (g[0], g[1])), pedge(g, (f[0], f[1])))
    arrow(ax, pedge(e, (h[0], h[1])), pedge(h, (e[0], e[1])))
    ax.text(26, 12.0, "partner flagged", fontsize=6.1, style="italic")
    out = box(ax, 86, 10, 13, 14, "Repaired\nimage\n+ rho", fs=6.6, style="square")
    arrow(ax, pedge(g, (92, 24)), top(out))
    arrow(ax, pedge(h, ctr(out)), left(out))
    save(fig, "fig5_6")


# ----------------------------------------------------------------- Fig 5.7
def fig_5_7():
    fig, ax = canvas(7.0, 3.5)

    def entity(x, y, w, title, attrs, dashed=False, fs=6.5):
        hh = 7.5
        h = hh + len(attrs) * 5.0
        ax.add_patch(Rectangle((x, y), w, h, facecolor=WHITE, edgecolor="black",
                               lw=1.1, linestyle="--" if dashed else "-"))
        ax.add_patch(Rectangle((x, y + h - hh), w, hh, facecolor=MID, edgecolor="black",
                               lw=1.1, linestyle="--" if dashed else "-"))
        ax.text(x + w / 2, y + h - hh / 2, title, fontsize=fs + 0.8, ha="center",
                va="center", fontweight="bold")
        for i, a in enumerate(attrs):
            ax.text(x + 1.6, y + h - hh - 3.2 - i * 5.0, a, fontsize=fs, va="center")
        return (x, y, w, h)

    pi = entity(32, 10, 36,
                "PROTECTED_IMAGE",
                ["id  (PK)", "name", "created_at", "height,  width", "block,  variant",
                 "key,  key_encrypted", "image_id", "png  (BLOB)", "sha256",
                 "psnr,  ssim,  blocks", "deleted_at"])
    kp = entity(1, 52, 27, "KEY_PROFILE",
                ["key_id  (PK)", "label", "created_at"], dashed=True)
    ve = entity(72, 46, 27, "VERIFICATION_EVENT",
                ["event_id  (PK)", "id  (FK)", "verified_at", "n_flagged_blocks",
                 "rho"], dashed=True)

    def dia(x, y, w, h, s):
        ax.add_patch(Polygon([(x, y + h / 2), (x + w / 2, y + h), (x + w, y + h / 2),
                              (x + w / 2, y)], closed=True, facecolor=LIGHT,
                             edgecolor="black", lw=1.0))
        ax.text(x + w / 2, y + h / 2, s, fontsize=6.3, ha="center", va="center")
        return (x, y, w, h)

    d1 = dia(1, 20, 22, 13, "protected\nunder")
    d2 = dia(72, 20, 22, 13, "subject of")
    line(ax, right(d1), left(pi))
    line(ax, top(d1), bot(kp))
    line(ax, right(pi), left(d2))
    line(ax, top(d2), bot(ve))
    ax.text(25.5, 28.5, "N", fontsize=7, ha="center")
    ax.text(13.5, 48, "1", fontsize=7, ha="center")
    ax.text(70, 28.5, "1", fontsize=7, ha="center")
    ax.text(84, 42, "N", fontsize=7, ha="center")
    ax.text(50, 97, "Solid entity is persisted in the current build; dashed entities are "
                    "conceptual, required by a deployment but not yet stored.",
            fontsize=6.9, ha="center", style="italic")
    save(fig, "fig5_7")


# ----------------------------------------------------------------- Fig 5.8
def fig_5_8():
    fig, ax = canvas(7.8, 4.1)
    ax.add_patch(Rectangle((27, 2), 46, 94, facecolor=WHITE, edgecolor="black", lw=1.1))
    ax.text(50, 92, "Watermarking System", fontsize=8.5, ha="center", fontweight="bold")

    def actor(x, y, label):
        ax.add_patch(Circle((x, y + 7.0), 2.2, fill=False, lw=1.1))
        line(ax, (x, y + 4.8), (x, y - 1.0))
        line(ax, (x - 3.2, y + 3.0), (x + 3.2, y + 3.0))
        line(ax, (x, y - 1.0), (x - 2.8, y - 5.8))
        line(ax, (x, y - 1.0), (x + 2.8, y - 5.8))
        ax.text(x, y - 9.0, label, fontsize=7.4, ha="center")
        return (x, y + 2)

    def uc(y, s, fs=6.6):
        ax.add_patch(Ellipse((50, y), 38, 6.0, facecolor=LIGHT, edgecolor="black", lw=1.0))
        ax.text(50, y, s, fontsize=fs, ha="center", va="center")
        return (50, y)

    owner = actor(11, 68, "Content\nOwner")
    ver = actor(11, 26, "Verifier")
    admin = actor(89, 30, "Administrator")

    labels = ["Protect Image", "Protect Batch", "Browse Library",
              "Download Protected Image", "Apply Simulated Damage", "Verify Image",
              "Extract Payload", "View Per-Block Audit", "Repair Image",
              "Export Report", "Run Attack Demonstration", "Delete Record"]
    ys = [86, 78.5, 71, 63.5, 56, 46.5, 39, 31.5, 24, 16.5, 9, 2.5]
    U = {lab: uc(y, lab) for lab, y in zip(labels, ys)}

    for lab in labels[:5]:
        line(ax, owner, (31.5, U[lab][1]))
    for lab in ["Verify Image", "View Per-Block Audit", "Repair Image", "Export Report",
                "Run Attack Demonstration"]:
        line(ax, ver, (31.5, U[lab][1]))
    for lab in ["Browse Library", "Delete Record"]:
        line(ax, admin, (68.5, U[lab][1]))

    arrow(ax, (62, U["Verify Image"][1] - 2.4), (62, U["Extract Payload"][1] + 2.4),
          ls="--")
    ax.text(70.5, (U["Verify Image"][1] + U["Extract Payload"][1]) / 2, "<<include>>",
            fontsize=5.8, ha="center", style="italic")
    arrow(ax, (38, U["Repair Image"][1] + 2.4), (38, U["Verify Image"][1] - 2.4),
          ls="--", rad=0.35)
    ax.text(26.5, (U["Verify Image"][1] + U["Repair Image"][1]) / 2, "<<extend>>",
            fontsize=5.8, ha="center", style="italic")
    save(fig, "fig5_8")


# ----------------------------------------------------------------- Fig 5.9
def fig_5_9():
    fig, ax = canvas(7.2, 4.4)

    def cls(x, y, w, name, ops, fs=6.1):
        hh = 6.6
        h = hh + len(ops) * 4.4 + 1.4
        ax.add_patch(Rectangle((x, y), w, h, facecolor=WHITE, edgecolor="black", lw=1.1))
        ax.add_patch(Rectangle((x, y + h - hh), w, hh, facecolor=MID, edgecolor="black",
                               lw=1.1))
        ax.text(x + w / 2, y + h - hh / 2, name, fontsize=fs + 1.0, ha="center",
                va="center", fontweight="bold")
        for i, o in enumerate(ops):
            ax.text(x + 1.4, y + h - hh - 3.2 - i * 4.4, o, fontsize=fs, va="center")
        return (x, y, w, h)

    bm = cls(1, 68, 30, "BlockMap",
             ["+ build(Ks, K, d_min)", "+ m(i)  /  m_inv(i)", "+ verify_R1_R3()"])
    pc = cls(34, 68, 32, "PayloadCodec",
             ["+ budget(B)", "+ msb(a)", "+ tag(Ks, ID, i, blk, r)",
              "+ encode / decode descriptor", "+ pack / unpack LSB"])
    em = cls(69, 68, 30, "Embedder",
             ["+ embed_image(img, Ks,", "   ID, block, variant)", "- shift_lsb_pairs()"])
    dt = cls(1, 36, 30, "Detector",
             ["+ detect_image(...)", "+ refine_mask()", "+ expand_mask()"])
    dr = cls(34, 36, 32, "DetectResult",
             ["+ block_mask", "+ pixel_mask", "+ audit record"])
    re = cls(69, 36, 30, "RecoveryEngine",
             ["+ recover_image(...)", "+ recoverability_rate()", "+ mark_unrecoverable()"])
    th = cls(1, 3, 23, "TamperHarness",
             ["+ splice()  + inpaint()", "+ crop_refill()", "+ noise()"], fs=5.8)
    mt = cls(26, 3, 23, "Metrics",
             ["+ psnr()  + ssim()", "+ localization_scores()", "+ in_region_metrics()"],
             fs=5.8)
    io = cls(51, 3, 23, "ImageIO",
             ["+ decode()", "+ sniff()", "+ save()"], fs=5.8)
    ls = cls(76, 3, 23, "LibraryStore",
             ["+ insert()  + fetch()", "+ soft_delete()", "+ list_records()"], fs=5.8)

    arrow(ax, right(bm), left(pc), ls="--")
    arrow(ax, right(pc), left(em), ls="--")
    arrow(ax, top(dt), (ctr(pc)[0] - 11, 68), ls="--", rad=0.12)
    arrow(ax, right(dt), left(dr), ls="--")
    arrow(ax, right(dr), left(re), ls="--")
    arrow(ax, top(re), bot(em), ls="--")
    arrow(ax, right(th), left(mt), ls="--")
    arrow(ax, top(io), (ctr(re)[0] - 12, 36), ls="--", rad=0.10)
    arrow(ax, top(ls), bot(re), ls="--")
    save(fig, "fig5_9")


# ----------------------------------------------------------------- Fig 5.10
def fig_5_10():
    fig, ax = canvas(7.2, 4.3)
    actors = ["Content\nOwner", "Web\nServer", "Embedder", "PayloadCodec\n+ BlockMap",
              "Detector", "RecoveryEngine", "LibraryStore"]
    xs = np.linspace(8, 93, len(actors))
    for x, a in zip(xs, actors):
        box(ax, x - 6.5, 90, 13, 8, a, fs=6.1, fill=LIGHT, style="square")
        ax.plot([x, x], [6, 90], "--", color=DARK, lw=0.8)

    msgs = [
        (0, 1, "POST /api/protect (image, key)", 85),
        (1, 2, "embed_image(img, Ks, ID)", 80),
        (2, 3, "budget, descriptors, m(i), tags", 75),
        (3, 2, "payload bits", 70.5),
        (2, 1, "watermarked image, PSNR, SSIM", 66),
        (1, 6, "insert(record)", 61.5),
        (1, 0, "protected image + metrics", 57),
        (0, 1, "POST /api/damage (region, class)", 50),
        (1, 0, "tampered image", 45.5),
        (0, 1, "POST /api/check (image, key)", 39),
        (1, 4, "detect_image(...)", 34.5),
        (4, 1, "block mask, pixel mask, audit", 30),
        (1, 0, "tamper map", 25.5),
        (0, 1, "POST /api/repair", 19),
        (1, 5, "recover_image(mask, payload)", 14.5),
        (5, 1, "repaired image, rho", 10.5),
        (1, 0, "repaired image + rho", 6.8),
    ]
    for a, b, s, y in msgs:
        ret = xs[b] < xs[a]
        arrow(ax, (xs[a], y), (xs[b], y), ls="--" if ret else "-", lw=0.9)
        ax.text((xs[a] + xs[b]) / 2, y + 0.9, s, fontsize=5.7, ha="center",
                va="bottom", style="italic" if ret else "normal")
    save(fig, "fig5_10")


# ----------------------------------------------------------------- Fig 5.11
def fig_5_11():
    fig, ax = canvas(7.4, 4.0)
    ax.add_patch(Circle((50, 96), 2.0, facecolor="black"))
    a = box(ax, 28, 85, 44, 7.5, "Read received image, key and identifier", fs=6.8, fill=LIGHT)
    b = box(ax, 28, 75, 44, 7.5, "Extract 128 payload bits from block i", fs=6.8, fill=LIGHT)
    c = box(ax, 28, 65, 44, 7.5, "Recompute tag over MSB(b_i) and carried descriptor",
            fs=6.5, fill=LIGHT)

    def dec(x, y, w, h, s, fs=6.3):
        ax.add_patch(Polygon([(x, y + h / 2), (x + w / 2, y + h), (x + w, y + h / 2),
                              (x + w / 2, y)], closed=True, facecolor=WHITE,
                             edgecolor="black", lw=1.1))
        ax.text(x + w / 2, y + h / 2, s, fontsize=fs, ha="center", va="center")
        return (x, y, w, h)

    d = dec(32, 51, 36, 11, "tag matches?")
    e = box(ax, 4, 52, 22, 7.5, "Flag block i", fs=6.8, fill=MID)
    f = box(ax, 74, 52, 22, 7.5, "Pass block i", fs=6.8)
    g = box(ax, 28, 39, 44, 7.5, "Refine mask, expand to pixel mask", fs=6.8, fill=LIGHT)
    h = dec(32, 25, 36, 11, "partner m(i) intact?")
    i_ = box(ax, 2, 26, 26, 7.5, "Decode descriptor,\nwrite recovered block", fs=6.3,
             fill=MID)
    j = box(ax, 72, 26, 26, 7.5, "Mark block\nunrecoverable", fs=6.3, fill=MID)
    k = box(ax, 28, 12, 44, 7.5, "Compose output, report rho", fs=6.8, fill=LIGHT)
    ax.add_patch(Circle((50, 5), 2.6, fill=False, lw=1.1))
    ax.add_patch(Circle((50, 5), 1.5, facecolor="black"))

    arrow(ax, (50, 94), top(a)); arrow(ax, bot(a), top(b)); arrow(ax, bot(b), top(c))
    arrow(ax, bot(c), (50, 62))
    arrow(ax, (32, 56.5), right(e), text="no", fs=6.0, tdy=0.6)
    arrow(ax, (68, 56.5), left(f), text="yes", fs=6.0, tdy=0.6)
    arrow(ax, bot(e), (15, 46.7)); ax.plot([15, 28], [46.7, 46.7], "-", color="black", lw=1.1)
    arrow(ax, bot(f), (85, 46.7)); ax.plot([72, 85], [46.7, 46.7], "-", color="black", lw=1.1)
    ax.text(50, 47.6, "repeat for every block and channel (per-channel OR)", fontsize=6.0,
            ha="center", style="italic")
    arrow(ax, bot(g), (50, 36))
    arrow(ax, (32, 30.5), right(i_), text="yes", fs=6.0, tdy=0.6)
    arrow(ax, (68, 30.5), left(j), text="no", fs=6.0, tdy=0.6)
    arrow(ax, bot(i_), (15, 19.5)); ax.plot([15, 28], [19.5, 19.5], "-", color="black", lw=1.1)
    arrow(ax, bot(j), (85, 19.5)); ax.plot([72, 85], [19.5, 19.5], "-", color="black", lw=1.1)
    arrow(ax, bot(k), (50, 7.6))
    save(fig, "fig5_11")


# ----------------------------------------------------------------- Fig 5.12
def fig_5_12():
    fig, ax = canvas(7.0, 3.2)
    ax.add_patch(Circle((2.4, 77.5), 1.8, facecolor="black"))
    s1 = box(ax, 7, 70, 19, 15, "Unprotected", fs=7.6)
    s2 = box(ax, 31, 70, 19, 15, "Protected", fs=7.6, fill=LIGHT)
    s3 = box(ax, 55, 70, 19, 15, "Distributed", fs=7.6, fill=LIGHT)
    s4 = box(ax, 79, 70, 20, 15, "Under\nVerification", fs=7.6, fill=LIGHT)
    s5 = box(ax, 8, 30, 20, 15, "Authentic", fs=7.6)
    s6 = box(ax, 36, 30, 20, 15, "Tampered", fs=7.6, fill=MID)
    s7 = box(ax, 64, 30, 20, 15, "Recovered", fs=7.6, fill=LIGHT)
    s8 = box(ax, 8, 4, 20, 13, "Archived", fs=7.6)
    ax.add_patch(Circle((2.4, 10.5), 2.4, fill=False, lw=1.1))
    ax.add_patch(Circle((2.4, 10.5), 1.4, facecolor="black"))

    arrow(ax, (4.2, 77.5), left(s1))
    arrow(ax, right(s1), left(s2), text="embed(Ks, ID)", fs=5.9)
    arrow(ax, right(s2), left(s3), text="publish", fs=5.9)
    arrow(ax, right(s3), left(s4), text="receive", fs=5.9)

    # one branch out of Under Verification, carried on a bus at y = 58
    ax.plot([89, 89], [70, 58], "-", color="black", lw=1.1)
    ax.plot([18, 89], [58, 58], "-", color="black", lw=1.1)
    arrow(ax, (18, 58), (18, 45.4))
    ax.text(19.3, 50.5, "all tags verify", fontsize=6.0, style="italic")
    arrow(ax, (46, 58), (46, 45.4))
    ax.text(47.3, 50.5, "mismatch found", fontsize=6.0, style="italic")

    arrow(ax, right(s6), left(s7), text="recover from partners", fs=5.9)
    arrow(ax, bot(s5), top(s8), text="retain", fs=5.9, tdx=4.5)
    ax.plot([74, 74], [30, 10.5], "-", color="black", lw=1.1)
    arrow(ax, (74, 10.5), (28.4, 10.5))
    ax.text(51, 11.7, "archive with the recovery report", fontsize=6.0, ha="center",
            style="italic")
    arrow(ax, left(s8), (4.9, 10.5))
    ax.text(50, 95, "Recovered may be complete or partial: blocks whose partner was also "
                    "flagged stay marked unrecoverable.", fontsize=6.9, ha="center",
            style="italic")
    save(fig, "fig5_12")


# ----------------------------------------------------------------- Fig 5.13
def fig_5_13():
    fig, ax = canvas(7.0, 3.6)

    def comp(x, y, w, h, s, fs=7.0, fill=LIGHT):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor="black", lw=1.1))
        ax.add_patch(Rectangle((x - 2.0, y + h - 5.5), 4.6, 3.0, facecolor=WHITE,
                               edgecolor="black", lw=0.9))
        ax.add_patch(Rectangle((x - 2.0, y + h - 10.0), 4.6, 3.0, facecolor=WHITE,
                               edgecolor="black", lw=0.9))
        ax.text(x + w / 2 + 1.5, y + h / 2, s, fontsize=fs, ha="center", va="center",
                linespacing=1.3)
        return (x, y, w, h)

    harn = comp(5, 60, 24, 26, "<<component>>\nExperiment Harness\ntamper · metrics ·\n"
                               "run_experiments ·\nsanity_gate", fs=5.9)
    core = comp(37, 60, 30, 26, "<<component>>\nCore Library\npayload · blockmap ·\n"
                                "embed · detect · recover", fs=6.3, fill=MID)
    brow = comp(75, 72, 23, 14, "<<component>>\nBrowser User\nInterface", fs=6.3,
                fill=WHITE)
    web = comp(75, 46, 23, 16, "<<component>>\nFlask Web\nApplication", fs=6.3)
    db = comp(75, 20, 23, 16, "<<component>>\nSQLite Protected\nImage Library", fs=6.1)
    demo = comp(37, 28, 30, 16, "<<component>>\nStreamlit Demonstration\nInterface",
                fs=6.3)
    rep = comp(5, 32, 24, 16, "<<component>>\nReport and Figure\nBuilders", fs=6.1)
    grid = comp(5, 5, 24, 14, "<<artifact>>\nruns.csv\nresult grid", fs=6.3, fill=WHITE)

    arrow(ax, right(harn), left(core), ls="--", text="uses", fs=5.8)
    arrow(ax, (67, 62), (76, 59), ls="--")
    ax.text(70.5, 64.5, "uses", fontsize=5.8, style="italic")
    arrow(ax, top(web), bot(brow), ls="--")
    ax.text(88.5, 65.5, "HTTP / JSON", fontsize=5.8, style="italic")
    arrow(ax, bot(web), top(db), ls="--")
    ax.text(88.5, 40.0, "SQL", fontsize=5.8, style="italic")
    arrow(ax, bot(core), top(demo), ls="--")
    arrow(ax, bot(harn), top(grid), ls="--")
    arrow(ax, (24, 19), (24, 31.6), ls="--")
    ax.text(50, 95, "Dashed arrows are dependencies; the arrow points at the component "
                    "whose interface is used.", fontsize=6.9, ha="center", style="italic")
    save(fig, "fig5_13")


# ----------------------------------------------------------------- Fig 5.14
def fig_5_14():
    fig, ax = canvas(7.0, 3.1)

    def node(x, y, w, h, s, fs=7.0, fill=LIGHT):
        d = 4.0
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor="black", lw=1.2))
        ax.add_patch(Polygon([(x, y + h), (x + d, y + h + d), (x + w + d, y + h + d),
                              (x + w, y + h)], closed=True, facecolor=WHITE,
                             edgecolor="black", lw=1.0))
        ax.add_patch(Polygon([(x + w, y), (x + w + d, y + d), (x + w + d, y + h + d),
                              (x + w, y + h)], closed=True, facecolor=WHITE,
                             edgecolor="black", lw=1.0))
        ax.text(x + w / 2, y + h - 4.5, s, fontsize=fs, ha="center", va="top",
                linespacing=1.3)
        return (x, y, w, h)

    ws = node(5, 10, 58, 70, "<<device>>  Commodity Workstation\n"
                             "x86-64 or ARM CPU · no accelerator", fs=7.2, fill=WHITE)
    rt = box(ax, 9, 40, 23, 22, "<<execution environment>>\nPython 3.10 Runtime\n\n"
                                "Core Library\nFlask Server", fs=6.0, fill=LIGHT)
    dbf = box(ax, 37, 45, 22, 13, "<<artifact>>\nlibrary.db\n(SQLite file)", fs=6.0,
              fill=WHITE)
    hn = box(ax, 9, 15, 50, 16, "<<execution environment>>\nOffline Experiment Harness\n"
                                "produces runs.csv, tables and figures", fs=6.0, fill=LIGHT)
    cl = node(69, 38, 24, 32, "<<device>>\nClient Machine", fs=7.2, fill=WHITE)
    br = box(ax, 72, 42, 18, 15, "<<component>>\nWeb Browser\n(HTML / JS UI)", fs=6.0,
             fill=LIGHT)
    arrow(ax, right(rt), left(dbf), ls="--")
    ax.text(34.5, 56, "file I/O", fontsize=5.9, style="italic")
    arrow(ax, (63, 52), left(br))
    ax.text(66.0, 63.0, "HTTP over\nlocalhost", fontsize=5.9, ha="center", style="italic")
    arrow(ax, bot(rt), (20.5, 31.3), ls="--")
    ax.text(50, 92, "No server, no accelerator and no external network service is "
                    "required; the client may be the same machine.",
            fontsize=6.9, ha="center", style="italic")
    save(fig, "fig5_14")


# ------------------------------------------------------- Figs 7.1 and 7.2 (data)
def _grid():
    import pandas as pd
    d = pd.read_csv(REPO / "output/runs.csv")
    return d[(d.condition == "tamper") & (d.block_size == 8)
             & (d.recovery_variant.isin(["A", "C"]))]


def fig_7_1():
    g = _grid()
    a = g.groupby("tamper_ratio_nominal").recoverability_rate.agg(["mean", "std"])
    x = a.index.values
    fig, ax = plt.subplots(figsize=(5.6, 3.4), dpi=200)
    ax.fill_between(x, 1 - x, a["mean"], color="#D9D9D9", zorder=1,
                    label="margin above the structural bound")
    ax.plot(x, 1 - x, "--", color="black", lw=1.6, zorder=2,
            label="structural bound  1 - alpha")
    ax.errorbar(x, a["mean"], yerr=a["std"], fmt="o-", color="black", lw=1.8, ms=5.5,
                mfc="white", mew=1.5, capsize=3, zorder=3,
                label="measured recoverability  rho")
    for xi, yi in zip(x, a["mean"]):
        ax.annotate(f"{yi:.3f}", (xi, yi), textcoords="offset points", xytext=(0, 10),
                    ha="center", fontsize=7.5)
    ax.set_xlabel("nominal tamper ratio  alpha", fontsize=9)
    ax.set_ylabel("recoverability rate  rho", fontsize=9)
    ax.set_xticks(x); ax.set_ylim(0.20, 1.06)
    ax.tick_params(labelsize=8, length=2)
    ax.grid(color="#E0E0E0", lw=0.7); ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    fig.tight_layout()
    save(fig, "fig7_1")


def fig_7_2():
    g = _grid()
    a = g[g.recovery_variant == "A"].groupby("tamper_ratio_nominal")[
        ["psnr_in_region", "psnr_whole_unmarked"]].mean()
    c = g[g.recovery_variant == "C"].groupby("tamper_ratio_nominal").psnr_in_region.mean()
    x = a.index.values
    fig, ax = plt.subplots(figsize=(5.6, 3.4), dpi=200)
    ax.plot(x, c, "^-", color="black", lw=1.6, ms=6, mfc="white", mew=1.4,
            label="in-region PSNR, Variant C")
    ax.plot(x, a.psnr_in_region, "o-", color="black", lw=1.6, ms=5.5, mfc="#9A9A9A",
            mew=1.2, label="in-region PSNR, Variant A")
    ax.plot(x, a.psnr_whole_unmarked, "s--", color="black", lw=1.4, ms=5, mfc="white",
            mew=1.2, label="whole-image PSNR (unmarked convention)")
    ax.annotate("flat across every ratio", xy=(x[3], a.psnr_in_region.iloc[3]),
                xytext=(x[1] - 0.01, 36.5), fontsize=8,
                arrowprops=dict(arrowstyle="->", color="black", lw=1.0))
    ax.annotate("falls with coverage, not\nwith descriptor fidelity",
                xy=(x[5], a.psnr_whole_unmarked.iloc[5]), xytext=(x[0] + 0.01, 12.4),
                fontsize=8, arrowprops=dict(arrowstyle="->", color="black", lw=1.0))
    ax.set_xlabel("nominal tamper ratio  alpha", fontsize=9)
    ax.set_ylabel("PSNR (dB)", fontsize=9)
    ax.set_xticks(x); ax.set_ylim(10, 40)
    ax.tick_params(labelsize=8, length=2)
    ax.grid(color="#E0E0E0", lw=0.7); ax.set_axisbelow(True)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    ax.legend(frameon=False, fontsize=8, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    fig.tight_layout()
    save(fig, "fig7_2")


def fig_7_3():
    import matplotlib.image as mpimg
    panels = [("lena_original.png", "Original"),
              ("lena_watermarked.png", "Watermarked (45.73 dB)"),
              ("lena_tampered_splice.png", "Tampered (splice)"),
              ("lena_mask_overlay_splice.png", "Localized"),
              ("lena_recovered_splice.png", "Recovered")]
    fig, axes = plt.subplots(1, 5, figsize=(7.0, 1.8), dpi=200)
    for ax, (f, label) in zip(axes, panels):
        im = np.asarray(mpimg.imread(REPO / "output/images" / f))[:, :, :3]
        ax.imshow(im @ [0.299, 0.587, 0.114], cmap="gray")
        ax.set_xticks([]); ax.set_yticks([])
        for sp in ax.spines.values():
            sp.set_linewidth(0.8)
        ax.set_xlabel(label, fontsize=6.8, labelpad=3)
    fig.subplots_adjust(wspace=0.05, left=0.004, right=0.996, top=0.99, bottom=0.13)
    save(fig, "fig7_3")


if __name__ == "__main__":
    for fn in (fig_1_1, fig_2_1, fig_3_1, fig_4_1, fig_5_1, fig_5_2, fig_5_3, fig_5_4,
               fig_5_5, fig_5_6, fig_5_7, fig_5_8, fig_5_9, fig_5_10, fig_5_11,
               fig_5_12, fig_5_13, fig_5_14, fig_7_1, fig_7_2, fig_7_3):
        fn()
