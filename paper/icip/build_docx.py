r"""Build output/paper/ICIP_Paper.pdf and ICIP_Paper.docx from paper/ICIP_Paper.tex.

The PDF is the real thing (tectonic on the actual IEEEtran class). The DOCX is
the same content rebuilt in Word: single-column title block over a two-column
body, Times New Roman at IEEE sizes, cross-references and citation numbers taken
from the PDF's own .aux so both documents agree.

All of that machinery already exists in src/build_docs.py for the long paper, so
this reuses it and only fixes what is different here:

  * this paper uses plain \includegraphics inside figure*, not the long paper's
    \figorbox macro -- Word has no two-column floats and cannot display a PDF
    image, so each figure becomes a 3.4 in PNG in the column;
  * \graphicspath and \balance are LaTeX-only and are dropped.

Usage:  python paper/icip/build_docx.py [--skip-pdf]
"""
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import build_docs as bd  # noqa: E402

PAPER = ROOT / "paper" / "ICIP_Paper.tex"
OUTDIR = bd.OUTDIR
FIGDIR = bd.FIGDIR


def prep(tex: str) -> tuple[str, dict]:
    """Everything prep_tex does, plus this paper's own differences."""
    counts = {}
    tex = re.sub(r"\\graphicspath\{[^\n]*\}\n", "", tex)
    tex = tex.replace("\\balance\n", "")
    tex = re.sub(r"\\IEEEoverridecommandlockouts\n", "", tex)

    # Word has no two-column float; each figure sits in the column at 3.4 in
    tex, n1 = re.subn(r"\\(begin|end)\{figure\*\}", r"\\\1{figure}", tex)
    tex, n2 = re.subn(r"\\(begin|end)\{table\*\}", r"\\\1{table}", tex)
    counts["spanning_floats"] = n1 + n2

    def graphic(m):
        png = Path(m.group(1)).with_suffix(".png").name
        assert (FIGDIR / png).exists(), f"missing {png}"
        return "\\includegraphics[width=3.4in]{%s}" % (FIGDIR / png).as_posix()

    # prep_tex counts the long paper's \figorbox macro under "figures", so this
    # one gets its own key rather than being overwritten by the update() below
    tex, counts["graphics"] = re.subn(
        r"\\includegraphics\[[^\]]*\]\{([^}]+)\}", graphic, tex)

    # booktabs partial rules have no pandoc equivalent and come through as text
    tex, counts["cmidrules"] = re.subn(r"\\cmidrule\(lr\)\{[^}]*\}", "", tex)

    labels, cites = read_aux()
    tex, c = bd.prep_tex(tex, labels, cites)
    counts.update(c)
    counts["labels"], counts["bibitems"] = len(labels), len(cites)
    return tex, counts


def read_aux() -> tuple[dict, dict]:
    aux = (OUTDIR / "ICIP_Paper.aux").read_text(encoding="utf-8", errors="replace")
    labels = dict(re.findall(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}", aux))
    cites = dict(re.findall(r"\\bibcite\{([^}]+)\}\{([^}]*)\}", aux))
    return labels, cites


def main() -> int:
    bd.PAPER = PAPER  # build_pdf() compiles whatever PAPER points at
    print("== PDF (IEEEtran via tectonic) ==")
    if "--skip-pdf" in sys.argv:
        print("  skipped")
    else:
        bd.ck(bd.build_pdf(), "tectonic compiled the paper")
    pdf = OUTDIR / "ICIP_Paper.pdf"
    import pymupdf
    pages = pymupdf.open(pdf).page_count
    bd.ck(4 <= pages <= 6, "PDF is within the 4-6 page limit", f"{pages} pages")

    print("\n== DOCX (IEEE format via pandoc) ==")
    tex, c = prep(PAPER.read_text(encoding="utf-8"))
    print(f"  rewrote: {c['graphics']} figures, {c['spanning_floats']} spanning floats, "
          f"{c['refs']} refs, {c['cites']} cite "
          f"groups, {c['eq_labels']} equation numbers")
    bd.ck(not c["unresolved"], "every ref and cite resolved to a number", c["unresolved"])
    bd.ck(c["graphics"] == 3 and c["authorblocks"] == 1 and c["abstract"] == 1
          and c["keywords"] == 1 and c["bibliography"] == 1,
          "every structural rewrite applied", c)

    work = OUTDIR / "_icip_pandoc_input.tex"
    work.write_text(tex, encoding="utf-8")
    ref = OUTDIR / "_icip_reference.docx"
    bd.make_reference_docx(ref)
    docx = OUTDIR / "ICIP_Paper.docx"
    r = subprocess.run([bd.PANDOC, str(work), "-o", str(docx), "--reference-doc",
                        str(ref), "--resource-path",
                        f"{ROOT / 'paper'}{os.pathsep}{FIGDIR}"],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stderr.strip():
        print("  pandoc:", (r.stderr or r.stdout).strip()[:1200])
    bd.ck(r.returncode == 0, "pandoc converted the paper")
    print(f"  post-processed: {bd.postprocess(docx)}")

    with zipfile.ZipFile(docx) as z:
        x = z.read("word/document.xml").decode("utf-8")
        media = [n for n in z.namelist() if n.startswith("word/media/")]
        bd.ck(x.count("<w:tbl>") == 3, "all three tables present", x.count("<w:tbl>"))
        bd.ck(len(media) == 3, "all three figures embedded", media)
        bd.ck(x.count("<m:oMath") > 100, "math converted to Word equations (OMML)",
              x.count("<m:oMath"))
        bd.ck('w:num="2"' in x and 'w:num="1"' in x,
              "single-column title block over a two-column body")
        body_txt = re.sub(r"<[^>]+>", "", x)
        for needle in ("45.648", "0.99356", "1,802,240", "0.6482", "Korus",
                       "Deepti Varshney", "manetejas710@gmail.com"):
            bd.ck(needle in body_txt, f"present in Word: {needle}")
        bd.ck("??" not in body_txt, "no unresolved reference markers")
        bd.ck("IEEEauthorblock" not in x and "includegraphics" not in x,
              "no LaTeX macro names leaked into the document")

    for tmp in (work, ref):
        tmp.unlink(missing_ok=True)
    print(f"\n{len(bd.fails)} failures")
    print("OK" if not bd.fails else "FAIL: " + "; ".join(bd.fails))
    return 1 if bd.fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
