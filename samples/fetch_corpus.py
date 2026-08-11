"""Fetches, standardizes, and hash-pins the two standard image corpora this
project evaluates on: USC-SIPI misc (8 colour, 512x512) and Kodak-PCD0992
(24 colour, 512x768 -- a few frames are stored transposed, 768x512).

THE USC-SIPI PROBLEM: USC's own misc-volume page states they no longer
distribute two of the eight required images -- "we no longer distribute the
following images that were previously available in our database: 4.2.04
(lena), 4.2.02 (tiffany) ... Although these images have played a significant
role in the history of image processing, they no longer represent the best
examples for future research." Confirmed live: sipi.usc.edu/database/
download.php?vol=misc&img=4.2.04 (lena) and img=4.2.02 (tiffany) both return
HTTP 200 with an HTML notice page, not a TIFF -- a 200 status does NOT mean
the image was served, which is why every fetch here is verified by actually
decoding the bytes as an image, not by HTTP status alone. Since the official
archive cannot supply a byte-identical 8-image set, this module fetches from
a mirror instead (see LICENSING below for the citation this implies).

SOURCES (tried in order per file; first success wins):
  1. github.com/girfa/ColorImageDatasets -- raw URLs are NOT constructed by
     hand. The GitHub Contents API is queried at runtime and its
     `download_url` field is used verbatim, because the repo's default
     branch and exact filenames are not something to guess.
  2. Per-file official mirrors: sipi.usc.edu/database/download.php?vol=misc
     &img=<id> for USC (known incomplete: lena/tiffany, see above), and
     r0k.us/graphics/kodak/kodak/kodim<NN>.png for Kodak. NOTE: the obvious
     r0k.us/graphics/kodak/kodim<NN>.png (single "kodak" segment) 404s --
     the site's own per-image HTML pages link to an image at a path one
     level deeper than the page itself, discovered by fetching
     r0k.us/graphics/kodak/kodim01.html and reading its <img src>.
  3. If a file has no successful source: print every missing filename with
     its expected dimensions and exit non-zero. This project never silently
     runs on a partial corpus.

LICENSING (verbatim -- lift this straight into the paper):
  the USC-SIPI and Kodak-PCD0992 sets as redistributed by the AuSR reference
  authors (github.com/girfa/ColorImageDatasets); original sources USC-SIPI
  (sipi.usc.edu) and Eastman Kodak (mirrored at r0k.us/graphics/kodak)

SCOPE: UCID (1,338 images) lives in the same upstream repo but is
deliberately NOT fetched here -- it is not part of this project's 32-image
evaluation grid and would multiply runtime for zero required deliverable.
Do not add it without a reason that isn't already covered by USC-SIPI/Kodak.

SYNTHETIC GUARANTEE: --synthetic-fallback writes procedurally generated
placeholder images (no network) so downstream modules can be developed
offline. Every such row is written to the manifest with dataset="synthetic",
so `[r for r in rows if r["dataset"] != "synthetic"]` is the one-line filter
that keeps placeholders out of any paper-facing table -- this project makes
no claim these placeholders are, or resemble, real photographs.

MANIFEST MODEL: trust-on-first-fetch, then pin-and-verify. The first
successful run hashes the STANDARDIZED PNG (never the original download --
the PNG is what every other module reads) and pins that SHA-256 into
manifest.csv. Every later run re-hashes the local file and compares against
the pinned value; a mismatch is a hard SystemExit, not a warning, because a
mirror silently changing bytes underneath a "reproducible" experiment is
exactly what a manifest exists to catch.
"""

import argparse
import csv
import datetime
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import cv2
import numpy as np

SAMPLES_DIR = Path(__file__).resolve().parent
USC_DIR = SAMPLES_DIR / "usc_sipi"
KODAK_DIR = SAMPLES_DIR / "kodak"
SYNTH_DIR = SAMPLES_DIR / "synthetic"
MANIFEST_PATH = SAMPLES_DIR / "manifest.csv"
MANIFEST_FIELDS = ["dataset", "filename", "relpath", "width", "height",
                    "channels", "sha256", "source_url", "fetched_utc"]
DATASET_ORDER = {"usc_sipi": 0, "kodak": 1, "synthetic": 2}

GH_API_USC = "https://api.github.com/repos/girfa/ColorImageDatasets/contents/USC-SIPI"
GH_API_KODAK = "https://api.github.com/repos/girfa/ColorImageDatasets/contents/Kodak-PCD0992"

# The 8 filenames actually present in girfa/ColorImageDatasets/USC-SIPI,
# discovered via the Contents API (not guessed) -- kept as a fixed roster so
# a future extra file in that repo doesn't silently get pulled into "the 8".
# Mapped to the standard test-image identity the literature reports; also
# gives the SIPI-native img id used by fallback tier 2 (see module docstring
# for why lena/tiffany's ids 200-OK with an HTML body instead of a TIFF).
USC_SIPI_FILES = {
    "airplane.tif": ("Airplane/F-16", "4.2.05"),
    "baboon.tif":   ("Baboon/Mandrill", "4.2.03"),
    "house.tif":    ("House", "house"),
    "lena.tif":     ("Lena", "4.2.04"),      # USC no longer serves this id
    "pepper.tif":   ("Peppers", "4.2.07"),
    "sailboat.tif": ("Sailboat/Boat", "4.2.06"),
    "splash.tif":   ("Splash", "4.2.01"),
    "tiffany.tif":  ("Tiffany", "4.2.02"),   # USC no longer serves this id
}
SIPI_DOWNLOAD_URL = "https://sipi.usc.edu/database/download.php?vol=misc&img={img_id}"
KODAK_MIRROR_URL = "https://r0k.us/graphics/kodak/kodak/kodim{n:02d}.png"

EXPECTED_DIMS = {
    "usc_sipi": "512x512x3",
    "kodak": "512x768x3 (a few Kodak frames are stored transposed, 768x512x3)",
}


# --------------------------------------------------------------------------
# Standardization
# --------------------------------------------------------------------------

def standardize_to_png(src_path: Path, dst_path: Path) -> tuple[int, int, int]:
    """Read via cv2.imread(..., cv2.IMREAD_UNCHANGED), write lossless PNG; return (w, h, channels)."""
    img = cv2.imread(str(src_path), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ValueError(f"could not decode as an image: {src_path}")
    # Load-bearing: OpenCV's TIFF reader can silently promote to 16-bit,
    # which would corrupt every LSB assumption downstream in this project.
    assert img.dtype == np.uint8, (
        f"{src_path} decoded as dtype {img.dtype}, not uint8 -- refusing to "
        "standardize a silently-promoted (e.g. 16-bit TIFF) source")
    if img.ndim == 3 and img.shape[2] == 4:
        img = img[:, :, :3]  # drop alpha
    channels = 1 if img.ndim == 2 else img.shape[2]
    if channels not in (1, 3):
        raise ValueError(f"unsupported channel count {channels} in {src_path}")
    h, w = img.shape[:2]
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(dst_path), img)
    if not ok:
        raise ValueError(f"cv2.imwrite failed: {dst_path}")
    return w, h, channels


# --------------------------------------------------------------------------
# Network
# --------------------------------------------------------------------------

def _http_get(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "fetch_corpus.py"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _gh_list(api_url: str) -> dict[str, str]:
    """{filename: download_url} from a GitHub contents API listing; {} on any failure."""
    try:
        data = json.loads(_http_get(api_url).decode("utf-8"))
        return {e["name"]: e["download_url"] for e in data if e.get("type") == "file"}
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError) as e:
        print(f"  [warn] GitHub listing failed for {api_url}: {e}", file=sys.stderr)
        return {}


def _fetch_one(dst_png: Path, candidates: list[str | None]
                ) -> tuple[str, int, int, int] | None:
    """Try each candidate URL in order; return (used_url, w, h, channels) on first success.

    A download is only trusted once the bytes are actually decoded as an
    image (see module docstring: USC's own removed ids return HTTP 200 with
    an HTML body). Downloads to a `.tmp` file and renames only after the
    standardized PNG is fully written and hashed, so a run killed mid-
    transfer never leaves a corrupt file sitting at the final path.
    """
    for url in candidates:
        if not url:
            continue
        raw_tmp = dst_png.with_name(dst_png.stem + "__raw.tmp")
        # cv2.imwrite picks its encoder from the extension, so the tmp file
        # must still END in .png -- "foo.png.tmp" has no recognized
        # extension and imwrite fails with "could not find a writer".
        png_tmp = dst_png.with_name(dst_png.stem + ".tmp" + dst_png.suffix)
        try:
            raw_tmp.parent.mkdir(parents=True, exist_ok=True)
            raw_tmp.write_bytes(_http_get(url))
            w, h, ch = standardize_to_png(raw_tmp, png_tmp)
        except Exception as e:
            print(f"  [warn] source failed ({url}): {e}", file=sys.stderr)
            png_tmp.unlink(missing_ok=True)
            continue
        finally:
            raw_tmp.unlink(missing_ok=True)
        png_tmp.replace(dst_png)  # atomic: dst_png only ever holds a complete file
        return url, w, h, ch
    return None


# --------------------------------------------------------------------------
# Manifest
# --------------------------------------------------------------------------

def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _now_iso() -> str:
    return datetime.datetime.now(datetime.UTC).isoformat()


def _read_manifest() -> list[dict]:
    if not MANIFEST_PATH.exists():
        return []
    with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_manifest_if_changed(rows: list[dict]) -> None:
    """Idempotent write: leaves manifest.csv byte-identical when content is unchanged."""
    import io
    rows_sorted = sorted(rows, key=lambda r: (DATASET_ORDER.get(r["dataset"], 99), r["filename"]))
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=MANIFEST_FIELDS)
    w.writeheader()
    for r in rows_sorted:
        w.writerow({k: r[k] for k in MANIFEST_FIELDS})
    new_content = buf.getvalue()
    if MANIFEST_PATH.exists():
        with open(MANIFEST_PATH, newline="", encoding="utf-8") as f:
            if f.read() == new_content:
                return  # nothing changed -- do not touch the file
    with open(MANIFEST_PATH, "w", newline="", encoding="utf-8") as f:
        f.write(new_content)


def _row_for_existing_file(dataset: str, filename: str, dst_path: Path,
                            prior: dict | None) -> dict:
    """Re-hash a file already on disk; hard-fail if it disagrees with a pinned manifest row."""
    relpath = dst_path.relative_to(SAMPLES_DIR).as_posix()
    local_hash = _sha256(dst_path)
    if prior is not None and prior["sha256"] != local_hash:
        raise SystemExit(
            f"HASH MISMATCH for {relpath}: manifest pins {prior['sha256']}, local file "
            f"now hashes to {local_hash}. Refusing to proceed -- either the local file was "
            "modified or a mirror changed bytes underneath a pinned corpus.")
    img = cv2.imread(str(dst_path), cv2.IMREAD_UNCHANGED)
    h, w = img.shape[:2]
    ch = 1 if img.ndim == 2 else img.shape[2]
    return {
        "dataset": dataset, "filename": filename, "relpath": relpath,
        "width": w, "height": h, "channels": ch, "sha256": local_hash,
        "source_url": prior["source_url"] if prior else "preexisting-local-file",
        "fetched_utc": prior["fetched_utc"] if prior else _now_iso(),
    }


def _row_for_fetch(dataset: str, filename: str, dst_path: Path,
                    candidates: list[str | None], prior: dict | None) -> dict | None:
    """Fetch+standardize via the fallback chain; hard-fail on a hash disagreeing with manifest."""
    result = _fetch_one(dst_path, candidates)
    if result is None:
        return None
    used_url, w, h, ch = result
    relpath = dst_path.relative_to(SAMPLES_DIR).as_posix()
    new_hash = _sha256(dst_path)
    if prior is not None and prior["sha256"] != new_hash:
        raise SystemExit(
            f"HASH MISMATCH for {relpath} after re-fetch: manifest pinned {prior['sha256']}, "
            f"freshly downloaded file hashes to {new_hash}. Refusing to silently accept a "
            "corpus that differs from the one already pinned.")
    return {
        "dataset": dataset, "filename": filename, "relpath": relpath,
        "width": w, "height": h, "channels": ch, "sha256": new_hash,
        "source_url": used_url, "fetched_utc": _now_iso(),
    }


# --------------------------------------------------------------------------
# Synthetic placeholders
# --------------------------------------------------------------------------

def _make_synthetic(h: int, w: int, seed: int) -> np.ndarray:
    """Structured gradient + seeded texture, distinct per channel; deterministic uint8 (h, w, 3)."""
    y, x = np.mgrid[0:h, 0:w].astype(np.float64)
    rng = np.random.default_rng(seed)
    chans = []
    for c, phase in enumerate((0.0, 2.1, 4.2)):
        base = (0.4 * x + 0.4 * y
                + 35.0 * np.sin(x / 7.0 + phase) * np.cos(y / 11.0 + phase) + 110.0)
        noise = rng.normal(0.0, 12.0, size=(h, w))
        chans.append(np.clip(base + noise, 0, 255))
    return np.stack(chans, axis=-1).astype(np.uint8)


def run_synthetic_fallback() -> list[dict]:
    SYNTH_DIR.mkdir(parents=True, exist_ok=True)
    existing = {r["relpath"]: r for r in _read_manifest()}
    specs = [("synth_512x512.png", 512, 512, 0), ("synth_512x768.png", 512, 768, 1)]
    processed = []
    for fname, h, w, seed in specs:
        dst = SYNTH_DIR / fname
        relpath = dst.relative_to(SAMPLES_DIR).as_posix()
        prior = existing.get(relpath)
        need_write = not dst.exists() or (prior is None) or _sha256(dst) != prior["sha256"]
        if not dst.exists():
            img = _make_synthetic(h, w, seed)
            tmp = dst.with_name(dst.stem + ".tmp" + dst.suffix)
            ok = cv2.imwrite(str(tmp), cv2.cvtColor(img, cv2.COLOR_RGB2BGR))
            assert ok and img.dtype == np.uint8
            tmp.replace(dst)
        row = _row_for_existing_file("synthetic", fname, dst, prior)
        processed.append(row)

    all_rows = _read_manifest()
    others = [r for r in all_rows if r["relpath"] not in {p["relpath"] for p in processed}]
    _write_manifest_if_changed(processed + others)
    return processed


# --------------------------------------------------------------------------
# Real corpus fetch
# --------------------------------------------------------------------------

def run_fetch_real() -> list[dict]:
    print("Listing girfa/ColorImageDatasets via the GitHub Contents API...")
    gh_usc = _gh_list(GH_API_USC)
    gh_kodak = _gh_list(GH_API_KODAK)

    targets = []  # (dataset, filename, dst_path, candidates)
    for fname, (_label, img_id) in USC_SIPI_FILES.items():
        dst = USC_DIR / (Path(fname).stem + ".png")
        candidates = [gh_usc.get(fname), SIPI_DOWNLOAD_URL.format(img_id=img_id)]
        targets.append(("usc_sipi", fname, dst, candidates))
    for n in range(1, 25):
        fname = f"kodim{n:02d}.png"
        dst = KODAK_DIR / fname
        candidates = [gh_kodak.get(fname), KODAK_MIRROR_URL.format(n=n)]
        targets.append(("kodak", fname, dst, candidates))

    existing = {r["relpath"]: r for r in _read_manifest()}
    processed, missing = [], []
    for dataset, filename, dst, candidates in targets:
        relpath = dst.relative_to(SAMPLES_DIR).as_posix()
        prior = existing.get(relpath)
        if dst.exists():
            processed.append(_row_for_existing_file(dataset, filename, dst, prior))
            print(f"  [skip, hash OK] {relpath}")
            continue
        row = _row_for_fetch(dataset, filename, dst, candidates, prior)
        if row is None:
            missing.append((dataset, filename))
        else:
            processed.append(row)
            print(f"  [fetched] {relpath}  <-  {row['source_url']}")

    if missing:
        print("\nFAILED to obtain the following files from every source in the fallback chain:",
              file=sys.stderr)
        for dataset, filename in missing:
            print(f"  {dataset}/{filename}  (expected {EXPECTED_DIMS[dataset]})", file=sys.stderr)
        print("\nRefusing to proceed with a partial corpus. Try --synthetic-fallback for "
              "offline development, or re-run once network/mirrors are available.",
              file=sys.stderr)
        sys.exit(1)

    all_rows = _read_manifest()
    target_relpaths = {t[2].relative_to(SAMPLES_DIR).as_posix() for t in targets}
    others = [r for r in all_rows if r["relpath"] not in target_relpaths]
    _write_manifest_if_changed(processed + others)

    usc_n = sum(1 for r in processed if r["dataset"] == "usc_sipi")
    kodak_n = sum(1 for r in processed if r["dataset"] == "kodak")
    assert usc_n == 8, f"expected 8 USC-SIPI rows, got {usc_n}"
    assert kodak_n == 24, f"expected 24 Kodak rows, got {kodak_n}"
    return processed


def run_verify_only() -> None:
    rows = _read_manifest()
    if not rows:
        print("manifest.csv not found or empty -- nothing to verify.")
        return
    failures = []
    for r in rows:
        path = SAMPLES_DIR / r["relpath"]
        if not path.exists():
            failures.append(f"{r['relpath']}: MISSING on disk (manifest expects it)")
            continue
        h = _sha256(path)
        if h != r["sha256"]:
            failures.append(f"{r['relpath']}: HASH MISMATCH (manifest {r['sha256']}, now {h})")
    print(f"Verified {len(rows)} manifest rows, {len(failures)} failure(s).")
    if failures:
        for f in failures:
            print(f"  {f}", file=sys.stderr)
        raise SystemExit(1)
    print("All local files match their pinned manifest hashes.")


def _print_summary(rows: list[dict]) -> None:
    print(f"\n{'dataset':<10} {'filename':<18} {'w':>5} {'h':>5} {'ch':>3}")
    for r in sorted(rows, key=lambda r: (DATASET_ORDER.get(r["dataset"], 99), r["filename"])):
        print(f"{r['dataset']:<10} {r['filename']:<18} {r['width']:>5} {r['height']:>5} {r['channels']:>3}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--synthetic-fallback", action="store_true",
                         help="generate offline placeholder images instead of fetching")
    parser.add_argument("--verify-only", action="store_true",
                         help="re-hash existing local files against manifest.csv; no network")
    args = parser.parse_args()

    if args.verify_only:
        run_verify_only()
    elif args.synthetic_fallback:
        rows = run_synthetic_fallback()
        _print_summary(rows)
    else:
        rows = run_fetch_real()
        _print_summary(rows)
        print("\nfetch_corpus.py: OK")
