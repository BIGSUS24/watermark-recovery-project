"""Deck-themed charts, rendered straight from output/runs.csv.

The figures in output/figures are styled for the IEEE paper (serif, greyscale-
safe). These are the same measurements restyled to match the slides, so the
deck never shows a chart that clashes with its own palette.
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
ASSETS = Path(__file__).resolve().parent / "assets"
RUNS = ROOT / "output" / "runs.csv"

INK, MID, DIM = "#0F172A", "#4B5A70", "#8A97A8"
CYAN, AMBER, EMER, ROSE = "#0891B2", "#F59E0B", "#109881", "#E11D48"
TEAL = "#7C3AED"
GRID = "#E3E9F1"

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Segoe UI", "DejaVu Sans"],
    "axes.edgecolor": GRID, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": MID, "ytick.color": MID,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.9,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def main_grid() -> pd.DataFrame:
    d = pd.read_csv(RUNS)
    return d[(d.condition == "tamper") & (d.block_size == 8)
             & (d.recovery_variant.isin(["A", "C"]))]


def _frame(ax):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.set_axisbelow(True)
    ax.tick_params(length=0, labelsize=11)


def rho_curve(g: pd.DataFrame, out: Path):
    a = g.groupby("tamper_ratio_nominal").recoverability_rate.agg(["mean", "std"])
    x = a.index.values
    fig, ax = plt.subplots(figsize=(6.5, 4.0), dpi=200)
    ax.fill_between(x, 1 - x, a["mean"], color=CYAN, alpha=0.13, zorder=1,
                    label="margin above the structural bound")
    ax.plot(x, 1 - x, "--", color=AMBER, lw=2.0, zorder=2,
            label=r"structural bound  1 $-$ $\alpha$")
    ax.errorbar(x, a["mean"], yerr=a["std"], fmt="o-", color=CYAN, lw=2.6,
                ms=7, mfc="white", mew=2.2, capsize=4, zorder=3,
                label=r"measured  $\rho$  (1,792 trials)")
    for xi, yi in zip(x, a["mean"]):
        ax.annotate(f"{yi:.3f}", (xi, yi), textcoords="offset points",
                    xytext=(0, 13), ha="center", fontsize=9.5, color=INK,
                    fontweight="bold")
    ax.set_xlabel("nominal tamper ratio  $\\alpha$", fontsize=12)
    ax.set_ylabel("recoverability  $\\rho$", fontsize=12)
    ax.set_xticks(x)
    ax.set_ylim(0.20, 1.06)
    ax.legend(frameon=False, fontsize=10.5, loc="upper right")
    _frame(ax)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def psnr_split(g: pd.DataFrame, out: Path):
    a = g[g.recovery_variant == "A"].groupby("tamper_ratio_nominal")[
        ["psnr_in_region", "psnr_whole_unmarked"]].mean()
    c = g[g.recovery_variant == "C"].groupby(
        "tamper_ratio_nominal").psnr_in_region.mean()
    x = a.index.values
    fig, ax = plt.subplots(figsize=(6.5, 4.0), dpi=200)
    ax.plot(x, c, "^-", color=TEAL, lw=2.6, ms=7, mfc="white", mew=2.2,
            label="in-region PSNR — Variant C (rate–distortion)")
    ax.plot(x, a.psnr_in_region, "o-", color=EMER, lw=2.8, ms=7, mfc="white",
            mew=2.2, label="in-region PSNR — Variant A (fixed DCT)")
    ax.plot(x, a.psnr_whole_unmarked, "s--", color=ROSE, lw=2.4, ms=6.5,
            mfc="white", mew=2.0, label="whole-image PSNR (unmarked convention)")
    ax.annotate(f"flat across every ratio\n"
                f"{a.psnr_in_region.min():.1f}–{a.psnr_in_region.max():.1f} dB (A),  "
                f"{c.min():.1f}–{c.max():.1f} dB (C)",
                xy=(x[4], a.psnr_in_region.iloc[4]), xytext=(x[1] - 0.02, 36.0),
                fontsize=10.5, color=EMER, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=EMER, lw=1.6))
    ax.annotate("falls with coverage,\nnot with descriptor fidelity",
                xy=(x[5], a.psnr_whole_unmarked.iloc[5]), xytext=(x[0] + 0.015, 11.6),
                fontsize=10.5, color=ROSE, fontweight="bold",
                arrowprops=dict(arrowstyle="->", color=ROSE, lw=1.6))
    ax.set_xlabel("nominal tamper ratio  $\\alpha$", fontsize=12)
    ax.set_ylabel("PSNR (dB)", fontsize=12)
    ax.set_xticks(x)
    ax.set_ylim(10, 40)
    ax.legend(frameon=False, fontsize=10.5, loc="lower center",
              bbox_to_anchor=(0.5, 1.01), ncol=1, handlelength=2.4)
    _frame(ax)
    fig.tight_layout()
    fig.savefig(out, bbox_inches="tight")
    plt.close(fig)


def build() -> dict:
    ASSETS.mkdir(exist_ok=True)
    g = main_grid()
    assert len(g) == 1792, f"expected the 1,792-row main grid, got {len(g)}"
    paths = {"rho": ASSETS / "rho_curve.png", "psnr": ASSETS / "psnr_split.png"}
    rho_curve(g, paths["rho"])
    psnr_split(g, paths["psnr"])
    return paths


def stats() -> dict:
    """Numbers the slides quote, read from the same grid the charts use."""
    d = pd.read_csv(RUNS)
    g = main_grid()
    b8 = d[d.block_size == 8]
    null = d[d.condition.isna()] if d.condition.isna().any() else d[d.condition == "null"]
    per_ratio = g.groupby("tamper_ratio_nominal")[
        ["recoverability_rate", "psnr_in_region", "psnr_whole_unmarked",
         "tamper_ratio_achieved"]].mean()
    return {
        "n_main": len(g), "n_total": len(d),
        "psnr_a": b8[b8.recovery_variant == "A"].wm_psnr.mean(),
        "psnr_c": b8[b8.recovery_variant == "C"].wm_psnr.mean(),
        "ssim_a": b8[b8.recovery_variant == "A"].wm_ssim.mean(),
        "ssim_c": b8[b8.recovery_variant == "C"].wm_ssim.mean(),
        "ssim_min": b8.wm_ssim.min(),
        "blk_prec": g.block_precision.mean(), "blk_rec": g.block_recall.mean(),
        "px_prec": g.px_precision.mean(),
        "inpaint_recall": g[g.tamper_class == "inpaint_removal"].block_recall.mean(),
        "in_region_mean": g.psnr_in_region.mean(),
        "n_null_blocks": int(null.n_blocks_total.sum()) if len(null) else 0,
        "n_fp": int(null.n_false_positive_blocks.sum()) if len(null) else 0,
        "per_ratio": per_ratio,
    }


if __name__ == "__main__":
    p = build()
    s = stats()
    print({k: str(v) for k, v in p.items()})
    print({k: v for k, v in s.items() if k != "per_ratio"})
    print(s["per_ratio"].round(4))
