"""Figures and per-image numbers for the ICIP short paper.

The conference paper uses an author-supplied 512x512 photograph as its worked
example instead of the USC-SIPI standard plate used in the long paper, so this
script runs the full pipeline on that one image and writes:

  paper/icip/photo_512.png          the prepared sample (centre-cropped, Lanczos)
  paper/icip/photo_results.json     every number the paper quotes for this image
  output/figures/icip_qualitative.{png,pdf}
  output/figures/icip_rho.{png,pdf}

Nothing in src/ is modified; this only calls it.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from detect import detect_image, expand_mask            # noqa: E402
from embed import embed_image                           # noqa: E402
from metrics import (confusion_counts, imperceptibility,  # noqa: E402
                     loc_scores, recovery_metrics)
from payload import default_image_id                    # noqa: E402
from recover import recover_image                       # noqa: E402
from run_experiments import SEED_BASE_DEFAULT, make_key  # noqa: E402
from tamper import apply_tamper, block_mask_from_pixel_mask  # noqa: E402

HERE = Path(__file__).resolve().parent
FIGS = ROOT / "output" / "figures"
SRC_PHOTO = Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "photo_src.jpeg"
NAME = "author_photo"
BLOCK, RATIOS = 8, (0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70)
CLASSES = ("splice", "inpaint_removal", "crop_refill", "noise")
LABELS = {"splice": "Copy-paste splicing", "inpaint_removal": "Object removal",
          "crop_refill": "Crop-and-refill", "noise": "Noise corruption"}
STYLE = {"splice": ("-", "o"), "inpaint_removal": ("--", "s"),
         "crop_refill": ("-.", "^"), "noise": (":", "D")}

plt.rcParams.update({"font.family": "serif", "font.size": 8.5, "axes.titlesize": 9,
                     "axes.labelsize": 8.5, "legend.fontsize": 7,
                     "xtick.labelsize": 8, "ytick.labelsize": 8})


def prepare(path: Path, out: Path, size: int = 512) -> np.ndarray:
    """Centre-crop to square and resample to 512x512, then store losslessly.

    The sample arrives as a phone JPEG; the scheme is fully fragile, so the
    sample must be fixed in a lossless container BEFORE embedding -- the paper's
    input is this PNG, not the JPEG it came from.
    """
    im = Image.open(path).convert("RGB")
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))
    im = im.resize((size, size), Image.LANCZOS)
    im.save(out)
    return np.asarray(im, dtype=np.uint8)


def overlay(base, pred_px, unrec_px):
    """Predicted tamper in red at 50% alpha, unrecoverable blocks in cyan."""
    out = base.astype(np.float64)
    pred_only = pred_px & ~unrec_px
    out[pred_only] = out[pred_only] * 0.5 + np.array([255.0, 0.0, 0.0]) * 0.5
    out[unrec_px] = out[unrec_px] * 0.5 + np.array([0.0, 255.0, 255.0]) * 0.5
    return np.clip(out, 0, 255).astype(np.uint8)


def trial(raw, wm, key, iid, tamper_class, ratio, variant):
    t = apply_tamper(wm, tamper_class, ratio, NAME, SEED_BASE_DEFAULT)
    tampered, gt_px = t["tampered_image"], t["gt_mask_px"]
    det = detect_image(tampered, key, iid, block=BLOCK, variant=variant)
    rec = recover_image(tampered, det, block=BLOCK, variant=variant)
    gt_blk = block_mask_from_pixel_mask(gt_px, BLOCK)
    blk = loc_scores(*confusion_counts(det.block_mask, gt_blk))
    px = loc_scores(*confusion_counts(det.pixel_mask, gt_px))
    unrec_px = expand_mask(rec.unrecoverable_mask, BLOCK).astype(bool)
    rm = recovery_metrics(raw, rec.image, gt_px.astype(bool), unrec_px)
    row = {"tamper_class": tamper_class, "ratio_nominal": ratio,
           "ratio_achieved": t["achieved_ratio"], "variant": variant,
           "block_precision": blk["precision"], "block_recall": blk["recall"],
           "px_precision": px["precision"], "px_recall": px["recall"],
           "rho": rec.rho, "psnr_in_region": rm["psnr_in_region"],
           "ssim_in_region": rm["ssim_in_region"],
           "n_tampered_blocks": rec.counts["tampered"],
           "n_unrecoverable_blocks": rec.counts["unrecoverable"]}
    panels = {"Original": raw, "Watermarked": wm,
              f"Tampered ({ratio:.0%})": tampered,
              "Detected / unrecoverable": overlay(tampered, det.pixel_mask.astype(bool), unrec_px),
              "Recovered": rec.image}
    return row, panels


def rho_figure(out_stem: Path) -> None:
    """Measured rho against its structural bound 1-alpha, on the 32-image main grid."""
    import csv
    rows = [r for r in csv.DictReader(open(ROOT / "output" / "runs.csv", encoding="utf-8"))
            if r["condition"] == "tamper" and r["recovery_variant"] == "A"
            and r["block_size"] == "8"]
    fig, ax = plt.subplots(figsize=(3.4, 2.45))
    for cls in CLASSES:
        xs, ys = [], []
        for a in RATIOS:
            vals = [float(r["recoverability_rate"]) for r in rows
                    if r["tamper_class"] == cls and abs(float(r["tamper_ratio_nominal"]) - a) < 1e-9]
            if vals:
                xs.append(a)
                ys.append(sum(vals) / len(vals))
        ls, mk = STYLE[cls]
        ax.plot(xs, ys, ls=ls, marker=mk, ms=3.2, lw=1.1, label=LABELS[cls])
    ax.plot(RATIOS, [1 - a for a in RATIOS], ls=(0, (1, 1)), color="0.35", lw=1.0,
            label=r"structural bound $1-\alpha$")
    ax.set_xlabel(r"tamper ratio $\alpha$")
    ax.set_ylabel(r"recoverability rate $\rho$")
    ax.set_xlim(0.05, 0.75)
    ax.set_ylim(0.25, 1.0)
    ax.grid(alpha=0.3, lw=0.5)
    ax.legend(loc="upper right", frameon=False)
    save(fig, out_stem)


def save(fig, stem: Path) -> None:
    stem.parent.mkdir(parents=True, exist_ok=True)
    for ext in (".png", ".pdf"):
        fig.savefig(stem.with_suffix(ext), dpi=300, bbox_inches="tight")
    plt.close(fig)
    print("wrote", stem.with_suffix(".png"))


def main() -> None:
    raw = prepare(SRC_PHOTO, HERE / "photo_512.png")
    key = make_key(0)
    iid = default_image_id(NAME, raw.shape, BLOCK)
    out = {"image": NAME, "shape": list(raw.shape), "block": BLOCK, "imperceptibility": {}}

    wm = {}
    for variant in ("A", "C"):
        w, _ = embed_image(raw, key, iid, block=BLOCK, variant=variant)
        wm[variant] = w
        out["imperceptibility"][variant] = imperceptibility(raw, w)

    rows, strip = [], None
    for variant in ("A", "C"):
        for cls in CLASSES:
            for a in RATIOS:
                row, panels = trial(raw, wm[variant], key, iid, cls, a, variant)
                rows.append(row)
                if variant == "A" and cls == "splice" and abs(a - 0.30) < 1e-9:
                    strip = panels
    out["trials"] = rows
    (HERE / "photo_results.json").write_text(json.dumps(out, indent=1), encoding="utf-8")

    fig, axes = plt.subplots(1, 5, figsize=(7.0, 1.62))
    for ax, (title, img) in zip(axes, strip.items()):
        ax.imshow(img)
        ax.set_title(title, fontsize=6.5, pad=2.5)
        ax.axis("off")
    fig.tight_layout(pad=0.25)
    save(fig, FIGS / "icip_qualitative")

    rho_figure(FIGS / "icip_rho")

    a = out["imperceptibility"]["A"]
    assert a["psnr"] > 40, a
    print(f"watermarked PSNR A {a['psnr']:.3f} dB  SSIM {a['ssim']:.5f}")
    print(f"{len(rows)} trials on {NAME}")


if __name__ == "__main__":
    main()
