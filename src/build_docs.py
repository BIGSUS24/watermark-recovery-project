r"""Build output/paper/IEEE_Paper.pdf and IEEE_Paper.docx from paper/IEEE_Paper.tex.

The PDF is the real thing: tectonic compiles the actual IEEEtran class, so the
layout is IEEE's own, not an imitation.

The DOCX is a conversion and is honest about being one. Word has no IEEEtran, so
this reproduces the format by construction -- letter page with IEEE margins, a
single-column title block followed by a two-column body, Times New Roman at IEEE
sizes, centred roman-numeral section headings, italic lettered subsections, 8 pt
captions -- and fixes the things a plain `pandoc file.tex -o file.docx` gets wrong
on this paper:

  - \figorbox is our own macro, so pandoc emitted no figures at all. Rewritten to
    \includegraphics of the PNG (Word cannot display a PDF image).
  - four tables are wrapped in \resizebox for the LaTeX column; pandoc dropped
    them. Unwrapped, with brace matching rather than a regex.
  - \IEEEauthorblockN/A are unknown to pandoc, which produced two empty author
    paragraphs. Flattened to plain lines.
  - \ref/\eqref/\cite resolve to nothing without LaTeX. Every one is substituted
    with the real number read out of the .aux file tectonic just wrote, so the
    Word document's cross-references and citation numbers agree with the PDF's
    exactly instead of being renumbered independently.

Requires tectonic and pandoc. Paths are read from the environment first
(TECTONIC / PANDOC), then from PATH, then from the E:\tools install.

Usage:  python src/build_docs.py [--skip-pdf]
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

from lxml import etree

ROOT = Path(__file__).resolve().parent.parent
PAPER = ROOT / "paper" / "IEEE_Paper.tex"
OUTDIR = ROOT / "output" / "paper"
FIGDIR = ROOT / "output" / "figures"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W}


def tool(env_name, exe, fallback):
    return os.environ.get(env_name) or shutil.which(exe) or fallback


TECTONIC = tool("TECTONIC", "tectonic", r"E:\tools\tectonic\tectonic.exe")
PANDOC = tool("PANDOC", "pandoc", r"E:\tools\pandoc\pandoc.exe")

fails = []


def ck(cond, label, extra=""):
    print(("  ok   " if cond else "  FAIL ") + label + (f"  {extra}" if extra else ""))
    if not cond:
        fails.append(label)


def w(tag):
    return f"{{{W}}}{tag}"


def el(tag, **attrs):
    e = etree.Element(w(tag))
    for k, v in attrs.items():
        e.set(w(k), str(v))
    return e


# ---------------------------------------------------------------- 1. the PDF
def build_pdf():
    OUTDIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run([TECTONIC, "-X", "compile", PAPER.name, "--outdir",
                        str(OUTDIR), "--keep-intermediates"],
                       cwd=PAPER.parent, capture_output=True, text=True)
    log = r.stdout + r.stderr
    over = re.findall(r"Overfull \\hbox \(([\d.]+)pt", log)
    print(f"  tectonic exit {r.returncode}, {len(set(over))} distinct overfull boxes"
          + (f" {sorted(set(over))}" if over else ""))
    if r.returncode != 0:
        print(log[-3000:])
    return r.returncode == 0


# --------------------------------------------- 2. numbers, straight from LaTeX
def read_aux():
    """label -> printed number, and bibitem key -> citation number."""
    aux = (OUTDIR / "IEEE_Paper.aux").read_text(encoding="utf-8", errors="replace")
    labels = dict(re.findall(r"\\newlabel\{([^}]+)\}\{\{([^}]*)\}", aux))
    cites = dict(re.findall(r"\\bibcite\{([^}]+)\}\{([^}]*)\}", aux))
    return labels, cites


# ------------------------------------------------ 3. tex -> pandoc-ready tex
def unwrap_resizebox(tex):
    """Drop \resizebox{..}{..}{ BODY } down to BODY, matching braces properly --
    the body is a whole tabular full of braces, so a regex cannot find its end."""
    out, i, n = [], 0, 0
    key = r"\resizebox"
    while True:
        j = tex.find(key, i)
        if j < 0:
            out.append(tex[i:])
            return "".join(out), n
        out.append(tex[i:j])
        k = j + len(key)
        # skip the two size arguments, then take the third balanced group
        for _ in range(2):
            k = tex.index("{", k)
            depth = 0
            while True:
                if tex[k] == "{":
                    depth += 1
                elif tex[k] == "}":
                    depth -= 1
                    if depth == 0:
                        k += 1
                        break
                k += 1
        start = tex.index("{", k) + 1
        depth, m = 1, start
        while depth:
            if tex[m] == "{":
                depth += 1
            elif tex[m] == "}":
                depth -= 1
            m += 1
        out.append(tex[start:m - 1])
        n += 1
        i = m


def prep_tex(tex, labels, cites):
    counts = {}

    # our own figure macro: pandoc knows nothing about it, and Word cannot show a
    # PDF image, so point at the PNG twin that make_figures.py also writes
    def figure(m):
        png = m.group(1).replace(".pdf", ".png")
        assert (FIGDIR / png).exists(), f"missing {png}"
        # The width matters: without it pandoc uses the PNG's natural size, which is
        # far wider than a 3.5 in column, and the figure spills across the gutter
        # into the other column. 3.4 in is the LaTeX \columnwidth, less a hair.
        return "\\includegraphics[width=3.4in]{%s}" % (FIGDIR / png).as_posix()

    tex, counts["figures"] = re.subn(r"\\figorbox\{([^}]+)\}\{[^}]*\}", figure, tex)
    tex = re.sub(r"\n% A single-file build.*?\n\}\n", "\n", tex, flags=re.S)  # macro def
    tex, counts["resizebox"] = unwrap_resizebox(tex)

    # IEEEtran's author block, flattened to lines pandoc understands
    def authors(m):
        parts = []
        for blk in m.group(1).split(r"\and"):
            lines = re.findall(r"\\IEEEauthorblock[NA]\{(.*?)\}\s*(?:\n|$)", blk, re.S)
            parts.append(r" \\ ".join(x.strip() for x in lines if x.strip()))
        return "\\author{" + "\n\\and\n".join(parts) + "}"

    tex, counts["authorblocks"] = re.subn(r"\\author\{(.*?)\n\}\n", authors, tex, flags=re.S)

    # abstract and keywords: IEEE runs the label inline, bold italic
    tex, counts["abstract"] = re.subn(
        r"\\begin\{abstract\}\s*(.*?)\s*\\end\{abstract\}",
        lambda m: r"\noindent\textbf{\textit{Abstract---}}" + m.group(1), tex, flags=re.S)
    tex, counts["keywords"] = re.subn(
        r"\\begin\{IEEEkeywords\}\s*(.*?)\s*\\end\{IEEEkeywords\}",
        lambda m: r"\noindent\textbf{\textit{Index Terms---}}" + m.group(1), tex, flags=re.S)

    # equation numbers: \label inside the environment carries the number LaTeX
    # printed, so keep the number and drop the label
    def eqlabel(m):
        num = labels.get(m.group(1))
        return r"\qquad(%s)" % num if num else ""

    # \mathrm{MSB} becomes one OMML run per letter, which renders as "M S B".
    # \text{MSB} keeps it a single upright run and reads correctly.
    tex, counts["mathrm"] = re.subn(r"\\mathrm\{", r"\\text{", tex)

    # PSNR$_\Omega$ opens math straight into a subscript. LaTeX quietly attaches it
    # to an empty box; OMML draws that empty box as a visible placeholder square.
    # Pull the preceding word inside the math so the subscript has a real base.
    tex, counts["empty_base"] = re.subn(r"([A-Za-z]+)\$([_^])", r"$\\text{\1}\2", tex)

    # Single symbols are better off as characters than as equations. An OMML object
    # inside a table cell can neither shrink with the cell's font nor wrap, so a
    # column of "1.000 $\pm$ 0.000" stays at body size and breaks onto two lines,
    # and a header like PSNR$_{\mathrm{unmarked}}$ pushes its column off the page.
    sym = {"pm": "±", "times": "×", "approx": "≈", "leq": "≤",
           "geq": "≥", "le": "≤", "ge": "≥", "to": "→",
           "rho": "ρ", "alpha": "α", "sigma": "σ", "Omega": "Ω",
           "Delta": "Δ", "tau": "τ", "mu": "μ", "ell": "ℓ",
           "beta": "β", "gamma": "γ", "ne": "≠", "cdot": "·"}
    tex, n1 = re.subn(r"\$\\(%s)\$" % "|".join(sym),
                      lambda m: sym[m.group(1)], tex)
    # $>$ and $<$ are bare relations rather than macros, and as equations they come
    # out oversized in a table cell
    tex, n0 = re.subn(r"\$([<>])\$", r"\1", tex)
    n1 += n0
    tex, n2 = re.subn(r"\$\\text\{(\w+)\}_\\(%s)\$" % "|".join(sym),
                      lambda m: f"{m.group(1)}-{sym[m.group(2)]}", tex)
    tex, n3 = re.subn(r"\$\\text\{(\w+)\}_\{\\text\{(\w+)\}\}\$",
                      lambda m: f"{m.group(1)}-{m.group(2)}", tex)
    counts["symbols"] = n1 + n2 + n3

    tex, counts["eq_labels"] = re.subn(r"\\label\{(eq:[^}]+)\}", eqlabel, tex)
    tex = re.sub(r"\\label\{[^}]+\}", "", tex)

    # cross-references and citations, resolved to the PDF's own numbers
    miss = []

    def ref(m):
        num = labels.get(m.group(2))
        if num is None:
            miss.append(m.group(2))
            return m.group(0)
        return f"({num})" if m.group(1) == "eqref" else num

    tex, counts["refs"] = re.subn(r"\\(ref|eqref)\{([^}]+)\}", ref, tex)

    def cite(m):
        out = []
        for k in m.group(1).split(","):
            k = k.strip()
            if k not in cites:
                miss.append(k)
            out.append("[%s]" % cites.get(k, "?"))
        return ", ".join(out)

    tex, counts["cites"] = re.subn(r"\\cite\{([^}]+)\}", cite, tex)

    # the bibliography, numbered to match those citations
    def bib(m):
        items = re.split(r"\\bibitem\{([^}]+)\}", m.group(1))[1:]
        rows = []
        for key, body in zip(items[0::2], items[1::2]):
            rows.append("[%s] %s\n" % (cites.get(key, "?"), body.strip()))
        return "\\section*{References}\n\n" + "\n".join(rows)

    tex, counts["bibliography"] = re.subn(
        r"\\begin\{thebibliography\}\{[^}]*\}(.*?)\\end\{thebibliography\}",
        bib, tex, flags=re.S)

    counts["unresolved"] = sorted(set(miss))
    return tex, counts


# -------------------------------------------------- 4. the IEEE reference.docx
# IEEE conference, US Letter: 0.75in top, 1in bottom, 0.625in sides; two 3.5in
# columns with a 0.25in gutter. Sizes are half-points, indents/margins twentieths
# of a point.
PGSZ = dict(w=12240, h=15840)
PGMAR = dict(top=1080, right=900, bottom=1440, left=900, header=720, footer=720, gutter=0)
STYLES = {
    "Normal":         (dict(jc="both", spacing=(0, 0)), dict(sz=20)),
    "BodyText":       (dict(jc="both", ind=288, spacing=(0, 0)), dict(sz=20)),
    "FirstParagraph": (dict(jc="both", ind=288, spacing=(0, 0)), dict(sz=20)),
    "Compact":        (dict(jc="both", spacing=(0, 0)), dict(sz=20)),
    "Title":          (dict(jc="center", spacing=(0, 240)), dict(sz=48)),
    "Author":         (dict(jc="center", spacing=(0, 120)), dict(sz=22)),
    "Abstract":       (dict(jc="both", ind=288, spacing=(0, 120)), dict(sz=18, b=1)),
    "AbstractTitle":  (dict(jc="both", spacing=(0, 0)), dict(sz=18, b=1, i=1)),
    "Heading1":       (dict(jc="center", spacing=(240, 120)), dict(sz=20, smallCaps=1)),
    "Heading2":       (dict(jc="left", spacing=(180, 100)), dict(sz=20, i=1)),
    "Heading3":       (dict(jc="left", ind=288, spacing=(120, 80)), dict(sz=20, i=1)),
    "Caption":        (dict(jc="center", spacing=(80, 120)), dict(sz=16)),
    "TableCaption":   (dict(jc="center", spacing=(80, 60)), dict(sz=16)),
    "ImageCaption":   (dict(jc="center", spacing=(80, 120)), dict(sz=16)),
    "Bibliography":   (dict(jc="both", spacing=(0, 0)), dict(sz=16)),
}


def style_pPr(spec):
    p = el("pPr")
    if "jc" in spec:
        p.append(el("jc", val=spec["jc"]))
    if "ind" in spec:
        p.append(el("ind", firstLine=spec["ind"]))
    before, after = spec.get("spacing", (0, 0))
    p.append(el("spacing", before=before, after=after, line=240, lineRule="auto"))
    return p


def style_rPr(spec):
    r = el("rPr")
    f = el("rFonts")
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        f.set(w(a), "Times New Roman")
    r.append(f)
    for flag in ("b", "i", "smallCaps"):
        if spec.get(flag):
            r.append(el(flag, val="1"))
        elif flag in ("b", "i"):
            r.append(el(flag, val="0"))
    r.append(el("sz", val=spec["sz"]))
    r.append(el("szCs", val=spec["sz"]))
    return r


def make_reference_docx(dst: Path):
    raw = subprocess.run([PANDOC, "--print-default-data-file", "reference.docx"],
                         capture_output=True).stdout
    src = dst.with_suffix(".src.docx")
    src.write_bytes(raw)
    zin = zipfile.ZipFile(src)
    styles = etree.fromstring(zin.read("word/styles.xml"))

    # document-wide default: Times New Roman 10 pt, no paragraph space-after
    dd = styles.find("w:docDefaults", NS)
    rpr = dd.find("w:rPrDefault/w:rPr", NS)
    for child in list(rpr):
        if child.tag in (w("rFonts"), w("sz"), w("szCs")):
            rpr.remove(child)
    f = el("rFonts")
    for a in ("ascii", "hAnsi", "cs", "eastAsia"):
        f.set(w(a), "Times New Roman")
    rpr.insert(0, f)
    rpr.append(el("sz", val=20))
    rpr.append(el("szCs", val=20))
    ppr = dd.find("w:pPrDefault/w:pPr", NS)
    for child in list(ppr):
        ppr.remove(child)
    ppr.append(el("spacing", before=0, after=0, line=240, lineRule="auto"))

    have = {s.get(w("styleId")): s for s in styles.findall("w:style", NS)}
    for sid, (pspec, rspec) in STYLES.items():
        st = have.get(sid)
        if st is None:                       # ImageCaption is pandoc-invented
            st = el("style", type="paragraph", styleId=sid)
            nm = el("name", val=sid)
            st.append(nm)
            st.append(el("basedOn", val="Normal"))
            styles.append(st)
        for child in list(st):
            if child.tag in (w("pPr"), w("rPr")):
                st.remove(child)
        st.append(style_pPr(pspec))
        st.append(style_rPr(rspec))

    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/styles.xml":
                data = etree.tostring(styles, xml_declaration=True,
                                      encoding="UTF-8", standalone=True)
            zout.writestr(item, data)
    zin.close()
    src.unlink()


# ------------------------------------------- 5. post-process the built docx
ROMAN = ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]


def sectpr(cols, continuous=False):
    s = el("sectPr")
    if continuous:
        # w:type says how THIS section begins, so it belongs on the two-column body
        # section, not on the title block that precedes it. Put it on the title
        # block instead and the body still starts on a new page, leaving the title
        # alone on page 1 -- which is exactly the bug this comment replaced.
        s.append(el("type", val="continuous"))
    s.append(el("pgSz", **PGSZ))
    s.append(el("pgMar", **PGMAR))
    s.append(el("cols", num=cols, space=360, equalWidth=1)
             if cols > 1 else el("cols", num=1, space=360))
    s.append(el("docGrid", linePitch=360))
    return s


def prefix_runs(p, text, *, italic=False, br=False):
    """Put a literal prefix at the start of a paragraph, in its own run."""
    r = el("r")
    rpr = el("rPr")
    if italic:
        rpr.append(el("i", val="1"))
    r.append(rpr)
    t = el("t")
    t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    r.append(t)
    if br:
        r.append(el("br"))
    idx = 1 if p.find("w:pPr", NS) is not None else 0
    p.insert(idx, r)


WIDE_COLS = 5          # a table this wide cannot be read in a 3.5 in column


def widen_tables(body, style_of):
    """Give every wide table a full-page-width section of its own.

    LaTeX shrinks these to fit with \resizebox; Word has no equivalent, so a
    nine-column table inside a 3.5 in column wraps every cell and pushes its last
    two columns off the edge. IEEE's own answer is table*, which spans both
    columns -- in Word that is a one-column section around the table. Sections are
    delimited by paragraphs, and a sectPr ENDS the section at the paragraph
    carrying it, so the two-column properties go on the paragraph before the
    caption and the one-column properties on a paragraph after the table.
    """
    n = 0
    for tblel in list(body.findall("w:tbl", NS)):
        cols = len(tblel.findall("w:tblGrid/w:gridCol", NS))
        if cols < WIDE_COLS:
            continue
        kids = list(body)
        i = kids.index(tblel)

        # the caption sits with its table, so start the full-width run above it
        start = i
        while start > 0 and kids[start - 1].tag == w("p") \
                and style_of(kids[start - 1]) == "TableCaption":
            start -= 1
        before = kids[start - 1] if start > 0 else None
        if before is not None and before.tag == w("p"):
            pPr = before.find("w:pPr", NS)
            if pPr is None:
                pPr = el("pPr")
                before.insert(0, pPr)
            if pPr.find("w:sectPr", NS) is None:
                pPr.append(sectpr(2, continuous=True))
        # ...and close it just after the table
        closer = el("p")
        cpPr = el("pPr")
        cpPr.append(el("pStyle", val="Compact"))
        cpPr.append(sectpr(1, continuous=True))
        closer.append(cpPr)
        tblel.addnext(closer)
        n += 1
    return n


FULL_W = 10440          # 7.25 in of text, in twentieths of a point
COL_W = 5040            # one 3.5 in column
MIN_COL = 500
CELL_PAD = 300          # Word's default left+right cell margins, plus a little
CHAR_W = 80             # average glyph advance for 8 pt Times, in twips
PROSE_CAP = 34          # widest a prose column may ask for, in characters


def size_table_columns(body):
    """Set every column's width from the longest text in it.

    Pandoc writes widths derived from the LaTeX column spec, which spreads them
    evenly: "Tamper Class" then breaks mid-word while the numeric columns sit half
    empty. Autofit does not rescue it either -- LibreOffice keeps honouring the
    tblGrid proportions -- so compute the widths here instead of hoping. Cells that
    span columns (the footnote row under three of these tables) are excluded, since
    a paragraph of note text would otherwise decide the whole layout.
    """
    n = 0
    for tblel in body.findall("w:tbl", NS):
        grid = tblel.find("w:tblGrid", NS)
        cols = len(grid.findall("w:gridCol", NS))
        if not cols:
            continue
        longest = [1] * cols
        floors = [1] * cols
        for tr in tblel.findall("w:tr", NS):
            i = 0
            for tc in tr.findall("w:tc", NS):
                span = tc.find("w:tcPr/w:gridSpan", NS)
                width = int(span.get(w("val"))) if span is not None else 1
                if width == 1 and i < cols:
                    # the whole cell, not its longest word: "1.000 +/- 0.000" wants
                    # thirteen characters of width, and sizing by the word "1.000"
                    # is what put the "+/- 0.000" half on a second line
                    txt = "".join(t.text or "" for t in tc.findall(".//w:t", NS))
                    longest[i] = max(longest[i], len(txt.strip()))
                    for word in txt.split():
                        floors[i] = max(floors[i], len(word))
                i += width
        total_w = FULL_W if cols >= WIDE_COLS else COL_W
        # What a column needs is its text plus Word's cell padding -- leaving the
        # padding out is what split "0.9824" over two lines. A prose column (the
        # Notes column of Table IV runs to about a hundred characters) is capped,
        # because letting it ask for its full length starves every numeric column
        # beside it; prose is meant to wrap. The floor is the longest single word,
        # so no column is ever squeezed into breaking a word in half.
        floor = [CELL_PAD + CHAR_W * f for f in floors]
        want = [CELL_PAD + CHAR_W * min(L, PROSE_CAP) for L in longest]
        if sum(want) <= total_w:
            # Everything fits: give each column what it asked for and share the
            # slack in proportion. Distributing the slack by unmet hunger instead
            # short-changes a narrow column whose hunger is small -- which is what
            # left "WM SSIM" too narrow for the "0.9824" beneath it.
            widths = [wd + (total_w - sum(want)) * wd // sum(want) for wd in want]
        elif sum(floor) <= total_w:
            spare = total_w - sum(floor)
            hunger = [max(0, wd - f) for wd, f in zip(want, floor)]
            tot = sum(hunger) or 1
            widths = [f + spare * h // tot for f, h in zip(floor, hunger)]
        else:                                     # pathological: scale the floors
            widths = [max(MIN_COL, f * total_w // sum(floor)) for f in floor]
        widths[-1] += total_w - sum(widths)      # absorb integer-division slack

        pr = tblel.find("w:tblPr", NS)
        if pr is None:
            pr = el("tblPr")
            tblel.insert(0, pr)
        for tag in ("tblW", "tblLayout"):
            for old in pr.findall(f"w:{tag}", NS):
                pr.remove(old)
        tw = el("tblW")
        tw.set(w("w"), str(total_w))
        tw.set(w("type"), "dxa")
        pr.append(tw)
        lay = el("tblLayout")
        lay.set(w("type"), "fixed")
        pr.append(lay)

        for gc, width in zip(grid.findall("w:gridCol", NS), widths):
            gc.set(w("w"), str(width))
        for tr in tblel.findall("w:tr", NS):
            i = 0
            for tc in tr.findall("w:tc", NS):
                span = tc.find("w:tcPr/w:gridSpan", NS)
                k = int(span.get(w("val"))) if span is not None else 1
                tcPr = tc.find("w:tcPr", NS)
                if tcPr is None:
                    tcPr = el("tcPr")
                    tc.insert(0, tcPr)
                for old in tcPr.findall("w:tcW", NS):
                    tcPr.remove(old)
                cw = el("tcW")
                cw.set(w("w"), str(sum(widths[i:i + k])))
                cw.set(w("type"), "dxa")
                tcPr.insert(0, cw)
                i += k
        n += 1
    return n


def shrink_table_text(body):
    """Set table text to IEEE's 8 pt (7 pt for the widest table), and clear the
    paragraph indent inside cells.

    The indent is the one that actually matters. Cell paragraphs inherit the body
    style's 0.2 in first-line indent, so the FIRST line of every cell is 14.4 pt
    narrower than the column -- which is why "0.9824" broke after five characters
    in a column measurably wide enough for all six, and why the header cells wrapped.
    Measured from the render: the text began 14.4 pt inside the column edge.
    """
    n = 0
    for tblel in body.findall("w:tbl", NS):
        cols = len(tblel.findall("w:tblGrid/w:gridCol", NS))
        half_points = 14 if cols >= 7 else 16
        for p in tblel.iter(w("p")):
            pPr = p.find("w:pPr", NS)
            if pPr is None:
                pPr = el("pPr")
                p.insert(0, pPr)
            for old in pPr.findall("w:ind", NS):
                pPr.remove(old)
            ind = el("ind")
            for side in ("firstLine", "left", "right", "start", "end"):
                ind.set(w(side), "0")
            # pPr's children are an ordered sequence: pStyle ... spacing, ind, jc.
            # Word rejects the file outright if ind lands before pStyle or after jc.
            jc = pPr.find("w:jc", NS)
            if jc is None:
                pPr.append(ind)
            else:
                jc.addprevious(ind)
            for r in p.findall("w:r", NS):
                rpr = r.find("w:rPr", NS)
                if rpr is None:
                    rpr = el("rPr")
                    r.insert(0, rpr)
                for old in rpr.findall("w:sz", NS) + rpr.findall("w:szCs", NS):
                    rpr.remove(old)
                rpr.append(el("sz", val=half_points))
                rpr.append(el("szCs", val=half_points))
            n += 1
    return n


def postprocess(docx: Path):
    zin = zipfile.ZipFile(docx)
    doc = etree.fromstring(zin.read("word/document.xml"))
    body = doc.find("w:body", NS)

    # IEEE page setup, two columns, on the document-level section
    for old in body.findall("w:sectPr", NS):
        body.remove(old)
    body.append(sectpr(2, continuous=True))

    paras = body.findall("w:p", NS)

    def style_of(p):
        s = p.find("w:pPr/w:pStyle", NS)
        return s.get(w("val")) if s is not None else None

    # the title block runs full width; everything after it is two-column. A sectPr
    # inside a paragraph ends the section AT that paragraph, so it goes on the last
    # title-block paragraph.
    last_title = None
    for p in paras:
        if style_of(p) in ("Title", "Author"):
            last_title = p
        elif last_title is not None:
            break
    n_split = 0
    if last_title is not None:
        pPr = last_title.find("w:pPr", NS)
        pPr.append(sectpr(1))
        n_split = 1

    # heading numbers: LaTeX printed I., A., 1); pandoc prints nothing
    sec = sub = subsub = 0
    n_head = 0
    for p in paras:
        s = style_of(p)
        if s == "Heading1":
            sec += 1
            sub = subsub = 0
            prefix_runs(p, f"{ROMAN[sec]}.  ")
            n_head += 1
        elif s == "Heading2":
            sub += 1
            subsub = 0
            prefix_runs(p, f"{chr(64 + sub)}.  ", italic=True)
            n_head += 1
        elif s == "Heading3":
            subsub += 1
            prefix_runs(p, f"{subsub})  ", italic=True)
            n_head += 1

    # caption labels, matching the numbers the in-text references now carry
    tbl, fig = 0, 0
    for p in paras:
        s = style_of(p)
        if s == "TableCaption":
            tbl += 1
            prefix_runs(p, f"TABLE {ROMAN[tbl]}", br=True)
        elif s == "ImageCaption":
            fig += 1
            prefix_runs(p, f"Fig. {fig}.  ")

    n_wide = widen_tables(body, style_of)
    n_fit = size_table_columns(body)
    n_small = shrink_table_text(body)

    with zipfile.ZipFile(docx.with_suffix(".tmp"), "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/document.xml":
                data = etree.tostring(doc, xml_declaration=True, encoding="UTF-8",
                                      standalone=True)
            zout.writestr(item, data)
    zin.close()
    docx.with_suffix(".tmp").replace(docx)
    return dict(section_break=n_split, headings=n_head, table_captions=tbl,
                figure_captions=fig, wide_tables=n_wide, sized_tables=n_fit,
                sized_table_paras=n_small)


# --------------------------------------------------------------------- main
def main():
    skip_pdf = "--skip-pdf" in sys.argv
    print("== PDF (real IEEEtran via tectonic) ==")
    if skip_pdf:
        print("  skipped")
    else:
        ck(build_pdf(), "tectonic compiled the paper")
    pdf = OUTDIR / "IEEE_Paper.pdf"
    ck(pdf.exists() and pdf.stat().st_size > 100_000, "PDF written",
       f"{pdf.stat().st_size / 1024:.0f} KB" if pdf.exists() else "missing")

    print("\n== DOCX (constructed IEEE format via pandoc) ==")
    labels, cites = read_aux()
    ck(len(labels) > 20 and len(cites) > 20, "aux gave the printed numbers",
       f"{len(labels)} labels, {len(cites)} bibitems")
    tex, c = prep_tex(PAPER.read_text(encoding="utf-8"), labels, cites)
    print(f"  rewrote: {c['figures']} figures, {c['resizebox']} resizebox wrappers, "
          f"{c['authorblocks']} author block, {c['refs']} refs, {c['cites']} cite groups, "
          f"{c['eq_labels']} equation numbers, {c['bibliography']} bibliography")
    ck(not c["unresolved"], "every ref and cite resolved to a number", c["unresolved"])
    # four tables are wrapped for the LaTeX column; the narrow null-condition one is not
    ck(c["figures"] == 2 and c["resizebox"] == 4 and c["authorblocks"] == 1
       and c["abstract"] == 1 and c["keywords"] == 1 and c["bibliography"] == 1,
       "every structural rewrite applied", c)

    work = OUTDIR / "_pandoc_input.tex"
    work.write_text(tex, encoding="utf-8")
    ref = OUTDIR / "_ieee_reference.docx"
    make_reference_docx(ref)
    docx = OUTDIR / "IEEE_Paper.docx"
    r = subprocess.run([PANDOC, str(work), "-o", str(docx), "--reference-doc", str(ref),
                        "--resource-path", f"{ROOT / 'paper'}{os.pathsep}{FIGDIR}"],
                       capture_output=True, text=True)
    if r.returncode != 0 or r.stderr.strip():
        print("  pandoc:", (r.stderr or r.stdout).strip()[:1500])
    ck(r.returncode == 0, "pandoc converted the paper")
    stats = postprocess(docx)
    print(f"  post-processed: {stats}")

    z = zipfile.ZipFile(docx)
    x = z.read("word/document.xml").decode("utf-8")
    media = [n for n in z.namelist() if n.startswith("word/media/")]
    ck(x.count("<w:tbl>") == 5, "all five tables present", x.count("<w:tbl>"))
    ck(len(media) == 2, "both figures embedded", media)
    ck(x.count("<m:oMath") > 300, "math converted to Word equations (OMML)",
       x.count("<m:oMath"))
    ck('w:num="2"' in x and 'w:num="1"' in x,
       "single-column title block over a two-column body")
    ck(f'w:w="{PGSZ["w"]}"' in x, "US Letter page size")
    ck("Times New Roman" in z.read("word/styles.xml").decode("utf-8"),
       "Times New Roman throughout")
    ck(stats["headings"] >= 20 and stats["table_captions"] == 5
       and stats["figure_captions"] == 2, "headings and captions labelled", stats)
    ck("figorbox" not in x and "resizebox" not in x and "IEEEauthorblock" not in x,
       "no LaTeX macro names leaked into the document")

    # the two layout invariants that were actually wrong once, so they get checks:
    # every column grid must add up to its table's declared width, and no cell may
    # keep the body's first-line indent (which silently narrows the first line and
    # breaks numbers in half)
    doc = etree.fromstring(x.encode("utf-8"))
    body = doc.find("w:body", NS)
    bad_w, bad_ind = [], 0
    for i, tblel in enumerate(body.findall("w:tbl", NS), 1):
        grid = sum(int(g.get(w("w"))) for g in tblel.findall("w:tblGrid/w:gridCol", NS))
        declared = tblel.find("w:tblPr/w:tblW", NS)
        if declared is None or int(declared.get(w("w"))) != grid:
            bad_w.append(i)
        for p in tblel.iter(w("p")):
            ind = p.find("w:pPr/w:ind", NS)
            if ind is None or ind.get(w("firstLine")) != "0":
                bad_ind += 1
    ck(not bad_w, "every table's columns add up to its declared width", bad_w)
    ck(not bad_ind, "no table cell keeps the body first-line indent", bad_ind)
    body_txt = re.sub(r"<[^>]+>", "", x)
    for needle in ("43.17", "0.9824", "1802240", "26.80", "Korus"):
        ck(needle in body_txt, f"table number present in Word: {needle}")
    ck("??" not in body_txt, "no unresolved reference markers")
    z.close()
    for tmp in (work, ref):
        tmp.unlink(missing_ok=True)
    # the .aux stays: --skip-pdf reads the printed numbers out of it. Both it and
    # the .log are gitignored.
    for junk in OUTDIR.glob("IEEE_Paper.*"):
        if junk.suffix in (".log", ".out", ".bbl", ".blg"):
            junk.unlink()

    print(f"\n{pdf.relative_to(ROOT)}   {pdf.stat().st_size / 1024:.0f} KB")
    print(f"{docx.relative_to(ROOT)}  {docx.stat().st_size / 1024:.0f} KB")
    print(f"{len(fails)} failures")
    print("DOCS OK" if not fails else "FAIL: " + "; ".join(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
