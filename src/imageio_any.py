"""Decode-side format adapter: turns whatever a user actually has into uint8 RGB.

embed_image (see embed.py) only accepts (H, W) or (H, W, 3) uint8 -- it hard-rejects
RGBA and knows nothing about JPEG/PDF/WebP/etc. This module is the layer in front of
it: sniff the real format from magic bytes, decode with Pillow (or pypdfium2 for PDF),
composite any alpha over white, and normalise every path to (H, W, 3) uint8 RGB in
the same channel order embed.py/load_image already use. Output is always PNG
elsewhere in the pipeline -- this module is decode-only.

No internal dependencies -- only numpy, Pillow, stdlib, and (lazily, PDF-only)
pypdfium2. Every other module in this project keeps to the RGB-at-the-boundary
convention (see embed.py's load_image/save_image); this module is where that
boundary actually gets crossed for non-PNG input.
"""

import io
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

# We do our own MAX_PIXELS check (below) with our own message and exception type,
# so Pillow's built-in decompression-bomb warning/exception is disabled rather than
# left to fire first with a different message.
Image.MAX_IMAGE_PIXELS = None

LOSSLESS = frozenset({"png", "bmp", "tiff"})  # formats whose 2 LSB planes survive a save
MAX_PIXELS = 40_000_000  # decompression-bomb guard, per page
MAX_PAGES = 20           # PDF page cap

# Pillow modes that store raw 16-bit (or wider) integer samples. convert("L") on
# these CLIPS at 255 instead of scaling -- confirmed empirically -- so they need
# their own >>8 path rather than a generic .convert() call.
_WIDE_INT_MODES = {"I", "I;16", "I;16B", "I;16L", "I;16N"}

_LOSSY_NOTE = {
    "jpeg": "JPEG re-encodes pixels lossily; a fragile 2-LSB watermark will not survive it.",
    # ponytail: WebP can be lossy or lossless, but the two are indistinguishable from
    # the leading magic bytes alone (both start RIFF....WEBP); we conservatively call
    # every WebP lossy. Upgrade path: parse the VP8/VP8L/VP8X chunk id that follows.
    "webp": "WebP is assumed lossy here (lossless WebP cannot be told apart by magic "
            "bytes alone); a fragile 2-LSB watermark may not survive it.",
    "gif": "GIF quantizes to a 256-colour palette; the original full-colour pixel "
           "values are already gone by the time this module sees them.",
}


class Page(NamedTuple):
    """One decoded page/image, always normalised to plain uint8 RGB.

    ponytail: a NamedTuple, matching detect.py's DetectResult / recover.py's
    RecoverResult -- zero boilerplate for pure data with no attached behaviour.
    """
    name: str            # e.g. "notice.pdf p3" or just the filename stem
    rgb: np.ndarray      # (H, W, 3) uint8, RGB order, NEVER RGBA, never greyscale-2D
    fmt: str             # sniffed format: "png"/"jpeg"/"bmp"/"tiff"/"webp"/"gif"/"pdf"
    lossy: bool          # True if this pixel data cannot carry a fragile watermark reliably
    page: int | None     # 1-based page number for PDFs, else None
    note: str            # "" or a short human-readable caveat, e.g. why it is lossy


def sniff(data: bytes) -> str:
    """Identify format from MAGIC BYTES only -- never the filename. "unknown" if none match."""
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if data.startswith(b"BM"):
        return "bmp"
    if data.startswith(b"II*\x00") or data.startswith(b"MM\x00*"):
        return "tiff"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "gif"
    if data.startswith(b"%PDF"):
        return "pdf"
    return "unknown"


def _to_rgb_white(img: Image.Image) -> tuple[np.ndarray, str]:
    """Normalise one Pillow image to (H, W, 3) uint8 RGB; alpha composited over white."""
    if img.mode in _WIDE_INT_MODES:
        # Scale down, don't clip: 16-bit-per-channel >> 8, per channel. These modes are
        # always single-channel in Pillow, hence the explicit replicate-to-3 below.
        gray8 = (np.array(img).astype(np.uint32) >> 8).astype(np.uint8)
        rgb = np.stack([gray8] * 3, axis=-1)
        return np.ascontiguousarray(rgb), ""

    has_alpha = img.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
        img.mode == "P" and "transparency" in img.info)
    note = ""
    if has_alpha:
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[-1])  # alpha band composites onto white
        img = bg
        note = "transparent pixels composited over white"
    elif img.mode != "RGB":
        img = img.convert("RGB")  # greyscale replicates to 3 channels; palette/CMYK converts

    return np.ascontiguousarray(np.array(img, dtype=np.uint8)), note


def _check_pixels(w: int, h: int, what: str) -> None:
    mp = w * h / 1_000_000
    if w * h > MAX_PIXELS:
        raise ValueError(
            f"{what} is {mp:.1f} megapixels ({w}x{h}), exceeds the {MAX_PIXELS / 1e6:.0f} "
            "MP-per-page decompression-bomb guard")


def _decode_raster(data: bytes, filename: str, fmt: str) -> Page:
    try:
        img = Image.open(io.BytesIO(data))
        _check_pixels(*img.size, what=f"{fmt} image")
        rgb, alpha_note = _to_rgb_white(img)
    except ValueError:
        raise
    except Exception as exc:  # Pillow raises OSError/SyntaxError/etc. on bad data
        raise ValueError(f"could not decode {fmt} data: {exc}") from exc

    lossy = fmt in _LOSSY_NOTE
    note = _LOSSY_NOTE.get(fmt, "")
    if alpha_note:
        note = f"{note} {alpha_note}".strip() if note else alpha_note

    name = Path(filename).stem if filename else fmt
    return Page(name=name, rgb=rgb, fmt=fmt, lossy=lossy, page=None, note=note)


def _decode_pdf(data: bytes, filename: str, dpi: int) -> list[Page]:
    try:
        import pypdfium2 as pdfium  # lazy: the rest of this module works without it
    except ImportError as exc:
        raise ValueError(
            "PDF input requires pypdfium2, which is not installed. Run: "
            "pip install pypdfium2"
        ) from exc

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as exc:
        raise ValueError(f"could not open PDF: {exc}") from exc

    try:
        n_pages = len(doc)
        if n_pages == 0:
            raise ValueError("PDF has no pages")
        n_decode = min(n_pages, MAX_PAGES)
        scale = dpi / 72.0  # PDF geometry is in 1/72" points
        base = filename if filename else "pdf"

        pages = []
        for i in range(n_decode):
            page = doc.get_page(i)
            try:
                w_pt, h_pt = page.get_size()
                _check_pixels(int(w_pt * scale), int(h_pt * scale), what=f"PDF page {i + 1}")
                # ponytail: first frame/layer only, same as the raster formats below --
                # PDF has no animation concept so there is nothing more to take here.
                pil_img = page.render(scale=scale).to_pil()
            except ValueError:
                raise
            except Exception as exc:  # a valid header can still hide a corrupt page stream
                raise ValueError(f"could not rasterise PDF page {i + 1}: {exc}") from exc
            finally:
                page.close()
            rgb, _ = _to_rgb_white(pil_img)  # PDF renders straight to RGB; call is defensive

            note = f"rasterised from PDF at {dpi} DPI; not the original vector content"
            if n_pages > MAX_PAGES and i == n_decode - 1:
                note += f"; document has {n_pages} pages, only the first {MAX_PAGES} were decoded"
            pages.append(Page(name=f"{base} p{i + 1}", rgb=rgb, fmt="pdf", lossy=True,
                              page=i + 1, note=note))
        return pages
    finally:
        doc.close()


def decode(data: bytes, filename: str = "", dpi: int = 200) -> list[Page]:
    """Decode any supported format to a list of Page (one page unless PDF)."""
    fmt = sniff(data)
    if fmt == "unknown":
        raise ValueError(
            f"unrecognised file format: first bytes {data[:8]!r} match none of "
            "png/jpeg/bmp/tiff/webp/gif/pdf magic numbers")
    if fmt == "pdf":
        return _decode_pdf(data, filename, dpi)
    return [_decode_raster(data, filename, fmt)]


# --------------------------------------------------------------------------
# Self-check -- synthesises every fixture in memory, no files on disk.
# --------------------------------------------------------------------------

def _save(img: Image.Image, fmt: str) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


if __name__ == "__main__":
    # 1. sniff from magic bytes alone, for every format, regardless of filename.
    samples = {
        "png": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "PNG"),
        "jpeg": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "JPEG"),
        "bmp": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "BMP"),
        "tiff": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "TIFF"),
        "webp": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "WEBP"),
        "gif": _save(Image.new("RGB", (4, 4), (1, 2, 3)), "GIF"),
        "pdf": b"%PDF-1.7\n%fake but magic bytes are real\n",
    }
    for fmt, data in samples.items():
        assert sniff(data) == fmt, (fmt, sniff(data))
    assert sniff(b"not an image at all") == "unknown"

    # 2. a .png-named JPEG still sniffs (and decodes) as jpeg -- filename is never trusted.
    jpeg_bytes = samples["jpeg"]
    assert sniff(jpeg_bytes) == "jpeg"
    pages = decode(jpeg_bytes, filename="photo.png")
    assert len(pages) == 1 and pages[0].fmt == "jpeg" and pages[0].lossy

    # 3. RGBA composites over white, proven by a NON-white colour under the hole.
    rgba = Image.new("RGBA", (10, 10), (0, 200, 0, 255))       # opaque green everywhere
    hole = np.array(rgba)
    hole[2:6, 2:6] = (0, 0, 200, 0)                            # blue, but FULLY transparent
    rgba = Image.fromarray(hole, mode="RGBA")
    png_rgba = _save(rgba, "PNG")
    p = decode(png_rgba)[0]
    assert p.rgb.shape == (10, 10, 3)
    assert tuple(p.rgb[3, 3]) == (255, 255, 255), p.rgb[3, 3]  # hole -> white, not blue
    assert tuple(p.rgb[0, 0]) == (0, 200, 0)                   # opaque area untouched
    assert "composited" in p.note

    # 3b. palette PNG with a transparent index also composites (not just RGBA does).
    pal = Image.new("P", (6, 6))
    pal.putpalette([255, 0, 0, 10, 20, 200] + [0] * (768 - 6))
    pal.putdata([0] * 36)  # every pixel = palette index 0 = red
    pal_bytes = io.BytesIO()
    pal.save(pal_bytes, format="PNG", transparency=0)  # index 0 (red) is transparent
    p = decode(pal_bytes.getvalue())[0]
    assert tuple(p.rgb[0, 0]) == (255, 255, 255), p.rgb[0, 0]  # transparent red -> white

    # 4. greyscale input comes back (H, W, 3), not 2-D.
    grey = Image.fromarray(np.arange(64, dtype=np.uint8).reshape(8, 8), mode="L")
    p = decode(_save(grey, "PNG"))[0]
    assert p.rgb.shape == (8, 8, 3)
    assert np.array_equal(p.rgb[:, :, 0], p.rgb[:, :, 1]) and np.array_equal(p.rgb[:, :, 1], p.rgb[:, :, 2])

    # 4b. 16-bit greyscale scales down with >>8, not a clip (TIFF, mode I;16).
    wide = np.array([[0, 255, 256, 32896, 65535]], dtype=np.uint16)
    wide_img = Image.fromarray(np.tile(wide, (4, 1)), mode="I;16")
    p = decode(_save(wide_img, "TIFF"))[0]
    assert np.array_equal(p.rgb[0, :, 0], (wide[0] >> 8).astype(np.uint8)), p.rgb[0, :, 0]

    # 4c. CMYK converts to RGB.
    cmyk = Image.new("CMYK", (5, 5), (0, 0, 0, 0))  # CMYK 0,0,0,0 -> white
    p = decode(_save(cmyk, "JPEG"))[0]
    assert p.rgb.shape == (5, 5, 3)

    # 5. every returned rgb is uint8, 3-channel, C-contiguous.
    for fmt, data in samples.items():
        if fmt == "pdf":
            continue
        p = decode(data)[0]
        assert p.rgb.dtype == np.uint8
        assert p.rgb.ndim == 3 and p.rgb.shape[2] == 3
        assert p.rgb.flags["C_CONTIGUOUS"]

    # 6. lossy is correct per format, with a note whenever True.
    expect_lossy = {"png": False, "bmp": False, "tiff": False,
                    "jpeg": True, "webp": True, "gif": True}
    for fmt, want in expect_lossy.items():
        p = decode(samples[fmt])[0]
        assert p.lossy == want, (fmt, p.lossy)
        assert (fmt in LOSSLESS) == (not want)
        if want:
            assert p.note, f"{fmt} is lossy but has no note"

    # 7. truncated/garbage bytes raise ValueError, not a silent wrong answer.
    try:
        decode(b"totally not an image")
        raise SystemExit("expected ValueError for garbage input")
    except ValueError:
        pass
    try:
        decode(b"\x89PNG\r\n\x1a\n" + b"garbage-after-valid-magic" * 4)
        raise SystemExit("expected ValueError for truncated PNG")
    except ValueError:
        pass

    # 8. MAX_PIXELS guard fires before the full array would be allocated.
    big = Image.new("RGB", (7000, 7000), (0, 0, 0))  # 49 MP > default 40 MP cap
    try:
        decode(_save(big, "PNG"))
        raise SystemExit("expected ValueError for over-MAX_PIXELS image")
    except ValueError as exc:
        assert "49.0" in str(exc) or "megapixels" in str(exc)
    del big

    # 9. PDF: full path if pypdfium2 is present, else a graceful skip (never a failure).
    try:
        import pypdfium2 as pdfium
        have_pdfium = True
    except ImportError:
        have_pdfium = False

    if have_pdfium:
        doc = pdfium.PdfDocument.new()
        for _ in range(MAX_PAGES + 2):
            doc.new_page(72, 144)  # 1in x 2in
        buf = io.BytesIO()
        doc.save(buf)
        doc.close()
        pdf_bytes = buf.getvalue()

        assert sniff(pdf_bytes) == "pdf"
        pages = decode(pdf_bytes, filename="notice.pdf", dpi=200)
        assert len(pages) == MAX_PAGES, len(pages)          # capped, not all 22
        assert pages[0].name == "notice.pdf p1"
        assert pages[0].page == 1 and pages[-1].page == MAX_PAGES
        assert all(pg.fmt == "pdf" and pg.lossy for pg in pages)
        assert f"{MAX_PAGES + 2} pages" in pages[-1].note   # cap noted on the last page
        # 1in x 2in at 200 DPI -> 200 x 400 px.
        assert pages[0].rgb.shape == (400, 200, 3), pages[0].rgb.shape
        print(f"  PDF: {MAX_PAGES + 2}-page doc -> {len(pages)} pages decoded, capped correctly")
    else:
        print("  PDF: pypdfium2 not installed, skipping PDF checks (not a failure)")

    print("imageio_any.py self-check OK")
