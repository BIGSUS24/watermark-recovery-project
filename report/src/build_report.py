"""Assemble Project_Report.docx to the departmental format annexure.

Formatting rules taken straight from Project_Report_Format_SEM_I_2019_Course.doc:
A4, Times New Roman 12 pt body, justified, 1.5 spacing, five-space first-line
indent, chapter titles bold 14 pt upper case centred, section headings bold
12 pt upper case left, figure captions below at 12 pt, the ADYPSOE footer on
every page and page numbers centred below it, small roman for the front matter
and arabic restarting at 1 from the introduction.

Two passes: the first lays the document out with placeholder page numbers, the
second reads the real ones back out of the rendered PDF. The body is its own
Word section with its own page counter, so nothing in the front matter can move
a body page number between the passes.
"""
import re
import subprocess
import sys
from pathlib import Path

import docx
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Mm, Pt, RGBColor

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
FIGS = HERE / "figs"
OUT = Path("E:/cheat/Selection/watermark-recovery-project/report")
SOFFICE = "E:/tools/libreoffice/program/soffice.exe"

FONT = "Times New Roman"
BODY = 12
TEXT_W = 5.85  # inches between the 37 mm and 23.4 mm margins on A4

COLLEGE = "AJEENKYA DY PATIL SCHOOL OF ENGINEERING"
ADDRESS = "CHARHOLI BUDRUK, LOHEGAON, PUNE 412105"
DEPT = "DEPARTMENT OF COMPUTER ENGINEERING"
UNIV = "SAVITRIBAI PHULE PUNE UNIVERSITY"
YEAR = "2026 - 2027"
TITLE = "WATERMARK-GUIDED TAMPER LOCALIZATION AND RECOVERY"
SUBTITLE = ("A Key-Seeded Self-Embedding Fragile Watermarking Scheme with Joint "
            "Localization and Restoration Assessment")
GUIDE = "Prof. [Guide Name]"
HOD = "Dr. Pankaj Agarkar"
PRINCIPAL = "Dr. F. B. Sayyad"
COORD = "Dr. Amruta Chitari"
STUDENTS = [("[STUDENT NAME 1]", "[EXAM NO.]"), ("[STUDENT NAME 2]", "[EXAM NO.]"),
            ("[STUDENT NAME 3]", "[EXAM NO.]"), ("[STUDENT NAME 4]", "[EXAM NO.]")]

CHAPTERS = [
    (1, "INTRODUCTION", "ch1.txt"),
    (2, "PROBLEM DEFINITION AND SCOPE", "ch2.txt"),
    (3, "PROJECT PLAN", "ch3.txt"),
    (4, "SOFTWARE REQUIREMENTS SPECIFICATION", "ch4.txt"),
    (5, "SYSTEM DESIGN", "ch5.txt"),
    (6, "OTHER SPECIFICATION", "ch6.txt"),
    (7, "CONCLUSIONS AND FUTURE WORK", "ch7.txt"),
]

FIGURES = {
    "1.1": ("fig1_1.png", "Passive forensic detection against active self-embedding. "
                          "Only the active path carries the original content forward.", 5.8),
    "2.1": ("fig2_1.png", "The four tamper classes applied to a watermarked image, shown "
                          "here at a 30% tamper ratio.", 5.8),
    "3.1": ("fig3_1.png", "Project schedule. Shaded bars are complete; hatched bars are "
                          "in progress or planned.", 5.8),
    "4.1": ("fig4_1.png", "The incremental model as applied: each increment carries its "
                          "own design, build and test cycle, and measurement feeds back "
                          "into the increment that caused a defect.", 5.8),
    "5.1": ("fig5_1.png", "System architecture. The key and the image identifier seed "
                          "both the block map and the tag; the dashed path carries the "
                          "distributed image, which may be tampered before verification.",
            5.8),
    "5.2": ("fig5_2.png", "Per-block payload layout at B = 8.", 5.8),
    "5.3": ("fig5_3.png", "The key-seeded block mapping i -> m(i).", 5.6),
    "5.4": ("fig5_4.png", "Data flow diagram, Level 0 (context diagram).", 5.6),
    "5.5": ("fig5_5.png", "Data flow diagram, Level 1.", 5.8),
    "5.6": ("fig5_6.png", "Data flow diagram, Level 2: decomposition of processes 3.0 "
                          "and 4.0.", 5.8),
    "5.7": ("fig5_7.png", "Entity-relationship diagram of the protected-image library.",
            5.8),
    "5.8": ("fig5_8.png", "Use case diagram.", 5.8),
    "5.9": ("fig5_9.png", "Class diagram. Dashed arrows are dependencies and point at "
                          "the class whose operations are used.", 5.8),
    "5.10": ("fig5_10.png", "Sequence diagram for the protect, damage, verify and repair "
                            "round trip.", 5.8),
    "5.11": ("fig5_11.png", "Activity diagram for verification and recovery.", 5.8),
    "5.12": ("fig5_12.png", "State machine diagram: the lifecycle of a protected image.",
             5.8),
    "5.13": ("fig5_13.png", "Component diagram.", 5.8),
    "5.14": ("fig5_14.png", "Deployment diagram.", 5.8),
    "7.1": ("fig7_1.png", "Recoverability rate against tamper ratio. The measured curve "
                          "stays above its own structural bound at every ratio.", 5.0),
    "7.2": ("fig7_2.png", "In-region and whole-image PSNR against tamper ratio.", 5.0),
    "7.3": ("fig7_3.png", "Qualitative result on Lena under copy-paste splicing. The "
                          "speckles in the recovered panel are blocks marked "
                          "unrecoverable, not noise.", 5.8),
}

ABBREVIATIONS = [
    ("ADYPSOE", "Ajeenkya DY Patil School of Engineering"),
    ("C2PA", "Coalition for Content Provenance and Authenticity"),
    ("COCOMO", "Constructive Cost Model"),
    ("CPU", "Central Processing Unit"),
    ("DCT", "Discrete Cosine Transform"),
    ("DFD", "Data Flow Diagram"),
    ("DICOM", "Digital Imaging and Communications in Medicine"),
    ("ER", "Entity-Relationship"),
    ("FPR", "False Positive Rate"),
    ("GPU", "Graphics Processing Unit"),
    ("HMAC", "Hash-based Message Authentication Code"),
    ("IoU", "Intersection over Union"),
    ("KLOC", "Thousands of Lines of Code"),
    ("LSB", "Least Significant Bit"),
    ("MSB", "Most Significant Bit"),
    ("PACS", "Picture Archiving and Communication System"),
    ("PNG", "Portable Network Graphics"),
    ("PSNR", "Peak Signal-to-Noise Ratio"),
    ("SDLC", "Software Development Life Cycle"),
    ("SHA", "Secure Hash Algorithm"),
    ("SPPU", "Savitribai Phule Pune University"),
    ("SQL", "Structured Query Language"),
    ("SSIM", "Structural Similarity Index Measure"),
    ("UML", "Unified Modeling Language"),
    ("USC-SIPI", "University of Southern California, Signal and Image Processing Institute"),
]

REFERENCES = [
    'J. Fridrich and M. Goljan, "Protection of digital images using self-embedding," in '
    'Proc. Symp. Content Security and Data Hiding in Digital Media, Newark, NJ, USA, May 1999.',
    'P. Zhou, X. Han, V. I. Morariu, and L. S. Davis, "Learning rich features for image '
    'manipulation detection," in Proc. IEEE/CVF Conf. Computer Vision and Pattern '
    'Recognition (CVPR), Salt Lake City, UT, USA, Jun. 2018.',
    'Y. Wu, W. AbdAlmageed, and P. Natarajan, "ManTra-Net: Manipulation tracing network '
    'for detection and localization of image forgeries with anomalous features," in Proc. '
    'IEEE/CVF Conf. Computer Vision and Pattern Recognition (CVPR), Long Beach, CA, USA, '
    'Jun. 2019.',
    'P. W. Wong and N. Memon, "Secret and public key image watermarking schemes for image '
    'authentication and ownership verification," IEEE Trans. Image Process., vol. 10, '
    'no. 10, pp. 1593-1601, Oct. 2001.',
    'C. Rey and J.-L. Dugelay, "A survey of watermarking algorithms for image '
    'authentication," EURASIP J. Appl. Signal Process., vol. 2002, no. 6, pp. 613-621, 2002.',
    'I. J. Cox, J. Kilian, F. T. Leighton, and T. Shamoon, "Secure spread spectrum '
    'watermarking for multimedia," IEEE Trans. Image Process., vol. 6, no. 12, '
    'pp. 1673-1687, Dec. 1997.',
    'M. Holliman and N. Memon, "Counterfeiting attacks on oblivious block-wise independent '
    'invisible watermarking schemes," IEEE Trans. Image Process., vol. 9, no. 3, '
    'pp. 432-441, Mar. 2000.',
    'C.-Y. Lin and S.-F. Chang, "Semi-fragile watermarking for authenticating JPEG visual '
    'content," in Proc. SPIE 3971, Security and Watermarking of Multimedia Contents II, '
    '2000, pp. 140-151.',
    'J. Fridrich, "Security of fragile authentication watermarks with localization," in '
    'Proc. SPIE 4675, Security and Watermarking of Multimedia Contents IV, San Jose, CA, '
    'USA, Jan. 2002, pp. 691-700.',
    'P.-L. Lin, C.-K. Hsieh, and P.-W. Huang, "A hierarchical digital watermarking method '
    'for image tamper detection and recovery," Pattern Recognit., vol. 38, no. 12, '
    'pp. 2519-2529, Dec. 2005.',
    'X. Zhang, S. Wang, Z. Qian, and G. Feng, "Reference sharing mechanism for watermark '
    'self-embedding," IEEE Trans. Image Process., vol. 20, no. 2, pp. 485-495, Feb. 2011.',
    'P. Korus and A. Dziech, "Efficient method for content reconstruction with '
    'self-embedding," IEEE Trans. Image Process., vol. 22, no. 3, pp. 1134-1147, Mar. 2013.',
    'A. Aminuddin and F. Ernawan, "AuSR1: Authentication and self-recovery using a new '
    'image inpainting technique with LSB shifting in fragile image watermarking," J. King '
    'Saud Univ. - Comput. Inf. Sci., 2022.',
    'A. Aminuddin and F. Ernawan, "AuSR2: Image watermarking technique for authentication '
    'and self-recovery with image texture preservation," Comput. Electr. Eng., vol. 102, '
    'art. 108207, 2022.',
    'A. Aminuddin and F. Ernawan, "AuSR3: A new block mapping technique for image '
    'authentication and self-recovery to avoid the tamper coincidence problem," J. King '
    'Saud Univ. - Comput. Inf. Sci., vol. 35, no. 9, art. 101755, 2023.',
    'A. Aminuddin, F. Ernawan, D. Nincarean, A. Amrullah, and D. Ariatmanto, "TCBR and '
    'TCBD: Evaluation metrics for tamper coincidence problem in fragile image '
    'watermarking," Eng. Sci. Technol. - Int. J., vol. 56, art. 101790, 2024.',
    'X. Zhang, R. Li, J. Yu, Y. Xu, W. Li, and J. Zhang, "EditGuard: Versatile image '
    'watermarking for tamper localization and copyright protection," in Proc. IEEE/CVF '
    'Conf. Computer Vision and Pattern Recognition (CVPR), 2024.',
    'Q. Wu, H. Li, M. Li, and M. Wang, "Multi-feature fragile image watermarking algorithm '
    'for tampering blind-detection and content self-recovery," Computers, Materials & '
    'Continua, vol. 86, no. 1, 2026.',
    'X. Zhang and S. Wang, "Fragile watermarking with error-free restoration capability," '
    'IEEE Trans. Multimedia, vol. 10, no. 8, pp. 1490-1499, Dec. 2008.',
    'National Institute of Standards and Technology, "Secure Hash Standard (SHS)," FIPS '
    'Publication 180-4, Aug. 2015.',
    'Z. Wang, A. C. Bovik, H. R. Sheikh, and E. P. Simoncelli, "Image quality assessment: '
    'From error visibility to structural similarity," IEEE Trans. Image Process., vol. 13, '
    'no. 4, pp. 600-612, Apr. 2004.',
    'University of Southern California, Signal and Image Processing Institute, "The '
    'USC-SIPI Image Database." [Online]. Available: https://sipi.usc.edu/database/',
    'Eastman Kodak Company, "Kodak Lossless True Color Image Suite." [Online]. Available: '
    'https://r0k.us/graphics/kodak/',
    'Coalition for Content Provenance and Authenticity, "C2PA Technical Specification." '
    '[Online]. Available: https://c2pa.org/specifications/',
    '"A recent survey of self-embedding fragile watermarking scheme for image '
    'authentication with recovery capability," EURASIP J. Image Video Process., 2019.',
    '"Security analysis of a self-embedding fragile image watermark scheme," '
    'arXiv:1812.11735, 2018.',
]


SHORT_FIG = {
    "1.1": "Passive detection against active self-embedding",
    "2.1": "The four tamper classes",
    "3.1": "Project schedule (Gantt chart)",
    "4.1": "The incremental SDLC model as applied",
    "5.1": "System architecture",
    "5.2": "Per-block payload layout at B = 8",
    "5.3": "Key-seeded block mapping",
    "5.4": "Data flow diagram, Level 0 (context)",
    "5.5": "Data flow diagram, Level 1",
    "5.6": "Data flow diagram, Level 2",
    "5.7": "Entity-relationship diagram",
    "5.8": "Use case diagram",
    "5.9": "Class diagram",
    "5.10": "Sequence diagram",
    "5.11": "Activity diagram",
    "5.12": "State machine diagram",
    "5.13": "Component diagram",
    "5.14": "Deployment diagram",
    "7.1": "Recoverability rate against tamper ratio",
    "7.2": "In-region and whole-image PSNR",
    "7.3": "Qualitative result under copy-paste splicing",
}

SHORT_TAB = {
    "1.1": "Summary of the surveyed literature",
    "2.1": "Tamper classes and tamper ratios",
    "3.1": "Measured size of the implementation",
    "3.2": "Basic COCOMO estimate",
    "3.3": "Risk register",
    "3.4": "Plan of work and status",
    "4.1": "Schema of the protected-image library",
    "4.2": "Software requirements",
    "4.3": "Hardware requirements",
    "5.1": "Per-block bit budget",
    "5.2": "Functional modules and responsibilities",
    "7.1": "Imperceptibility of watermarked images",
    "7.2": "Recoverability and in-region recovery quality",
    "7.3": "Null condition on unmodified images",
    "7.4": "Comparison with published schemes",
    "7.5": "Block-size ablation",
}


# --------------------------------------------------------------- docx helpers
def set_run(r, size=BODY, bold=False, italic=False, caps=False, name=FONT):
    r.font.name = name
    r.font.size = Pt(size)
    r.bold = bold
    r.italic = italic
    r._element.rPr.rFonts.set(qn("w:eastAsia"), name)
    if caps:
        r.text = r.text.upper()


def para(doc, text="", size=BODY, bold=False, italic=False, align=None,
         before=0, after=0, indent=0.0, spacing=1.5, keep=False, name=FONT):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = spacing
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.first_line_indent = Inches(indent)
    pf.keep_with_next = keep
    if align is not None:
        p.alignment = align
    if text:
        r = p.add_run(text)
        set_run(r, size, bold, italic, name=name)
    return p


def body_para(doc, text):
    return para(doc, text, align=WD_ALIGN_PARAGRAPH.JUSTIFY, after=5, indent=0.30)


def bullet(doc, text):
    p = doc.add_paragraph(style="List Bullet")
    pf = p.paragraph_format
    pf.line_spacing = 1.5
    pf.space_after = Pt(2)
    pf.left_indent = Inches(0.55)
    pf.first_line_indent = Inches(-0.25)
    p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    set_run(p.add_run(text))
    return p


def add_logo(doc, width=1.15, before=0, after=6):
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=before, after=after,
             spacing=1.0)
    p.add_run().add_picture(str(FIGS / "logo.png"), width=Inches(width))
    return p


def chapter_title(doc, num, title):
    para(doc, f"CHAPTER {num}", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=0, after=6, spacing=1.0, keep=True)
    para(doc, title.upper(), 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=0, after=12, spacing=1.0, keep=True)


def section_heading(doc, text):
    return para(doc, text.upper(), BODY, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                before=14, after=6, spacing=1.0, keep=True)


def sub_heading(doc, text):
    return para(doc, text, BODY, bold=True, align=WD_ALIGN_PARAGRAPH.LEFT,
                before=9, after=5, spacing=1.0, keep=True)


MAX_FIG_H = 3.00  # inches; keeps two illustrations per page as the format requires


def fig_width(fn, width):
    from PIL import Image
    w, h = Image.open(FIGS / fn).size
    if width * h / w > MAX_FIG_H:
        width = MAX_FIG_H * w / h
    return width


def add_figure(doc, key):
    fn, caption, width = FIGURES[key]
    width = fig_width(fn, width)
    p = para(doc, align=WD_ALIGN_PARAGRAPH.CENTER, before=6, after=3, spacing=1.0,
             keep=True)
    p.add_run().add_picture(str(FIGS / fn), width=Inches(width))
    para(doc, f"Fig. {key}: {caption}", BODY, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=0, after=9, spacing=1.0)


def shade(cell, hexcolor):
    el = OxmlElement("w:shd")
    el.set(qn("w:val"), "clear")
    el.set(qn("w:fill"), hexcolor)
    cell._tc.get_or_add_tcPr().append(el)


def add_table(doc, key, spec):
    caption, header, rows, widths = spec
    para(doc, f"Table {key}: {caption}", BODY, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=8, after=4, spacing=1.0, keep=True)
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    fs = 9.5 if len(rows) > 8 else (10 if len(header) > 3 else 11)
    for i, h in enumerate(header):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        set_run(p.add_run(h), fs, bold=True)
        shade(c, "D9D9D9")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            p = cells[i].paragraphs[0]
            p.alignment = (WD_ALIGN_PARAGRAPH.LEFT if len(str(v)) > 22
                           else WD_ALIGN_PARAGRAPH.CENTER)
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            set_run(p.add_run(str(v)), fs)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Inches(w)
    para(doc, "", 6, after=4, spacing=1.0)
    return t


def equation(doc, text):
    para(doc, text, BODY, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         before=5, after=6, spacing=1.0)


def dotted_row(doc, left, right, indent=0.0, bold=False, before=0, after=4):
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.line_spacing = 1.0
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.left_indent = Inches(indent)
    pf.tab_stops.add_tab_stop(Inches(TEXT_W), WD_TAB_ALIGNMENT.RIGHT, 1)  # 1 = DOTS
    set_run(p.add_run(left), BODY, bold=bold)
    set_run(p.add_run("\t" + str(right)), BODY, bold=bold)
    return p


def field(p, instr):
    r = p.add_run()
    fc = OxmlElement("w:fldChar"); fc.set(qn("w:fldCharType"), "begin")
    it = OxmlElement("w:instrText"); it.set(qn("xml:space"), "preserve"); it.text = instr
    fs = OxmlElement("w:fldChar"); fs.set(qn("w:fldCharType"), "separate")
    tx = OxmlElement("w:t"); tx.text = "1"
    fe = OxmlElement("w:fldChar"); fe.set(qn("w:fldCharType"), "end")
    r._r.append(fc); r._r.append(it); r._r.append(fs); r._r.append(tx); r._r.append(fe)
    return r


def page_numbering(section, fmt, start=None):
    sectPr = section._sectPr
    pg = OxmlElement("w:pgNumType")
    pg.set(qn("w:fmt"), fmt)
    if start is not None:
        pg.set(qn("w:start"), str(start))
    sectPr.append(pg)


def make_footer(section, numbered=True):
    section.footer.is_linked_to_previous = False
    f = section.footer
    for p in list(f.paragraphs)[1:]:
        p._element.getparent().remove(p._element)
    p1 = f.paragraphs[0]
    p1.text = ""
    p1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p1.paragraph_format.line_spacing = 1.0
    p1.paragraph_format.space_after = Pt(0)
    set_run(p1.add_run("ADYPSOE, Department of Computer Engineering 2026-27"), 10)
    if numbered:
        p2 = f.add_paragraph()
        p2.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p2.paragraph_format.line_spacing = 1.0
        p2.paragraph_format.space_before = Pt(0)
        field(p2, " PAGE ")
        for r in p2.runs:
            set_run(r, 10)


def new_section(doc, fmt, start=None, numbered=True, footer=True):
    s = doc.add_section(WD_SECTION.NEW_PAGE)
    page_setup(s)
    page_numbering(s, fmt, start)
    if footer:
        make_footer(s, numbered)
    else:
        s.footer.is_linked_to_previous = False
        s.footer.paragraphs[0].text = ""
    return s


def page_setup(s):
    s.page_height = Mm(297)
    s.page_width = Mm(210)
    s.top_margin = Mm(23.4)
    s.bottom_margin = Mm(32)
    s.left_margin = Mm(37)
    s.right_margin = Mm(23.4)
    s.footer_distance = Mm(14)


# ------------------------------------------------------------- content parser
MARK = re.compile(r"^\[\[(FIG|TABLE) ([0-9.]+)\]\]$")


def render_chapter(doc, path, tables, index, chapter_num):
    """index collects (kind, key, label) in document order for the front matter."""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        m = MARK.match(line)
        if m:
            kind, key = m.group(1), m.group(2)
            if kind == "FIG":
                add_figure(doc, key)
                index.append(("fig", key, FIGURES[key][1]))
            else:
                add_table(doc, key, tables[key])
                index.append(("tab", key, tables[key][0]))
            continue
        if line.startswith("@@SEC "):
            txt = line[6:].strip()
            section_heading(doc, txt)
            index.append(("sec", txt.split(" ", 1)[0], txt))
            continue
        if line.startswith("@@SUB "):
            txt = line[6:].strip()
            sub_heading(doc, txt)
            index.append(("sub", txt.split(" ", 1)[0], txt))
            continue
        if line.startswith("@@EQ "):
            equation(doc, line[5:].strip())
            continue
        if line.startswith("* "):
            bullet(doc, line[2:].strip())
            continue
        body_para(doc, line)


# ------------------------------------------------------------------ front matter
def cover_page(doc):
    for _ in range(4):
        para(doc, "", spacing=1.0, after=0)
    para(doc, "A PRELIMINARY REPORT ON", 12, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=18)
    para(doc, TITLE, 16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=6)
    para(doc, SUBTITLE, 12, italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=18)
    for t in ["SUBMITTED TO THE SAVITRIBAI PHULE PUNE UNIVERSITY, PUNE",
              "IN THE PARTIAL FULFILLMENT OF THE REQUIREMENTS",
              "FOR THE AWARD OF THE DEGREE"]:
        para(doc, t, 12, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)
    para(doc, "OF", 12, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, before=10, after=10)
    para(doc, "BACHELOR OF ENGINEERING", 16, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)
    para(doc, "(COMPUTER ENGINEERING)", 16, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=18)
    para(doc, "SUBMITTED BY", 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, after=10)
    for name, seat in STUDENTS:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(4)
        set_run(p.add_run(f"{name}          Exam No : {seat}"), 12, bold=True)
    para(doc, "Under the Guidance of", 12, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, before=16, after=4)
    para(doc, GUIDE, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=8)
    add_logo(doc, width=1.25, after=14)
    para(doc, DEPT, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)
    para(doc, COLLEGE, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=0)
    para(doc, ADDRESS, 12, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=10)
    para(doc, UNIV, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)
    para(doc, YEAR, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)


def certificate_page(doc):
    add_logo(doc, width=1.25, before=6, after=10)
    para(doc, COLLEGE, 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=2)
    para(doc, DEPT, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=24)
    para(doc, "CERTIFICATE", 16, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=22)
    para(doc, "This is to certify that the Project Report entitled", 12,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=10)
    para(doc, f'"{TITLE}"', 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=16)
    para(doc, "Submitted by", 12, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=8)
    for name, seat in STUDENTS:
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.paragraph_format.line_spacing = 1.0
        p.paragraph_format.space_after = Pt(3)
        set_run(p.add_run(f"{name}          Exam No : {seat}"), 12, bold=True)
    para(doc,
         "are bonafide students of this institute and the work has been carried out by "
         f"them under the supervision of {GUIDE} and it is approved for the partial "
         "fulfillment of the requirement of Savitribai Phule Pune University, for the "
         "award of the degree of Bachelor of Engineering in Computer Engineering.",
         12, align=WD_ALIGN_PARAGRAPH.JUSTIFY, spacing=1.5, before=16, after=40)
    t = doc.add_table(rows=3, cols=2)
    t.autofit = False
    pairs = [(f"({GUIDE})", f"({HOD})"), ("Guide", "H.O.D"),
             ("Department of Computer Engineering", "Department of Computer Engineering")]
    for i, (a, b) in enumerate(pairs):
        for j, v in enumerate((a, b)):
            c = t.rows[i].cells[j]
            c.width = Inches(2.92)
            p = c.paragraphs[0]
            p.paragraph_format.line_spacing = 1.0
            p.paragraph_format.space_after = Pt(0)
            set_run(p.add_run(v), 12)
    para(doc, "", spacing=1.0, after=30)
    t2 = doc.add_table(rows=1, cols=2)
    t2.autofit = False
    for j, v in enumerate(("Signature of Internal Examiner:",
                           "Signature of External Examiner:")):
        c = t2.rows[0].cells[j]
        c.width = Inches(2.92)
        p = c.paragraphs[0]
        p.paragraph_format.line_spacing = 1.0
        set_run(p.add_run(v), 12)
    para(doc, "", spacing=1.0, after=24)
    para(doc, PRINCIPAL, 12, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=0)
    para(doc, "Principal", 12, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=0)
    para(doc, f"{COLLEGE}, Lohegaon, Pune-412105", 12,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=18)
    p = doc.add_paragraph()
    p.paragraph_format.line_spacing = 1.0
    p.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
    set_run(p.add_run("Place : Pune\tDate :"), 12)


def acknowledgement_page(doc):
    para(doc, "ACKNOWLEDGEMENT", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, after=20)
    for t in [
        "It gives us great pleasure in presenting the preliminary project report on "
        f'"{TITLE.title()}".',
        f"We would like to take this opportunity to thank our Internal Guide {GUIDE} for "
        "giving us all the help and guidance we needed. We are really grateful for the "
        "kind support, and the valuable suggestions that shaped both the design of the "
        "scheme and the way its results are reported.",
        f"We are also grateful to {HOD}, Head of the Computer Engineering Department, "
        f"ADYPSOE, Lohegaon, Pune, and to our Project Co-ordinator {COORD}, for their "
        "indispensable support, suggestions and motivation during the entire course of "
        "the project.",
        f"We would also be grateful to our Principal {PRINCIPAL}, who encouraged us and "
        "created a healthy environment for all of us to learn in the best possible way.",
        "We also thank all the staff members of our college and the technicians for their "
        "help in making this project a successful one.",
    ]:
        body_para(doc, t)
    para(doc, "", after=24)
    for name, _ in STUDENTS:
        para(doc, name, 12, bold=True, align=WD_ALIGN_PARAGRAPH.RIGHT, spacing=1.0,
             after=2)


def abstract_page(doc):
    para(doc, "ABSTRACT", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=20)
    for line in (HERE / "abstract.txt").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        if line.lower().startswith("keywords"):
            p = doc.add_paragraph()
            p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            p.paragraph_format.line_spacing = 1.5
            p.paragraph_format.space_before = Pt(10)
            head, rest = line.split(":", 1)
            set_run(p.add_run(head + ":"), 12, bold=True)
            set_run(p.add_run(rest), 12)
        else:
            body_para(doc, line)


def list_page(doc, title, rows, widths, header=None):
    """Plain tab-aligned columns, as the template prints them -- no borders."""
    para(doc, title, 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=16)
    stops = []
    x = 0.45
    for w in widths[:-1]:
        stops.append(x)
        x += w
    right = sum(widths) + 0.45

    def row(vals, bold=False, caps=False):
        q = doc.add_paragraph()
        qf = q.paragraph_format
        qf.line_spacing = 1.0
        qf.space_after = Pt(6)
        for st in stops[1:]:
            qf.tab_stops.add_tab_stop(Inches(st), WD_TAB_ALIGNMENT.LEFT)
        if len(vals) > 2:
            qf.tab_stops.add_tab_stop(Inches(right), WD_TAB_ALIGNMENT.RIGHT)
        qf.left_indent = Inches(stops[0])
        qf.first_line_indent = Inches(0)
        text = "\t".join(str(v) for v in vals[1:])
        set_run(q.add_run(str(vals[0]) + "\t" + text), 11.5, bold=bold)
        return q

    if header:
        row(header, bold=True)
        para(doc, "", 6, after=4, spacing=1.0)
    for r in rows:
        row(r)


# ------------------------------------------------------------------- the build
def build(pages=None):
    tables = __import__("tables").build()
    doc = Document()
    st = doc.styles["Normal"]
    st.font.name = FONT
    st.font.size = Pt(BODY)
    st.element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

    s0 = doc.sections[0]
    page_setup(s0)
    s0.footer.paragraphs[0].text = ""
    cover_page(doc)
    doc.add_page_break()
    certificate_page(doc)

    # ---- front matter, small roman
    new_section(doc, "lowerRoman", start=1)
    acknowledgement_page(doc)
    doc.add_page_break()
    abstract_page(doc)
    doc.add_page_break()

    toc_anchor = len(doc.paragraphs)
    para(doc, "TABLE OF CONTENTS", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, after=16)
    P = pages or {}

    def pg(key):
        return P.get(key, "")

    for label, key in [("LIST OF ABBREVIATIONS", "front:abbr"),
                       ("LIST OF FIGURES", "front:figs"),
                       ("LIST OF TABLES", "front:tabs")]:
        q = doc.add_paragraph()
        qf = q.paragraph_format
        qf.line_spacing = 1.0
        qf.space_after = Pt(2)
        qf.left_indent = Inches(0.6)
        qf.tab_stops.add_tab_stop(Inches(4.6), WD_TAB_ALIGNMENT.RIGHT)
        set_run(q.add_run(label + "\t" + str(pg(key))), BODY)
    para(doc, "", 6, after=12, spacing=1.0)

    t = doc.add_table(rows=1, cols=3)
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    t.autofit = False
    widths = [0.95, 4.05, 0.85]
    for i, h in enumerate(["Sr.No.", "Title of Chapter", "Page No."]):
        c = t.rows[0].cells[i]
        q = c.paragraphs[0]
        q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        q.paragraph_format.line_spacing = 1.0
        q.paragraph_format.space_after = Pt(1)
        q.paragraph_format.space_before = Pt(1)
        set_run(q.add_run(h), BODY, bold=True)
        shade(c, "D9D9D9")
    trPr = t.rows[0]._tr.get_or_add_trPr()
    el = OxmlElement("w:tblHeader")
    el.set(qn("w:val"), "true")
    trPr.append(el)

    def toc_row(sr, title, page, bold=False, indent=0.0):
        cells = t.add_row().cells
        for i, v in enumerate((sr, title, page)):
            q = cells[i].paragraphs[0]
            q.paragraph_format.line_spacing = 1.0
            q.paragraph_format.space_after = Pt(1)
            q.paragraph_format.space_before = Pt(1)
            if i == 0:
                q.alignment = WD_ALIGN_PARAGRAPH.CENTER
                q.paragraph_format.left_indent = Inches(indent)
            elif i == 2:
                q.alignment = WD_ALIGN_PARAGRAPH.CENTER
            set_run(q.add_run(str(v)), 11, bold=bold)

    for kind, key, label in TOC_ROWS:
        if kind == "chapter":
            toc_row(f"{int(key):02d}", label.title(), pg(f"ch:{key}"), bold=True)
        else:
            num, _, name = label.partition(" ")
            toc_row(num, name, pg(f"sec:{key}"), indent=0.12 if kind == "sec" else 0.26)
    toc_row("", "References", pg("back:ref"), bold=True)
    toc_row("", "Appendix A: Feasibility Assessment, Satisfiability Analysis and "
                "Complexity Classification", pg("back:appA"), bold=True)
    toc_row("", "Appendix B: Details of the Papers Referred", pg("back:appB"), bold=True)
    toc_row("", "Appendix C: Plagiarism Report", pg("back:appC"), bold=True)
    for r in t.rows:
        for i, w in enumerate(widths):
            r.cells[i].width = Inches(w)

    doc.add_page_break()
    list_page(doc, "LIST OF ABBREVIATIONS",
              [[a, b] for a, b in ABBREVIATIONS], [1.25, 3.95],
              ["Abbreviation", "Illustration"])
    doc.add_page_break()
    order = sorted(FIG_ORDER, key=lambda k: [int(x) for x in k.split(".")])
    list_page(doc, "LIST OF FIGURES",
              [[k, SHORT_FIG[k], pg(f"fig:{k}")] for k in order],
              [0.95, 3.95, 0.45], ["Figure", "Illustration", "Page No."])
    doc.add_page_break()
    order = sorted(TAB_ORDER, key=lambda k: [int(x) for x in k.split(".")])
    list_page(doc, "LIST OF TABLES",
              [[k, SHORT_TAB.get(k, tables[k][0]), pg(f"tab:{k}")] for k in order],
              [0.95, 3.95, 0.45], ["Table", "Illustration", "Page No."])

    # ---- body, arabic from 1
    new_section(doc, "decimal", start=1)
    index = []
    for num, title, fn in CHAPTERS:
        if num > 1:
            doc.add_page_break()
        chapter_title(doc, num, title)
        index.append(("chapter", str(num), title))
        render_chapter(doc, HERE / fn, tables, index, num)

    doc.add_page_break()
    para(doc, "REFERENCES", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=18)
    for i, ref in enumerate(REFERENCES, 1):
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.line_spacing = 1.5
        pf.space_after = Pt(8)
        pf.left_indent = Inches(0.42)
        pf.first_line_indent = Inches(-0.42)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_run(p.add_run(f"[{i}]\t"), BODY)
        set_run(p.add_run(ref), BODY)

    doc.add_page_break()
    para(doc, "APPENDIX A", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=6)
    para(doc, "FEASIBILITY ASSESSMENT, SATISFIABILITY ANALYSIS AND COMPLEXITY "
              "CLASSIFICATION", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, after=18)
    render_chapter(doc, HERE / "appendixA.txt", tables, [], 0)

    doc.add_page_break()
    para(doc, "APPENDIX B", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=6)
    para(doc, "DETAILS OF THE PAPERS REFERRED", 14, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0, after=18)
    for block in (HERE / "appendixB.txt").read_text(encoding="utf-8").split("\n\n"):
        lines = [l.strip() for l in block.strip().splitlines() if l.strip()]
        if not lines:
            continue
        p = doc.add_paragraph()
        pf = p.paragraph_format
        pf.line_spacing = 1.5
        pf.space_after = Pt(2)
        pf.left_indent = Inches(0.42)
        pf.first_line_indent = Inches(-0.42)
        p.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        set_run(p.add_run(lines[0]), BODY)
        for extra in lines[1:]:
            q = doc.add_paragraph()
            qf = q.paragraph_format
            qf.line_spacing = 1.5
            qf.space_after = Pt(10)
            qf.left_indent = Inches(0.42)
            q.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
            head, rest = (extra.split(":", 1) + [""])[:2] if extra.startswith("Summary") \
                else ("", extra)
            if head:
                set_run(q.add_run(head + ":"), BODY, italic=True)
                set_run(q.add_run(rest), BODY)
            else:
                set_run(q.add_run(extra), BODY)

    doc.add_page_break()
    para(doc, "APPENDIX C", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, spacing=1.0,
         after=6)
    para(doc, "PLAGIARISM REPORT", 14, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER,
         spacing=1.0, after=18)
    body_para(doc,
              "The plagiarism check report generated by the institute's similarity "
              "checking service is to be attached at this point, as required by clause 19 "
              "of the departmental report format. The report covers Chapters 1 to 7 and "
              "Appendices A and B of this document; the cover page, certificate, "
              "acknowledgement, table of contents, lists and references are excluded from "
              "the check in line with the usual convention.")
    para(doc, "[ATTACH THE PLAGIARISM CHECK REPORT HERE]", 12, bold=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, before=36)

    OUT.mkdir(exist_ok=True)
    out = OUT / "Project_Report.docx"
    doc.save(out)
    return out, index


# TOC_ROWS / FIG_ORDER / TAB_ORDER are discovered from the chapter files so the front
# matter can never disagree with the body.
def discover():
    rows, figs, tabs = [], [], []
    for num, title, fn in CHAPTERS:
        rows.append(("chapter", str(num), title))
        for raw in (HERE / fn).read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            m = MARK.match(line)
            if m:
                (figs if m.group(1) == "FIG" else tabs).append(m.group(2))
            elif line.startswith("@@SEC "):
                t = line[6:].strip()
                rows.append(("sec", t.split(" ", 1)[0], t))
            elif line.startswith("@@SUB "):
                t = line[6:].strip()
                rows.append(("sub", t.split(" ", 1)[0], t))
    return rows, figs, tabs


TOC_ROWS, FIG_ORDER, TAB_ORDER = discover()


def to_pdf(docx_path):
    subprocess.run([SOFFICE, "--headless", "--convert-to", "pdf", "--outdir",
                    str(docx_path.parent), str(docx_path)],
                   check=True, capture_output=True)
    return docx_path.with_suffix(".pdf")


def measure(pdf_path):
    import pymupdf
    d = pymupdf.open(pdf_path)
    # find where the body section restarts at page 1: the first page whose footer
    # shows "1" after the front matter
    pages = {}
    texts = [p.get_text() for p in d]
    # the table of contents also names every chapter, so the body search starts
    # after the last front-matter page
    lot = max(i for i, t in enumerate(texts) if "LIST OF TABLES" in t)
    body_start = None
    for i in range(lot + 1, len(texts)):
        if "CHAPTER 1" in texts[i] and "INTRODUCTION" in texts[i]:
            body_start = i
            break
    assert body_start is not None, "could not find chapter 1"

    def rec(key, i, front=False):
        if key in pages:
            return
        pages[key] = (ROMAN[i - front_start + 1] if front else i - body_start + 1)

    front_start = None
    for i, t in enumerate(texts):
        if "ACKNOWLEDGEMENT" in t:
            front_start = i
            break
    ROMAN = {n: r for n, r in zip(range(1, 40), [
        "i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii",
        "xiv", "xv", "xvi", "xvii", "xviii", "xix", "xx", "xxi", "xxii", "xxiii", "xxiv",
        "xxv", "xxvi", "xxvii", "xxviii", "xxix", "xxx", "xxxi", "xxxii", "xxxiii",
        "xxxiv", "xxxv", "xxxvi", "xxxvii", "xxxviii", "xxxix"])}

    for name, needle in [("front:ack", "ACKNOWLEDGEMENT"), ("front:abs", "ABSTRACT"),
                         ("front:abbr", "LIST OF ABBREVIATIONS"),
                         ("front:figs", "LIST OF FIGURES"),
                         ("front:tabs", "LIST OF TABLES")]:
        hits = [i for i in range(front_start, body_start) if needle in texts[i]]
        if hits:
            # the contents page names every one of these, so take the page that
            # actually carries the section, which is the last hit
            i = hits[0] if name in ("front:ack", "front:abs") else hits[-1]
            pages[name] = ROMAN[i - front_start + 1]

    for num, title, _ in CHAPTERS:
        for i in range(body_start, len(texts)):
            if f"CHAPTER {num}" in texts[i] and title[:18] in texts[i]:
                pages[f"ch:{num}"] = i - body_start + 1
                break
    for kind, key, label in TOC_ROWS:
        if kind == "chapter":
            continue
        needle = label.upper()
        for i in range(body_start, len(texts)):
            if needle in texts[i].upper():
                pages[f"sec:{key}"] = i - body_start + 1
                break
    for k in FIG_ORDER:
        for i in range(body_start, len(texts)):
            if f"Fig. {k}:" in texts[i]:
                pages[f"fig:{k}"] = i - body_start + 1
                break
    for k in TAB_ORDER:
        for i in range(body_start, len(texts)):
            if f"Table {k}:" in texts[i]:
                pages[f"tab:{k}"] = i - body_start + 1
                break
    for name, needle in [("back:ref", "REFERENCES"), ("back:appA", "APPENDIX A"),
                         ("back:appB", "APPENDIX B"), ("back:appC", "APPENDIX C")]:
        for i in range(body_start, len(texts)):
            if needle in texts[i]:
                pages[name] = i - body_start + 1
                break
    d.close()
    return pages, len(texts), body_start


if __name__ == "__main__":
    print(f"{len(TOC_ROWS)} toc rows, {len(FIG_ORDER)} figures, {len(TAB_ORDER)} tables")
    out, _ = build()
    print("pass 1:", out)
    pdf = to_pdf(out)
    pages, n, body_start = measure(pdf)
    print(f"rendered {n} pages, body starts at pdf page {body_start + 1}, "
          f"body length {n - body_start}")
    out, _ = build(pages)
    print("pass 2:", out)
    pdf = to_pdf(out)
    pages2, n2, bs2 = measure(pdf)
    drift = {k: (pages[k], pages2[k]) for k in pages if pages.get(k) != pages2.get(k)}
    print("drift after pass 2:", drift or "none")
