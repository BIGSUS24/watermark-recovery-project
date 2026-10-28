"""Stitch paper/icip/parts/*.tex into paper/ICIP_Paper.tex and compile it.

The parts are kept separate because they were drafted separately; the submitted
artifact is one self-contained .tex. Only the bibliography entries actually cited
are carried over, renumbered into order of first citation as IEEE requires.

    python paper/icip/assemble.py [--no-pdf]
"""
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PARTS = HERE / "parts"
OUT = ROOT / "paper" / "ICIP_Paper.tex"

ORDER = ["s1_intro", "fig_arch", "s2_related", "s3_method", "s4_setup",
         "tab_imperc", "s5_results", "fig_qual", "fig_rho", "tab_results",
         "tab_compare", "s6_conclusion"]


def bibitems(src: str) -> dict[str, str]:
    """{key: whole \\bibitem block} from the long paper's bibliography."""
    out, parts = {}, re.split(r"\\bibitem\{", src)
    for chunk in parts[1:]:
        key, _, body = chunk.partition("}")
        out[key] = ("\\bibitem{" + key + "}" + body).rstrip()
    return out


def main() -> None:
    body = "\n\n".join((PARTS / f"{name}.tex").read_text(encoding="utf-8").strip()
                       for name in ORDER)
    doc = (PARTS / "head.tex").read_text(encoding="utf-8").replace(
        "%%ABSTRACT%%", (PARTS / "abstract.tex").read_text(encoding="utf-8").strip())

    all_items = bibitems((PARTS / "bib.tex").read_text(encoding="utf-8"))
    cited: list[str] = []
    for m in re.finditer(r"\\cite\{([^}]*)\}", body):
        for key in m.group(1).split(","):
            key = key.strip()
            if key and key not in cited:
                cited.append(key)
    missing = [k for k in cited if k not in all_items]
    assert not missing, f"cited but not in bib.tex: {missing}"

    refs = "\n\n".join(all_items[k] for k in cited)
    doc += "\n\n" + body + "\n\n\\balance\n\n"
    doc += ("\\begin{thebibliography}{%d}\n\n%s\n\n\\end{thebibliography}\n\n"
            % (len(cited), refs))
    doc += "\\end{document}\n"
    OUT.write_text(doc, encoding="utf-8")
    print(f"wrote {OUT}  ({len(cited)} references)")

    if "--no-pdf" not in sys.argv:
        subprocess.run(["tectonic", "-X", "compile", str(OUT),
                        "--outdir", str(ROOT / "output" / "paper")], check=True)
        pdf = ROOT / "output" / "paper" / "ICIP_Paper.pdf"
        import pymupdf
        print(f"{pdf}: {pymupdf.open(pdf).page_count} pages")


if __name__ == "__main__":
    main()
