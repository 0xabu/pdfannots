#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import io
import pathlib
import sys
import tempfile
from multiprocessing import Pool, cpu_count

import PyPDF2 as PyPDF2
import click
import pdfminer.pdftypes as pdftypes
import pdfminer.settings
from fpdf import FPDF
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams, LTAnno, LTContainer, LTText, LTTextBox
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.pdfinterp import PDFPageInterpreter, PDFResourceManager
from pdfminer.pdfpage import PDFPage
from pdfminer.pdfparser import PDFParser
from pdfminer.psparser import PSLiteral, PSLiteralTable
from tqdm import tqdm

pdfminer.settings.STRICT = False

SUBSTITUTIONS = {
    u'ﬀ': 'ff',
    u'ﬁ': 'fi',
    u'ﬂ': 'fl',
    u'’': "'",
}

ANNOT_SUBTYPES = set(['Text', 'Highlight', 'Squiggly', 'StrikeOut', 'Underline'])

DEBUG_BOXHIT = False

OUTDIR = ""


def box_hit(item, box):
    (x0, y0, x1, y1) = box
    assert item.x0 <= item.x1 and item.y0 <= item.y1
    assert x0 <= x1 and y0 <= y1

    # does most of the item area overlap the box?
    # http://math.stackexchange.com/questions/99565/simplest-way-to-calculate-the-intersect-area-of-two-rectangles
    x_overlap = max(0, min(item.x1, x1) - max(item.x0, x0))
    y_overlap = max(0, min(item.y1, y1) - max(item.y0, y0))
    overlap_area = x_overlap * y_overlap
    item_area = (item.x1 - item.x0) * (item.y1 - item.y0)
    assert overlap_area <= item_area

    if DEBUG_BOXHIT and overlap_area != 0:
        print("'%s' %f-%f,%f-%f in %f-%f,%f-%f %2.0f%%" %
              (item.get_text(), item.x0, item.x1, item.y0, item.y1, x0, x1, y0, y1,
               100 * overlap_area / item_area))

    if item_area == 0:
        return False
    else:
        return overlap_area >= 0.5 * item_area


class RectExtractor(TextConverter):
    def __init__(self, rsrcmgr, codec='utf-8', page_num=1):
        dummy = io.StringIO()
        TextConverter.__init__(self, rsrcmgr, outfp=dummy, codec=codec, pageno=page_num, laparams=LAParams())
        self.annots = []

    def set_coords(self, annots):
        self.annots = [a for a in annots if a.boxes]
        self._last_hit = []

    def test_boxes(self, item):
        self._last_hit = []
        for a in self.annots:
            if any([box_hit(item, b) for b in a.boxes]):
                self._last_hit.append(a)
        return self._last_hit

    def receive_layout(self, lt_page):
        def render(item):
            if isinstance(item, LTContainer):
                for child in item:
                    render(child)
            elif isinstance(item, LTAnno):
                # this catches whitespace
                for a in self._last_hit:
                    a.capture(item.get_text())
            elif isinstance(item, LTText):
                for a in self.test_boxes(item):
                    a.capture(item.get_text())
            if isinstance(item, LTTextBox):
                for a in self.test_boxes(item):
                    a.capture('\n')

        render(lt_page)


class Annotation:
    def __init__(self, page_num, tag_name, coords=None, rect=None, contents=None):
        self.page_num = page_num
        self.tag_name = tag_name
        if contents == '':
            self.contents = None
        else:
            self.contents = contents
        self.rect = rect
        self.text = ''

        if coords is None:
            self.boxes = None
        else:
            assert (len(coords) % 8 == 0)
            self.boxes = []
            while coords:
                (x0, y0, x1, y1, x2, y2, x3, y3) = coords[:8]
                coords = coords[8:]
                x_coords = [x0, x1, x2, x3]
                y_coords = [y0, y1, y2, y3]
                box = (min(x_coords), min(y_coords), max(x_coords), max(y_coords))
                self.boxes.append(box)

    def capture(self, text):
        if text == '\n':
            # kludge for latex: elide hyphens, join lines
            if self.text.endswith('-'):
                self.text = self.text[:-1]
            else:
                self.text += ' '
        else:
            self.text += text

    def get_text(self):
        if self.text:
            # replace tex ligatures (and other common odd characters)
            return ''.join([SUBSTITUTIONS.get(c, c) for c in self.text.strip()])
        else:
            return None

    def get_start_pos(self):
        if self.rect:
            (x0, y0, x1, y1) = self.rect
        elif self.boxes:
            (x0, y0, x1, y1) = self.boxes[0]
        else:
            return None
        return min(x0, x1), max(y0, y1)  # assume left-to-right top-to-bottom text :)


def get_annots(pdf_annots, page_num):
    annots = []
    for pa in pdf_annots:
        subtype = pa.get('Subtype')
        if subtype is not None and subtype.name not in ANNOT_SUBTYPES:
            continue

        contents = pa.get('Contents')
        if contents is not None:
            contents = str(contents, 'utf-8')  # 'utf-8'  , iso8859-15
            contents = contents.replace('\r\n', '\n').replace('\r', '\n')
        a = Annotation(page_num, subtype.name.lower(), pa.get('QuadPoints'), pa.get('Rect'), contents)
        annots.append(a)

    return annots


def normalise_to_box(pos, box):
    (x, y) = pos
    (x0, y0, x1, y1) = box
    if x < x0:
        x = x0
    elif x > x1:
        x = x1
    if y < y0:
        y = y0
    elif y > y1:
        y = y1
    return x, y


def nearest_outline(outlines, page_num, media_box, pos):
    (x, y) = normalise_to_box(pos, media_box)
    prev = None
    for o in outlines:
        if o.page_num < page_num:
            prev = o
        elif o.page_num > page_num:
            return prev
        else:
            # XXX: assume two-column left-to-right top-to-bottom documents
            (o_x, o_y) = normalise_to_box((o.x, o.y), media_box)
            (x0, y0, x1, y1) = media_box
            colwidth = (x1 - x0) / 2
            outline_col = (o_x - x0) // colwidth
            pos_col = (x - x0) // colwidth
            if outline_col > pos_col or (outline_col == pos_col and o.y < y):
                return prev
            else:
                prev = o
    return prev


def prettify(text):
    # re.sub(r"\s\s+", " ", text)
    # return text
    return " ".join(text.split())


def structure_extracts(annots, outlines, media_boxes):
    def format_paging(annot):
        apos = annot.get_start_pos()
        if apos:
            o = nearest_outline(outlines, annot.page_num, media_boxes[annot.page_num], apos)
            if o:
                return o.title, annot.page_num + 1
        return "- Missing chapter name -", annot.page_num + 1

    def format_text(annot):
        if annot.boxes:
            if annot.get_text():
                return prettify(annot.get_text())
            else:
                return "(XXX: missing text!)"
        else:
            return ''

    nits = [a for a in annots if a.tag_name in ['squiggly', 'strikeout', 'underline']]
    comments = [a for a in annots if a.tag_name in ['highlight', 'text'] and a.contents]
    highlights = [a for a in annots if a.tag_name == 'highlight' and a.contents is None]

    annot_list = [(highlights, "Highlights"), (comments, "Comments"), (nits, "Nits"), ]

    annot_dic = {}
    for annot in annot_list:
        annot_type = annot[0]
        annot_name = annot[1]
        for t in annot_type:
            title, page = format_paging(t)
            text = format_text(t)

            try:
                annot_dic[title][page][annot_name]
            except KeyError:
                annot_dic.setdefault(title, {})
                annot_dic[title].setdefault(page, {})
                annot_dic[title][page].setdefault(annot_name, [])
            finally:
                annot_dic[title][page][annot_name].append(text)

    return annot_dic


def resolve_dest(doc, dest):
    if isinstance(dest, bytes):
        dest = pdftypes.resolve1(doc.get_dest(dest))
    elif isinstance(dest, PSLiteral):
        dest = pdftypes.resolve1(doc.get_dest(dest.name))
    if isinstance(dest, dict):
        dest = dest['D']
    return dest


class Outline:
    def __init__(self, title, dest, page_num, x, y):
        self.title = title
        self.dest = dest
        self.page_num = page_num
        self.x = x
        self.y = y


def get_outlines(doc, pages_dict):
    result = []
    for (level, title, dest_name, action_ref, _) in doc.get_outlines():
        if dest_name is None and action_ref:
            action = action_ref.resolve()
            if isinstance(action, dict):
                subtype = action.get('S')
                if subtype is PSLiteralTable.intern('GoTo'):
                    dest_name = action.get('D')
        if dest_name is None:
            continue
        dest = resolve_dest(doc, dest_name)
        page_num = pages_dict[dest[0].objid]
        (_, _, target_x, target_y, _) = dest
        result.append(Outline(title, dest_name, page_num, target_x, target_y))
    return result


class PDF(FPDF):
    def _page_setup(self):
        self.set_margins(left=20, top=15, right=20)
        # self.set_title(title)
        # self.set_author('Jules Verne')

    def _chapter_title(self, title):
        self.ln()
        self.set_font('Arial', '', 22)
        self.cell(w=0, h=6, txt=str(title), border=0, ln=0, align='L', fill=0, link="")
        self.ln(12)  # Line break

    def _chapter_page(self, page_num):
        self.set_font('Arial', '', 19)
        self.cell(w=0, h=6, txt="Page: " + str(page_num), border=0, ln=0, align='L', fill=0, link="")
        self.ln(9)

    def _chapter_body(self, annotations):
        # Times 12
        self.set_font('Arial', 'U', 17)
        for key, annot in annotations.items():
            self.cell(w=0, h=6, txt=str(key), border=0, ln=0, align='L', fill=0, link="")
            # Line break
            self.ln(7)
            self.set_font('Times', '', 14)
            for a in annot:
                # Output justified text
                self.multi_cell(0, 5, a)
                # Line break
                self.ln(2)

    def print_chapter(self, title, page_num, page_content):
        self.add_page()  # TODO: transfer to wider scope
        self._page_setup()

        self._chapter_title(title)
        self._chapter_page(page_num)
        self._chapter_body(page_content)


def create_cover(cover_doner, body_donor, output_path):
    with open(cover_doner, 'rb') as pdf1File, open(body_donor, 'rb') as pdf2File:
        pdf1Reader = PyPDF2.PdfFileReader(pdf1File)
        pdf2Reader = PyPDF2.PdfFileReader(pdf2File)
        pdfWriter = PyPDF2.PdfFileWriter()

        # get cover = 1st page from donor
        pageObj = pdf1Reader.getPage(0)
        pdfWriter.addPage(pageObj)

        for pageNum in range(pdf2Reader.numPages):
            pageObj = pdf2Reader.getPage(pageNum)
            pdfWriter.addPage(pageObj)

        with open(output_path, 'wb') as pdfOutputFile:
            pdfWriter.write(pdfOutputFile)


def extract_annots(fh):
    rsrcmgr = PDFResourceManager()
    device = RectExtractor(rsrcmgr)
    interpreter = PDFPageInterpreter(rsrcmgr, device)

    with open(fh, 'rb') as pdf_file:
        parser = PDFParser(pdf_file)
        doc = PDFDocument(parser)

        pages_dict = {}
        media_boxes = {}

        all_annots = []

        tqdm_desc = fh.ljust(25)[:25]  # make string exactly 25 chars long
        for (page_num, page) in tqdm(enumerate(PDFPage.create_pages(doc)), desc=tqdm_desc):
            pages_dict[page.pageid] = page_num
            media_boxes[page_num] = page.mediabox
            if page.annots is None or page.annots is []:
                continue

            # emit progress indicator
            sys.stderr.write((" " if page_num > 0 else "") + "%d" % (page_num + 1))
            sys.stderr.flush()

            pdf_annots = [ar.resolve() for ar in pdftypes.resolve1(page.annots)]
            page_annots = get_annots(pdf_annots, page_num)
            device.set_coords(page_annots)
            interpreter.process_page(page)
            all_annots.extend(page_annots)

        outlines = []
        try:
            outlines = get_outlines(doc, pages_dict)
        except PDFNoOutlines:
            sys.stderr.write("Document doesn't include outlines (\"bookmarks\")\n")
        except:
            e = sys.exc_info()[0]
            sys.stderr.write("Warning: failed to retrieve outlines: %s\n" % e)

    device.close()

    # pretty_print(all_annots, outlines, media_boxes)
    extract_dic = structure_extracts(all_annots, outlines, media_boxes)

    pdf = PDF()

    for key_1, chapter in extract_dic.items():
        for key_2, page_content in chapter.items():
            pdf.print_chapter(title=key_1, page_num=key_2, page_content=page_content)

    # constructing output file path
    with tempfile.NamedTemporaryFile(suffix='.pdf') as tmp:
        tmp_path = tmp.name
        pdf.output(tmp_path, 'F')
        # copy cover from source pdf in outputpath
        p = pathlib.Path(fh)
        out_fname = pathlib.Path(p.stem + ".sum" + p.suffix)
        out_dir = pathlib.Path(OUTDIR)
        output_path = pathlib.Path.joinpath(out_dir, out_fname)
        create_cover(cover_doner=fh, body_donor=tmp_path, output_path=output_path)


@click.command()
@click.option('--outdir', default="", help='Specify output directory')
@click.argument('files', nargs=-1)
def main(outdir, files):
    # ugly hack to work around maps arg limit
    global OUTDIR
    OUTDIR = outdir

    if not files:
        sys.stderr.write("Usage: FILE_1.PDF FILE_2.PDF ...")
        sys.exit(1)
    else:
        for f in files:
            if not f.lower().endswith(".pdf"):
                sys.stderr.write("Wrong file extension: " + f)
                sys.exit(1)

        files = set(files)  # make sure all files are unique

        if outdir:  # create target dir if not existing
            pathlib.Path(outdir).mkdir(parents=True, exist_ok=True)
        p = Pool(processes=cpu_count())  # does processes default to this value anyway?
        p.map(extract_annots, files)


if __name__ == "__main__":
    main()
