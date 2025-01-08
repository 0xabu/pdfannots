"""
Tool to extract and pretty-print PDF annotations for reviewing.
"""

__version__ = '0.5'

import bisect
import collections
import itertools
import logging
import typing as typ

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

from .types import Page, Outline, AnnotationType, Annotation, Document, RGB
from .utils import cleanup_text, decode_datetime

pdfminer.settings.STRICT = False

logger = logging.getLogger('pdfannots')

ANNOT_SUBTYPES: typ.Dict[PSLiteral, AnnotationType] = {
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
    pa: typ.Dict[str, typ.Any],
    page: Page
) -> typ.Optional[Annotation]:
    """
    Given a PDF annotation, capture relevant fields and construct an Annotation object.

    Refer to Section 8.4 of the PDF reference (version 1.7).
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

    rgb: typ.Optional[RGB] = None
    color = pdftypes.resolve1(pa.get('C'))
    if color:
        if (isinstance(color, list)
                and len(color) == 3
                and all(isinstance(e, (int, float)) and 0 <= e <= 1 for e in color)):
            rgb = RGB(*color)
        else:
            logger.warning("Invalid color %s in annotation on %s", color, page)

    # Rect defines the location of the annotation on the page
    rect = pdftypes.resolve1(pa.get('Rect'))

    # QuadPoints are defined only for "markup" annotations (Highlight, Underline, StrikeOut,
    # Squiggly, Caret), where they specify the quadrilaterals (boxes) covered by the annotation.
    quadpoints = pdftypes.resolve1(pa.get('QuadPoints'))

    author = pdftypes.resolve1(pa.get('T'))
    if author is not None:
        author = pdfminer.utils.decode_text(author)

    name = pdftypes.resolve1(pa.get('NM'))
    if name is not None:
        name = pdfminer.utils.decode_text(name)

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

    in_reply_to = pa.get('IRT')
    is_group = False
    if in_reply_to is not None:
        reply_type = pa.get('RT')
        if reply_type is PSLiteralTable.intern('Group'):
            is_group = True
        elif not (reply_type is None or reply_type is PSLiteralTable.intern('R')):
            logger.warning("Unexpected RT=%s, treated as R", reply_type)

    return Annotation(page, annot_type, quadpoints=quadpoints, rect=rect, name=name,
                      contents=contents, author=author, created=created, color=rgb,
                      in_reply_to_ref=in_reply_to, is_group_child=is_group)


def _get_outlines(doc: PDFDocument) -> typ.Iterator[Outline]:
    """Retrieve a list of (unresolved) Outline objects for all recognised outlines in the PDF."""

    def _resolve_dest(dest: typ.Any) -> typ.Any:
        if isinstance(dest, pdftypes.PDFObjRef):
            dest = pdftypes.resolve1(dest)
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

            if not isinstance(pageref, (int, pdftypes.PDFObjRef)):
                logger.warning("Unsupported pageref in outline: %s", pageref)
            else:
                if targetx is None or targety is None:
                    # Treat as a general reference to the page
                    target = None
                else:
                    target = (targetx, targety)
                    if not all(isinstance(v, (int, float)) for v in target):
                        logger.warning("Unsupported target in outline: (%r, %r)", targetx, targety)
                        target = None

                yield Outline(title, pageref, target)


class _PDFProcessor(PDFLayoutAnalyzer):
    """
    PDF processor class.

    This class encapsulates our primary interface with pdfminer's page layout logic. It is used
    to define a logical order for the objects we care about (Annotations and Outlines) on a page,
    and to capture the text that annotations may refer to.
    """

    CONTEXT_CHARS = 256
    """Maximum number of recent characters to keep as context."""

    page: typ.Optional[Page]                # Page being processed.
    charseq: int                            # Character sequence number within the page.
    compseq: int                            # Component sequence number within the page.
    recent_text: typ.Deque[str]             # Rotating buffer of recent text, for context.
    _lasthit: typ.FrozenSet[Annotation]     # Annotations hit by the most recent character.
    _curline: typ.Set[Annotation]           # Annotations hit somewhere on the current line.

    # Stores annotations that are subscribed to receive their post-annotation
    # context. The first element of each tuple, on which the list is sorted, is
    # the sequence number of the last character to hit the annotation.
    context_subscribers: typ.List[typ.Tuple[int, Annotation]]

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

    def update_pageseq(self, component: LTComponent) -> bool:
        """Assign sequence numbers for objects on the page based on the nearest line of text.
        Returns True if we need to recurse on smaller sub-components (e.g. characters)."""
        assert self.page is not None
        self.compseq += 1

        hits = 0
        for x in itertools.chain(self.page.annots, self.page.outlines):
            if x.update_pageseq(component, self.compseq):
                hits += 1

        # If we have assigned the same sequence number to multiple objects, and there exist smaller
        # sub-components (e.g. characters within a line), we'll recurse on those assigning sequence
        # numbers to sub-components to disambiguate the hits, but first we must forget about the
        # current sequence number.
        # NB: This could be done more efficiently -- we really only need to disambiguate conflicts
        # that still exist after processing *all* the line-level components on the same page, but
        # that would require multiple rendering passes.
        if hits > 1 and isinstance(component, LTContainer) and len(component) > 1:
            for x in itertools.chain(self.page.annots, self.page.outlines):
                x.discard_pageseq(self.compseq)
            return True

        return False

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
        """Capture a character."""
        self.capture_context(text)

        if text == '\n':
            # "Broadcast" newlines to _all_ annotations that received any text on the
            # current line, in case they see more text on the next line, even if the
            # most recent character on the line was not covered by their boxes.
            for a in self._curline:
                a.capture('\n')
            self._curline = set()
        else:
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
                        while True:
                            (found_charseq, found_annot) = self.context_subscribers[i]
                            assert found_charseq == last_charseq
                            if found_annot is a:
                                self.context_subscribers.pop(i)
                                break
                            i += 1
                            assert i < len(self.context_subscribers)

                    else:
                        # This is the first hit for the annotation, so set the pre-context.
                        assert last_charseq == 0
                        assert len(a.text) != 0
                        pre_context = ''.join(
                            self.recent_text[n] for n in range(len(self.recent_text) - 1))
                        a.set_pre_context(pre_context)

                    # Subscribe this annotation for post-context.
                    self.context_subscribers.append((self.charseq, a))

    def render(self, item: LTItem, pageseq_nested: bool = False) -> None:
        """
        Helper for receive_layout, called recursively for every item on a page, in layout order.

        Ref: https://pdfminersix.readthedocs.io/en/latest/topic/converting_pdf_to_text.html
        """
        # Assign sequence numbers to items on the page based on their proximity to lines of text or
        # to figures (which may contain bare LTChar elements).
        if isinstance(item, (LTTextLine, LTFigure)) or (
                pageseq_nested and isinstance(item, LTComponent)):
            pageseq_nested = self.update_pageseq(item)

        # If it's a container, recurse on nested items.
        if isinstance(item, LTContainer):
            for child in item:
                self.render(child, pageseq_nested)

            # After the children of a text box, capture the end of the final
            # line (logic derived from pdfminer.converter.TextConverter).
            if isinstance(item, LTTextBox):
                self.capture_char('\n')

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
            self.capture_char(item.get_text())


def process_file(
    file: typ.BinaryIO,
    *,  # Subsequent arguments are keyword-only
    columns_per_page: typ.Optional[int] = None,
    emit_progress_to: typ.Optional[typ.TextIO] = None,
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

    # Retrieve outlines if present. Each outline refers to a page, using
    # *either* a PDF object ID or an integer page number. These references will
    # be resolved below while rendering pages -- for now we insert them into one
    # of two dicts for later.
    outlines_by_pageno: typ.Dict[object, typ.List[Outline]] = collections.defaultdict(list)
    outlines_by_objid: typ.Dict[object, typ.List[Outline]] = collections.defaultdict(list)

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

    # Iterate over all the pages, constructing page objects.
    result = Document()
    for (pageno, pdfpage) in enumerate(PDFPage.create_pages(doc)):
        emit_progress(" %d" % (pageno + 1))

        page = Page(pageno, pdfpage.pageid, pdfpage.label, pdfpage.mediabox, columns_per_page)
        result.pages.append(page)

        # Resolve any outlines referring to this page, and link them to the page.
        # Note that outlines may refer to the page number or ID.
        for o in (outlines_by_objid.pop(page.objid, [])
                  + outlines_by_pageno.pop(pageno, [])):
            o.resolve(page)
            page.outlines.append(o)

        # Dict from object ID (in the ObjRef) to Annotation object
        # This is used while post-processing to resolve inter-annotation references
        annots_by_objid: typ.Dict[int, Annotation] = {}

        # Construct Annotation objects, and append them to the page.
        for pa in pdftypes.resolve1(pdfpage.annots) if pdfpage.annots else []:
            if isinstance(pa, pdftypes.PDFObjRef):
                annot_dict = pdftypes.dict_value(pa)
                if annot_dict:  # Would be empty if pa is a broken ref
                    annot = _mkannotation(annot_dict, page)
                    if annot is not None:
                        page.annots.append(annot)
                        assert pa.objid not in annots_by_objid
                        annots_by_objid[pa.objid] = annot
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

        # Give the annotations a chance to update their internals
        for a in page.annots:
            a.postprocess(annots_by_objid)

    emit_progress("\n")

    device.close()

    # all outlines should be resolved by now
    assert {} == outlines_by_pageno
    assert {} == outlines_by_objid

    return result
