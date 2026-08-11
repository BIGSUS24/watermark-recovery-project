"""IEEE-column-width figures for the paper: recovery-vs-ratio, rho-vs-ratio, and one
qualitative pipeline strip. Agg backend (no display); every figure is written as both
a 300 dpi PNG and a vector PDF into output/figures/.

Degrades gracefully on the still-running grid: `_series` simply omits any (tamper
class, ratio) bucket with no rows yet rather than crashing, so all three figures can be
regenerated at any point during the run and again once the grid is complete.
"""

import matplotlib
matplotlib.use("Agg")

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from detect import detect_image, expand_mask
from embed import embed_image, load_image
from metrics import aggregate_by, load_runs_csv
from payload import default_image_id
from recover import recover_image
from run_experiments import SEED_BASE_DEFAULT, load_manifest, make_key
from tamper import apply_tamper

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CSV = ROOT / "output" / "runs.csv"
FIGURES_DIR = ROOT / "output" / "figures"
IMAGES_DIR = ROOT / "output" / "images"

RATIOS = ("0.10", "0.25", "0.50")
RATIO_VALUES = {"0.10": 0.10, "0.25": 0.25, "0.50": 0.50}
TAMPER_ORDER = ("splice", "inpaint_removal", "crop_refill", "noise")
TAMPER_LABELS = {
    "splice": "Copy-paste splicing", "inpaint_removal": "Object removal",
    "crop_refill": "Crop-and-refill", "noise": "Noise corruption",
}
# Distinct dash pattern + marker per tamper class -- IEEE papers are printed and
# reviewed in black & white, so colour alone must never be the only distinguishing
# channel between series.
STYLE = {
    "splice": {"ls": "-", "marker": "o", "color": "tab:blue"},
    "inpaint_removal": {"ls": "--", "marker": "s", "color": "tab:orange"},
    "crop_refill": {"ls": "-.", "marker": "^", "color": "tab:green"},
    "noise": {"ls": ":", "marker": "D", "color": "tab:red"},
}

plt.rcParams.update({
    "font.family": "serif",
    "font.size": 8.5,
    "axes.titlesize": 9,
    "axes.labelsize": 8.5,
    "legend.fontsize": 7,
    "xtick.labelsize": 8,
    "ytick.labelsize": 8,
})


def _save(fig, out_stem: Path) -> None:
    out_stem = Path(out_stem)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_stem.with_suffix(".png"), dpi=300, bbox_inches="tight")
    fig.savefig(out_stem.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(fig)


def _series(rows: list[dict], tamper_class: str, value_key: str) -> tuple[list, list, list]:
    """(x, y, yerr) for one tamper class, skipping any ratio bucket with no rows yet."""
    sub = [r for r in rows if r["tamper_class"] == tamper_class]
    agg = aggregate_by(sub, ("tamper_ratio_nominal",), value_key)
    xs, ys, es = [], [], []
    for ratio_s in RATIOS:
        entry = agg.get((ratio_s,))
        if entry is None or entry["n"] == 0:
            continue
        xs.append(RATIO_VALUES[ratio_s]); ys.append(entry["mean"]); es.append(entry["std"])
    return xs, ys, es


def _plot_series(ax, rows: list[dict], value_key: str) -> bool:
    """Draw one line per tamper class on `ax`; returns True iff anything was plotted."""
    plotted = False
    for cls in TAMPER_ORDER:
        xs, ys, es = _series(rows, cls, value_key)
        if not xs:
            continue
        st = STYLE[cls]
        ax.errorbar(xs, ys, yerr=es, label=TAMPER_LABELS[cls], linestyle=st["ls"],
                    marker=st["marker"], color=st["color"], capsize=2, linewidth=1.2,
                    markersize=4)
        plotted = True
    ax.set_xticks([0.10, 0.25, 0.50])
    ax.set_xlabel("Tamper ratio (fraction of image area)")
    return plotted


# ---------------------------------------------------------------------------
# Figure 1: recovery vs. ratio
# ---------------------------------------------------------------------------

def recovery_vs_ratio(rows: list[dict], out_stem: Path) -> None:
    """psnr_whole_unmarked and psnr_in_region vs tamper ratio, one line per tamper class.

    Restricted to Variant A, main grid (block=8) -- the same scope as the paper's
    localization/recovery table, so the two never tell conflicting stories.
    """
    tamper_rows = [r for r in rows if r["condition"] == "tamper" and r["recovery_variant"] == "A"
                  and int(r["block_size"]) == 8]
    fig, axes = plt.subplots(1, 2, figsize=(6.8, 2.6))
    _plot_series(axes[0], tamper_rows, "psnr_whole_unmarked")
    axes[0].set_ylabel("Whole-image PSNR, unmarked (dB)")
    _plot_series(axes[1], tamper_rows, "psnr_in_region")
    axes[1].set_ylabel(r"In-region recovery PSNR $\mathrm{PSNR}_\Omega$ (dB)")

    handles, labels = axes[0].get_legend_handles_labels()
    if handles:
        fig.legend(handles, labels, loc="lower center", ncol=4, bbox_to_anchor=(0.5, -0.06),
                  frameon=False)
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    _save(fig, out_stem)


# ---------------------------------------------------------------------------
# Figure 2: recoverability rate vs. ratio
# ---------------------------------------------------------------------------

def rho_vs_ratio(rows: list[dict], out_stem: Path) -> None:
    """Recoverability rate vs tamper ratio, one line per tamper class (Variant A, block=8)."""
    tamper_rows = [r for r in rows if r["condition"] == "tamper" and r["recovery_variant"] == "A"
                  and int(r["block_size"]) == 8]
    fig, ax = plt.subplots(figsize=(3.4, 2.8))
    plotted = _plot_series(ax, tamper_rows, "recoverability_rate")
    ax.set_ylabel(r"Recoverability rate $\rho$")
    ax.set_ylim(0, 1.05)
    if plotted:
        ax.legend(loc="lower left", frameon=True)
    fig.tight_layout()
    _save(fig, out_stem)


# ---------------------------------------------------------------------------
# Figure 3: qualitative pipeline strip
# ---------------------------------------------------------------------------

def _overlay_mask(base: np.ndarray, pred_px: np.ndarray, unrecoverable_px: np.ndarray) -> np.ndarray:
    """Predicted-tamper mask in red @ 50% alpha; unrecoverable region in cyan (distinct hue)."""
    out = base.astype(np.float64)
    red, cyan, alpha = np.array([255.0, 0.0, 0.0]), np.array([0.0, 255.0, 255.0]), 0.5
    pred_only = pred_px & ~unrecoverable_px
    out[pred_only] = out[pred_only] * (1 - alpha) + red * alpha
    out[unrecoverable_px] = out[unrecoverable_px] * (1 - alpha) + cyan * alpha
    return np.clip(out, 0, 255).astype(np.uint8)


def _run_pipeline_live(image_name: str, tamper_class: str, ratio: float, variant: str,
                       block: int) -> dict[str, np.ndarray]:
    """Only used when output/images/ does not already hold the saved qualitative artifacts."""
    sample = next(s for s in load_manifest() if s["name"] == image_name)
    raw = load_image(sample["path"])
    key = make_key(0)
    iid = default_image_id(sample["name"], sample["shape"], block)
    wm, _ = embed_image(raw, key, iid, block=block, variant=variant)
    tres = apply_tamper(wm, tamper_class, ratio, sample["name"], SEED_BASE_DEFAULT)
    tampered = tres["tampered_image"]
    det = detect_image(tampered, key, iid, block=block, variant=variant)
    rec = recover_image(tampered, det, block=block, variant=variant)
    unrec_px = expand_mask(rec.unrecoverable_mask, block).astype(bool)
    overlay = _overlay_mask(tampered, det.pixel_mask.astype(bool), unrec_px)
    return {
        "Original": raw, "Watermarked": wm,
        f"Tampered ({tamper_class}, {ratio:.0%})": tampered,
        "Detected + Unrecoverable": overlay, "Recovered": rec.image,
    }


def qualitative_strip(out_stem: Path) -> None:
    """[original | watermarked | tampered | detected mask | recovered] for one image."""
    image_name, tamper_class, ratio, variant, block = "lena", "splice", 0.25, "A", 8
    saved = {
        "Original": IMAGES_DIR / f"{image_name}_original.png",
        "Watermarked": IMAGES_DIR / f"{image_name}_watermarked.png",
        f"Tampered ({tamper_class}, {ratio:.0%})": IMAGES_DIR / f"{image_name}_tampered_{tamper_class}.png",
        "Detected + Unrecoverable": IMAGES_DIR / f"{image_name}_mask_overlay_{tamper_class}.png",
        "Recovered": IMAGES_DIR / f"{image_name}_recovered_{tamper_class}.png",
    }
    if all(p.exists() for p in saved.values()):
        panels = {title: load_image(path) for title, path in saved.items()}
    else:
        panels = _run_pipeline_live(image_name, tamper_class, ratio, variant, block)

    fig, axes = plt.subplots(1, 5, figsize=(9.0, 2.1))
    for ax, (title, img) in zip(axes, panels.items()):
        ax.imshow(img)
        ax.set_title(title, fontsize=7.5)
        ax.axis("off")
    fig.tight_layout()
    _save(fig, out_stem)


if __name__ == "__main__":
    rows = load_runs_csv(DEFAULT_CSV) if DEFAULT_CSV.exists() else []
    print(f"plots.py: {len(rows)} rows found in {DEFAULT_CSV}")

    recovery_vs_ratio(rows, FIGURES_DIR / "recovery_vs_ratio")
    rho_vs_ratio(rows, FIGURES_DIR / "rho_vs_ratio")
    qualitative_strip(FIGURES_DIR / "qualitative_strip")

    for stem in ("recovery_vs_ratio", "rho_vs_ratio", "qualitative_strip"):
        for ext in (".png", ".pdf"):
            p = FIGURES_DIR / f"{stem}{ext}"
            assert p.exists() and p.stat().st_size > 1000, f"{p} missing or suspiciously small"
    print(f"plots.py: all 3 figures (PNG+PDF) written to {FIGURES_DIR}")
