"""
Tool to extract and pretty-print PDF annotations for reviewing.
"""

__version__ = '0.3'

import bisect
import collections
import itertools
import logging
import typing

from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import (LAParams, LTAnno, LTChar, LTComponent, LTContainer, LTFigure, LTItem,
                             LTPage, LTTextBox, LTTextLine)
from pdfminer.converter import PDFLayoutAnalyzer
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.psparser import PSLiteralTable, PSLiteral
from pdfminer import pdftypes
import pdfminer.settings
import pdfminer.utils

from .types import Page, Outline, AnnotationType, Annotation, Document
from .utils import cleanup_text, decode_datetime, format_alpha, format_roman

pdfminer.settings.STRICT = False

logger = logging.getLogger(__name__)

ANNOT_SUBTYPES: typing.Dict[PSLiteral, AnnotationType] = {
    PSLiteralTable.intern(e.name): e for e in AnnotationType}
"""Mapping from PSliteral to our own enumerant, for supported annotation types."""

IGNORED_ANNOT_SUBTYPES = \
    frozenset(PSLiteralTable.intern(n) for n in (
        'Link',   # Links are used for internal document links (e.g. to other pages).
        'Popup',  # Controls the on-screen appearance of other annotations. TODO: we may want to
                  # check for an optional 'Contents' field for alternative human-readable contents.
    ))
"""Annotation types that we ignore without issuing a warning."""


def _mkannotation(
    pa: typing.Dict[str, typing.Any],
    page: Page
) -> typing.Optional[Annotation]:
    """
    Given a PDF annotation, capture relevant fields and construct an Annotation object.

    Refer to Section 8.4 of the PDF spec:
    https://www.adobe.com/content/dam/acom/en/devnet/pdf/pdfs/pdf_reference_archives/PDFReference.pdf
    """

    subtype = pa.get('Subtype')
    annot_type = None
    assert isinstance(subtype, PSLiteral)
    try:
        annot_type = ANNOT_SUBTYPES[subtype]
    except KeyError:
        pass

    if annot_type is None:
        if subtype not in IGNORED_ANNOT_SUBTYPES:
            logger.warning("Unsupported %s annotation ignored on %s", subtype.name, page)
        return None

    contents = pa.get('Contents')
    if contents is not None:
        # decode as string, normalise line endings, replace special characters
        contents = cleanup_text(pdfminer.utils.decode_text(contents))

    # Rect defines the location of the annotation on the page
    rect = pdftypes.resolve1(pa.get('Rect'))

    # QuadPoints are defined only for "markup" annotations (Highlight, Underline, StrikeOut,
    # Squiggly), where they specify the quadrilaterals (boxes) covered by the annotation.
    quadpoints = pdftypes.resolve1(pa.get('QuadPoints'))

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
        created = decode_datetime(createds)

    return Annotation(page, annot_type, quadpoints, rect,
                      contents, author=author, created=created)


def _get_outlines(doc: PDFDocument) -> typing.Iterator[Outline]:
    """Retrieve a list of (unresolved) Outline objects for all recognised outlines in the PDF."""

    def _resolve_dest(dest: typing.Any) -> typing.Any:
        if isinstance(dest, bytes):
            dest = pdftypes.resolve1(doc.get_dest(dest))
        elif isinstance(dest, PSLiteral):
            dest = pdftypes.resolve1(doc.get_dest(dest.name))
        if isinstance(dest, dict):
            dest = dest['D']
        return dest

    for (_, title, destname, actionref, _) in doc.get_outlines():
        if destname is None and actionref:
            action = pdftypes.resolve1(actionref)
            if isinstance(action, dict):
                subtype = action.get('S')
                if subtype is PSLiteralTable.intern('GoTo'):
                    destname = action.get('D')
        if destname is None:
            continue
        dest = _resolve_dest(destname)

        # consider targets of the form [page /XYZ left top zoom]
        if dest[1] is PSLiteralTable.intern('XYZ'):
            (pageref, _, targetx, targety) = dest[:4]

            if isinstance(pageref, (int, pdftypes.PDFObjRef)):
                yield Outline(title, pageref, (targetx, targety))
            else:
                logger.warning("Unsupported pageref in outline: %s", pageref)


class PDFNoPageLabels(Exception):
    pass


def _get_page_labels(doc: PDFDocument) -> typing.Iterator[str]:
    """
    Generate page label strings for the PDF document.

    If the document includes page labels, return a generator of strings, one per page.
    If not, raise PDFNoPageLabels.
    """
    assert doc.catalog is not None

    try:
        labels_tree = pdftypes.dict_value(doc.catalog['PageLabels'])
    except (pdftypes.PDFTypeError, KeyError) as ex:
        raise PDFNoPageLabels from ex

    total_pages = pdftypes.int_value(pdftypes.dict_value(doc.catalog['Pages'])['Count'])

    def walk_number_tree(td: typing.Dict[typing.Any, typing.Any]
                         ) -> typing.Iterator[
                             typing.Tuple[int, typing.Dict[typing.Any, typing.Any]]]:
        """
        Walk a number tree node dictionary, yielding (page index, label dict) tuples.

        See PDF spec, section 3.8.5.
        """
        if 'Nums' in td:  # Leaf node
            objs = pdftypes.list_value(td['Nums'])
            for (k, v) in pdfminer.utils.choplist(2, objs):
                yield pdftypes.int_value(k), pdftypes.dict_value(v)

        if 'Kids' in td:  # Intermediate node
            for child_ref in pdftypes.list_value(td['Kids']):
                yield from walk_number_tree(pdftypes.dict_value(child_ref))

    # Pass 1: find index ranges
    range_indices: typing.List[int] = []
    label_dicts: typing.List[typing.Dict[typing.Any, typing.Any]] = []
    for (index, d) in walk_number_tree(labels_tree):
        assert 0 <= index < total_pages
        if range_indices == []:
            assert index == 0  # Tree must include page index 0
        else:
            assert index > range_indices[-1]  # Tree must be sorted

        range_indices.append(index)
        label_dicts.append(d)

    # Pass 2: emit page labels
    for i in range(len(range_indices)):
        range_start = range_indices[i]
        range_limit = range_indices[i + 1] if i + 1 < len(range_indices) else total_pages

        d = label_dicts[i]
        style = d.get('S')
        prefix = pdfminer.utils.decode_text(pdftypes.str_value(d.get('P', b'')))
        first = pdftypes.int_value(d.get('St', 1))

        for value in range(first, first + range_limit - range_start):
            if style is PSLiteralTable.intern('D'):    # Decimal arabic numerals
                label = str(value)
            elif style is PSLiteralTable.intern('R'):  # Uppercase roman numerals
                label = format_roman(value).upper()
            elif style is PSLiteralTable.intern('r'):  # Lowercase roman numerals
                label = format_roman(value)
            elif style is PSLiteralTable.intern('A'):  # Uppercase letters A-Z, AA-ZZ, etc.
                label = format_alpha(value).upper()
            elif style is PSLiteralTable.intern('a'):  # Lowercase letters a-z, aa-zz, etc.
                label = format_alpha(value)
            else:
                label = ''

            yield prefix + label


class _PDFProcessor(PDFLayoutAnalyzer):  # type:ignore
    # (pdfminer lacks type annotations)
    """
    PDF processor class.

    This class encapsulates our primary interface with pdfminer's page layout logic. It is used
    to define a logical order for the objects we care about (Annotations and Outlines) on a page,
    and to capture the text that annotations may refer to.
    """

    CONTEXT_CHARS = 256
    """Maximum number of recent characters to keep as context."""

    page: typing.Optional[Page]     # Page being processed.
    charseq: int                    # Character sequence number within the page.
    compseq: int                    # Component sequence number within the page.
    recent_text: typing.Deque[str]  # Rotating buffer of recent text, for context.
    _lasthit: typing.FrozenSet[Annotation]  # Annotations hit by the most recent character.
    _curline: typing.Set[Annotation]        # Annotations hit somewhere on the current line.

    # Stores annotations that are subscribed to receive their post-annotation
    # context. The first element of each tuple, on which the list is sorted, is
    # the sequence number of the last character to hit the annotation.
    context_subscribers: typing.List[typing.Tuple[int, Annotation]]

    def __init__(self, rsrcmgr: PDFResourceManager, laparams: LAParams):
        super().__init__(rsrcmgr, laparams=laparams)
        self.page = None
        self.recent_text = collections.deque(maxlen=self.CONTEXT_CHARS)
        self.context_subscribers = []
        self.clear()

    def clear(self) -> None:
        """Reset our internal per-page state."""
        self.charseq = 0
        self.compseq = 0
        self.recent_text.clear()
        self.context_subscribers.clear()
        self._lasthit = frozenset()
        self._curline = set()

    def set_page(self, page: Page) -> None:
        """Prepare to process a new page. Must be called prior to processing."""
        assert self.page is None
        self.page = page

    def receive_layout(self, ltpage: LTPage) -> None:
        """Callback from PDFLayoutAnalyzer superclass. Called once with each laid-out page."""
        assert self.page is not None

        # Re-initialise our per-page state
        self.clear()

        # Render all the items on the page
        self.render(ltpage)

        # If we still have annotations needing context, give them whatever we have
        for (charseq, annot) in self.context_subscribers:
            available = self.charseq - charseq
            annot.post_context = ''.join(self.recent_text[n] for n in range(-available, 0))

        self.page = None

    def update_pageseq(self, component: LTComponent) -> None:
        """Assign sequence numbers for objects on the page based on the nearest line of text."""
        assert self.page is not None
        self.compseq += 1

        for x in itertools.chain(self.page.annots, self.page.outlines):
            x.update_pageseq(component, self.compseq)

    def test_boxes(self, item: LTComponent) -> None:
        """Update the set of annotations whose boxes intersect with the area of the given item."""
        assert self.page is not None
        hits = frozenset(a for a in self.page.annots if a.boxes
                         and any(b.hit_item(item) for b in a.boxes))
        self._lasthit = hits
        self._curline.update(hits)

    def capture_context(self, text: str) -> None:
        """Store the character for use as context, and update subscribers if required."""
        self.recent_text.append(text)
        self.charseq += 1

        # Notify subscribers for whom this character provides the full post-context.
        while self.context_subscribers:
            (charseq, annot) = self.context_subscribers[0]
            assert charseq < self.charseq
            if charseq == self.charseq - self.CONTEXT_CHARS:
                annot.set_post_context(''.join(self.recent_text))
                self.context_subscribers.pop(0)
            else:
                assert charseq > self.charseq - self.CONTEXT_CHARS
                break

    def capture_char(self, text: str) -> None:
        """Capture a non-newline character."""
        assert text != '\n'
        self.capture_context(text)

        # Broadcast the character to annotations that include it.
        for a in self._lasthit:
            last_charseq = a.last_charseq
            a.capture(text, self.charseq)

            if a.wants_context():
                if a.has_context():
                    # We already gave the annotation the pre-context, so it is subscribed.
                    # Locate and remove the annotation's existing context subscription.
                    assert last_charseq != 0
                    i = bisect.bisect_left(self.context_subscribers, (last_charseq,))
                    assert 0 <= i < len(self.context_subscribers)
                    (found_charseq, found_annot) = self.context_subscribers.pop(i)
                    assert found_charseq == last_charseq
                    assert found_annot is a

                else:
                    # This is the first hit for the annotation, so set the pre-context.
                    assert last_charseq == 0
                    assert len(a.text) != 0
                    pre_context = ''.join(
                        self.recent_text[n] for n in range(len(self.recent_text) - 1))
                    a.set_pre_context(pre_context)

                # Subscribe this annotation for post-context.
                self.context_subscribers.append((self.charseq, a))

    def capture_newline(self) -> None:
        """
        Capture a line break.

        "Broadcasts" newlines to _all_ annotations that received any text on the
        current line, in case they see more text on the next line, even if the
        most recent character on the line was not covered by their boxes.
        """
        self.capture_context('\n')
        for a in self._curline:
            a.capture('\n')
        self._curline = set()

    def render(self, item: LTItem) -> None:
        """
        Helper for receive_layout, called recursively for every item on a page, in layout order.

        Ref: https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
        """
        # Assign sequence numbers to items on the page based on their proximity to lines of text or
        # to figures (which may contain bare LTChar elements).
        if isinstance(item, (LTTextLine, LTFigure)):
            self.update_pageseq(item)

        # If it's a container, recurse on nested items.
        if isinstance(item, LTContainer):
            for child in item:
                self.render(child)

            # After the children of a text box, capture the end of the final
            # line (logic derived from pdfminer.converter.TextConverter).
            if isinstance(item, LTTextBox):
                self.capture_newline()

        # Each character is represented by one LTChar, and we must handle
        # individual characters (not higher-level objects like LTTextLine)
        # so that we can capture only those covered by the annotation boxes.
        elif isinstance(item, LTChar):
            self.test_boxes(item)
            self.capture_char(item.get_text())

        # LTAnno objects capture whitespace not explicitly encoded in
        # the text. They don't have an (X,Y) position -- we treat them
        # the same as the most recent character.
        elif isinstance(item, LTAnno):
            text = item.get_text()
            if text == '\n':
                self.capture_newline()
            else:
                self.capture_char(text)


def process_file(
    file: typing.BinaryIO,
    *,  # Subsequent arguments are keyword-only
    columns_per_page: typing.Optional[int] = None,
    emit_progress_to: typing.Optional[typing.TextIO] = None,
    laparams: LAParams = LAParams()
) -> Document:
    """
    Process a PDF file, extracting its annotations and outlines.

    Arguments:
        file                Handle to PDF file
        columns_per_page    If set, overrides PDF Miner's layout detect with a fixed page layout
        emit_progress_to    If set, file handle (e.g. sys.stderr) to which progress is reported
        laparams            PDF Miner layout parameters
    """

    # Initialise PDFMiner state
    rsrcmgr = PDFResourceManager()
    device = _PDFProcessor(rsrcmgr, laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    parser = PDFParser(file)
    doc = PDFDocument(parser)

    def emit_progress(msg: str) -> None:
        if emit_progress_to is not None:
            emit_progress_to.write(msg)
            emit_progress_to.flush()

    emit_progress(file.name)

    # Step 1: retrieve outlines if present. Each outline refers to a page, using
    # *either* a PDF object ID or an integer page number. These references will
    # be resolved below while rendering pages -- for now we insert them into one
    # of two dicts for later.
    outlines_by_pageno = collections.defaultdict(list)
    outlines_by_objid = collections.defaultdict(list)

    try:
        for o in _get_outlines(doc):
            if isinstance(o.pageref, pdftypes.PDFObjRef):
                outlines_by_objid[o.pageref.objid].append(o)
            else:
                outlines_by_pageno[o.pageref].append(o)
    except PDFNoOutlines:
        logger.info("Document doesn't include outlines (\"bookmarks\")")
    except Exception as ex:
        logger.warning("Failed to retrieve outlines: %s", ex)

    # Step 2: retrieve page labels, if present.
    page_labels: typing.Optional[typing.Iterator[str]] = _get_page_labels(doc)

    # Step 3: iterate over all the pages, constructing page objects.
    result = Document()
    for (pageno, pdfpage) in enumerate(PDFPage.create_pages(doc)):
        emit_progress(" %d" % (pageno + 1))

        page = Page(pageno, pdfpage.pageid, pdfpage.mediabox, columns_per_page)
        result.pages.append(page)

        # Retrieve the page's label, but stop trying after an exception is raised.
        if page_labels is not None:
            try:
                page.label = page_labels.__next__()
            except PDFNoPageLabels:
                page_labels = None
            except Exception as ex:
                logger.warning("Failed to parse page labels: %s", ex)
                page_labels = None

        # Resolve any outlines referring to this page, and link them to the page.
        # Note that outlines may refer to the page number or ID.
        for o in (outlines_by_objid.pop(page.objid, [])
                  + outlines_by_pageno.pop(pageno, [])):
            o.resolve(page)
            page.outlines.append(o)

        # Construct Annotation objects, and append them to the page.
        for pa in pdftypes.resolve1(pdfpage.annots) if pdfpage.annots else []:
            if isinstance(pa, pdftypes.PDFObjRef):
                annot = _mkannotation(pdftypes.dict_value(pa), page)
                if annot is not None:
                    page.annots.append(annot)
            else:
                logger.warning("Unknown annotation: %s", pa)

        # If the page has neither outlines nor annotations, skip further processing.
        if not (page.annots or page.outlines):
            continue

        # Render the page. This captures the selected text for any annotations
        # on the page, and updates annotations and outlines with a logical
        # sequence number based on the order of text lines on the page.
        device.set_page(page)
        interpreter.process_page(pdfpage)

        # Now we have their logical order, sort the annotations and outlines.
        page.annots.sort()
        page.outlines.sort()

    emit_progress("\n")

    device.close()

    # all outlines should be resolved by now
    assert {} == outlines_by_pageno
    assert {} == outlines_by_objid

    return result
