"""
Extracts annotations from a PDF file in markdown format for use in reviewing.
"""

__version__ = '0.1'

import sys
import io
import logging
import typing

from .types import Box, Pos, Page, Outline, Annotation
import pdfannots.utils as utils

from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import (
    LAParams, LTContainer, LTAnno, LTChar, LTPage, LTTextBox, LTItem, LTComponent)
from pdfminer.converter import TextConverter
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.psparser import PSLiteralTable, PSLiteral
import pdfminer.pdftypes as pdftypes
import pdfminer.settings
import pdfminer.utils

pdfminer.settings.STRICT = False

ANNOT_SUBTYPES = frozenset(
    {'Text', 'Highlight', 'Squiggly', 'StrikeOut', 'Underline'})


def _getannots(
    pdfannots: typing.Iterable[typing.Any],
    page: Page
) -> typing.List[Annotation]:

    annots = []
    for pa in pdfannots:
        subtype = pa.get('Subtype')
        if subtype is not None and subtype.name not in ANNOT_SUBTYPES:
            continue

        contents = pa.get('Contents')
        if contents is not None:
            # decode as string, normalise line endings, replace special characters
            contents = utils.cleanup_text(pdfminer.utils.decode_text(contents))

        coords = pdftypes.resolve1(pa.get('QuadPoints'))
        rect = pdftypes.resolve1(pa.get('Rect'))

        author = pdftypes.resolve1(pa.get('T'))
        if author is not None:
            author = pdfminer.utils.decode_text(author)

        created = None
        dobj = pa.get('CreationDate')
        # some pdf apps set modification date, but not creation date
        dobj = dobj or pa.get('ModDate')
        # poppler-based apps (e.g. Okular) use 'M' for some reason
        dobj = dobj or pa.get('M')
        createds = pdftypes.resolve1(dobj)
        if createds is not None:
            createds = pdfminer.utils.decode_text(createds)
            created = utils.decode_datetime(createds)

        a = Annotation(page, subtype.name, coords, rect,
                       contents, author=author, created=created)
        annots.append(a)

    return annots


def _resolve_dest(doc: PDFDocument, dest: typing.Any) -> typing.Any:
    if isinstance(dest, bytes):
        dest = pdftypes.resolve1(doc.get_dest(dest))
    elif isinstance(dest, PSLiteral):
        dest = pdftypes.resolve1(doc.get_dest(dest.name))
    if isinstance(dest, dict):
        dest = dest['D']
    return dest


def _get_outlines(
    doc: PDFDocument,
    pageslist: typing.List[Page],
    pagesdict: typing.Mapping[typing.Any, Page]
) -> typing.List[Outline]:

    result = []
    for (_, title, destname, actionref, _) in doc.get_outlines():
        if destname is None and actionref:
            action = pdftypes.resolve1(actionref)
            if isinstance(action, dict):
                subtype = action.get('S')
                if subtype is PSLiteralTable.intern('GoTo'):
                    destname = action.get('D')
        if destname is None:
            continue
        dest = _resolve_dest(doc, destname)

        # consider targets of the form [page /XYZ left top zoom]
        if dest[1] is PSLiteralTable.intern('XYZ'):
            (pageref, _, targetx, targety) = dest[:4]

            page = None
            if type(pageref) is int:
                page = pageslist[pageref]
            elif isinstance(pageref, pdftypes.PDFObjRef):
                page = pagesdict[pageref.objid]
            else:
                sys.stderr.write(
                    'Warning: unsupported pageref in outline: %s\n' % pageref)

            if page:
                pos = Pos(page, targetx, targety)
                result.append(Outline(title, destname, pos))
    return result


class _RectExtractor(TextConverter):  # type:ignore
    # (pdfminer lacks type annotations)

    annots: typing.Set[Annotation]
    _lasthit: typing.FrozenSet[Annotation]
    _curline: typing.Set[Annotation]

    def __init__(
            self,
            rsrcmgr: PDFResourceManager,
            codec: str = 'utf-8',
            pageno: int = 1,
            laparams: typing.Optional[LAParams] = None):

        dummy = io.StringIO()
        TextConverter.__init__(self, rsrcmgr, outfp=dummy,
                               codec=codec, pageno=pageno, laparams=laparams)
        self.annots = set()

    def setannots(self, annots: typing.Sequence[Annotation]) -> None:
        self.annots = {a for a in annots if a.boxes}

    # main callback from parent PDFConverter
    def receive_layout(self, ltpage: LTPage) -> None:
        self._lasthit = frozenset()
        self._curline = set()
        self.render(ltpage)

    def testboxes(self, item: LTComponent) -> typing.AbstractSet[Annotation]:
        hits = frozenset(
            {a for a in self.annots if any(
                {self.boxhit(item, b) for b in a.boxes})})
        self._lasthit = hits
        self._curline.update(hits)
        return hits

    @staticmethod
    def boxhit(item: LTComponent, box: Box) -> bool:
        (x0, y0, x1, y1) = box
        assert item.x0 <= item.x1 and item.y0 <= item.y1
        assert x0 <= x1 and y0 <= y1

        # does most of the item area overlap the box?
        # http://math.stackexchange.com/questions/99565/simplest-way-to-calculate-the-intersect-area-of-two-rectangles
        x_overlap = max(0, min(item.x1, x1) - max(item.x0, x0))
        y_overlap = max(0, min(item.y1, y1) - max(item.y0, y0))
        overlap_area = float(x_overlap) * float(y_overlap)
        item_area = float(item.x1 - item.x0) * float(item.y1 - item.y0)
        assert overlap_area <= item_area

        if overlap_area != 0:
            logging.debug(
                "Box hit: '%s' %f-%f,%f-%f in %f-%f,%f-%f %2.0f%%",
                item.get_text(),
                item.x0, item.x1, item.y0, item.y1,
                x0, x1, y0, y1,
                100 * overlap_area / item_area)

        return (item_area != 0) and overlap_area >= (0.5 * item_area)

    # "broadcast" newlines to _all_ annotations that received any text on the
    # current line, in case they see more text on the next line, even if the
    # most recent character was not covered.
    def capture_newline(self) -> None:
        for a in self._curline:
            a.capture('\n')
        self._curline = set()

    def render(self, item: LTItem) -> None:
        # If it's a container, recurse on nested items.
        if isinstance(item, LTContainer):
            for child in item:
                self.render(child)

            # Text boxes are a subclass of container, and somehow encode newlines
            # (this weird logic is derived from pdfminer.converter.TextConverter)
            if isinstance(item, LTTextBox):
                self.testboxes(item)
                self.capture_newline()

        # Each character is represented by one LTChar, and we must handle
        # individual characters (not higher-level objects like LTTextLine)
        # so that we can capture only those covered by the annotation boxes.
        elif isinstance(item, LTChar):
            for a in self.testboxes(item):
                a.capture(item.get_text())

        # Annotations capture whitespace not explicitly encoded in
        # the text. They don't have an (X,Y) position, so we need some
        # heuristics to match them to the nearby annotations.
        elif isinstance(item, LTAnno):
            text = item.get_text()
            if text == '\n':
                self.capture_newline()
            else:
                for a in self._lasthit:
                    a.capture(text)


def process_file(
    fh: typing.BinaryIO,
    columns_per_page: int,
    emit_progress: bool = False
) -> typing.Tuple[typing.List[Annotation], typing.List[Outline]]:

    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    device = _RectExtractor(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    parser = PDFParser(fh)
    doc = PDFDocument(parser)

    pageslist = []  # pages in page order
    pagesdict = {}  # map from PDF page object ID to Page object
    allannots = []

    for (pageno, pdfpage) in enumerate(PDFPage.create_pages(doc)):
        page = Page(pageno, pdfpage.mediabox, columns_per_page)
        pageslist.append(page)
        pagesdict[pdfpage.pageid] = page
        if pdfpage.annots:
            # emit progress indicator
            if emit_progress:
                sys.stderr.write(
                    (" " if pageno > 0 else "") + "%d" % (pageno + 1))
                sys.stderr.flush()

            pdfannots = []
            for a in pdftypes.resolve1(pdfpage.annots):
                if isinstance(a, pdftypes.PDFObjRef):
                    pdfannots.append(a.resolve())
                else:
                    sys.stderr.write('Warning: unknown annotation: %s\n' % a)

            page.annots = _getannots(pdfannots, page)
            page.annots.sort()
            device.setannots(page.annots)
            interpreter.process_page(pdfpage)
            allannots.extend(page.annots)

    if emit_progress:
        sys.stderr.write("\n")

    outlines = []
    try:
        outlines = _get_outlines(doc, pageslist, pagesdict)
    except PDFNoOutlines:
        if emit_progress:
            sys.stderr.write(
                "Document doesn't include outlines (\"bookmarks\")\n")
    except Exception as ex:
        sys.stderr.write("Warning: failed to retrieve outlines: %s\n" % ex)

    device.close()

    return (allannots, outlines)
