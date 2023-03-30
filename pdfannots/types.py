from __future__ import annotations

import bisect
import datetime
import enum
import functools
import logging
import typing as typ

from pdfminer.layout import LTComponent, LTText
from pdfminer.pdftypes import PDFObjRef

from .utils import merge_lines

logger = logging.getLogger('pdfannots')

Point = typ.Tuple[float, float]
"""An (x, y) point in PDF coordinates, i.e. bottom left is 0,0."""

BoxCoords = typ.Tuple[float, float, float, float]
"""The coordinates of a bounding box (x0, y0, x1, y1)."""


class Box:
    """
    Coordinates of a rectangular box.
    """

    def __init__(self, x0: float, y0: float, x1: float, y1: float):
        assert x0 <= x1 and y0 <= y1
        self.x0 = x0
        self.x1 = x1
        self.y0 = y0
        self.y1 = y1

    @staticmethod
    def from_item(item: LTComponent) -> Box:
        """Construct a Box from the bounding box of a given PDF component."""
        return Box(item.x0, item.y0, item.x1, item.y1)

    @staticmethod
    def from_coords(coords: BoxCoords) -> Box:
        """Construct a Box from the given PDF coordinates."""
        (x0, y0, x1, y1) = coords
        return Box(x0, y0, x1, y1)

    def get_coords(self) -> BoxCoords:
        """Return the PDF coordinates of this box."""
        return (self.x0, self.y0, self.x1, self.y1)

    def get_width(self) -> float:
        """Return the width of the box."""
        return self.x1 - self.x0

    def get_height(self) -> float:
        """Return the height of the box."""
        return self.y1 - self.y0

    def get_overlap(self, other: Box) -> float:
        """Compute the overlapping area (if any) with the provided box."""
        x_overlap = max(0, min(other.x1, self.x1) - max(other.x0, self.x0))
        y_overlap = max(0, min(other.y1, self.y1) - max(other.y0, self.y0))
        return x_overlap * y_overlap

    def hit_item(self, item: LTComponent) -> bool:
        """Does most of the area of the PDF component overlap this box?"""
        item_area = float(item.width) * float(item.height)
        overlap_area = self.get_overlap(Box.from_item(item))

        if overlap_area != 0:
            logger.debug(
                "Box hit: '%s' %f-%f,%f-%f in %f-%f,%f-%f %2.0f%%",
                item.get_text() if isinstance(item, LTText) else '',
                item.x0, item.x1, item.y0, item.y1,
                self.x0, self.x1, self.y0, self.y1,
                100 * overlap_area / item_area)

        assert overlap_area <= item_area
        return (item_area != 0) and overlap_area >= (0.5 * item_area)

    def closest_point(self, point: Point) -> Point:
        """Compute the closest point in this box to the specified point."""
        px, py = point
        return (min(max(self.x0, px), self.x1),
                min(max(self.y0, py), self.y1))

    def square_of_distance_to_closest_point(self, point: Point) -> float:
        """
        Compute the distance from the closest point in this box to the specified point, squared.

        (We avoid calling sqrt for performance reasons, since we just need to compare.)
        """
        x, y = self.closest_point(point)
        px, py = point
        return abs(px - x)**2 + abs(py - y)**2


@functools.total_ordering
class Page:
    """
    Page.

    A page object uniquely represents a page in the PDF. It is identified by a
    zero-based page number, and a PDF object ID. It holds a list of Annotation
    objects for annotations on the page, and Outline objects for outlines that
    link to somewhere on the page.
    """

    annots: typ.List[Annotation]
    outlines: typ.List[Outline]

    def __init__(
        self,
        pageno: int,
        objid: object,
        label: typ.Optional[str],
        mediabox: BoxCoords,
        fixed_columns: typ.Optional[int] = None
    ):
        assert pageno >= 0
        assert fixed_columns is None or fixed_columns > 0
        self.pageno = pageno
        self.objid = objid
        self.label = label
        self.annots = []
        self.outlines = []
        self.mediabox = Box.from_coords(mediabox)
        self.fixed_columns = fixed_columns

    def __repr__(self) -> str:
        return '<Page #%d>' % self.pageno  # zero-based page index

    def __str__(self) -> str:
        if self.label:
            return 'page %s' % self.label
        else:
            # + 1 for 1-based page numbers in normal program output (error messages, etc.)
            return 'page #%d' % (self.pageno + 1)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno == other.pageno

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno < other.pageno


@functools.total_ordering
class Pos:
    """
    A position within the document.

    This object represents an x,y point on a particular page. Such positions are
    also comparable, and compare in natural document reading order (as inferred
    by pdfminer's text layout detection).
    """

    def __init__(self, page: Page, x: float, y: float):
        self.page = page
        self.x = x
        self.y = y
        self._pageseq = 0
        self._pageseq_distance = 0.0

    def __str__(self) -> str:
        return '%s (%.3f,%.3f)' % (self.page, self.x, self.y)

    def __repr__(self) -> str:
        return '<Pos pg#%d (%.3f,%.3f) #%d>' % (self.page.pageno, self.x, self.y, self._pageseq)

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Pos):
            return (self.page == other.page
                    and self.x == other.x
                    and self.y == other.y)
        return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Pos):
            if self.page == other.page:
                assert self.page is other.page
                if self.page.fixed_columns:
                    # Fixed layout: assume left-to-right top-to-bottom documents
                    (sx, sy) = self.page.mediabox.closest_point((self.x, self.y))
                    (ox, oy) = self.page.mediabox.closest_point((other.x, other.y))
                    colwidth = self.page.mediabox.get_width() / self.page.fixed_columns
                    self_col = (sx - self.page.mediabox.x0) // colwidth
                    other_col = (ox - self.page.mediabox.x0) // colwidth
                    return self_col < other_col or (self_col == other_col and sy > oy)
                else:
                    # Default layout inferred from pdfminer traversal
                    assert self._pageseq != 0
                    assert other._pageseq != 0
                    if self._pageseq == other._pageseq:
                        # The positions are on or closest to the same line of text.
                        # XXX: assume top-to-bottom left-to-right order
                        return self.x < other.x if self.y == other.y else self.y > other.y
                    else:
                        return self._pageseq < other._pageseq
            else:
                return self.page < other.page
        else:
            return NotImplemented

    def item_hit(self, item: LTComponent) -> bool:
        """Is this pos within the bounding box of the given PDF component?"""
        return (self.x >= item.x0
                and self.x <= item.x1
                and self.y >= item.y0
                and self.y <= item.y1)

    def update_pageseq(self, component: LTComponent, pageseq: int) -> None:
        """If close-enough to the given component, adopt its sequence number."""
        assert pageseq > 0
        if self.item_hit(component):
            # This pos is inside the component area
            self._pageseq = pageseq
            self._pageseq_distance = 0
        else:
            d = Box.from_item(component).square_of_distance_to_closest_point((self.x, self.y))
            if self._pageseq == 0 or self._pageseq_distance > d:
                self._pageseq = pageseq
                self._pageseq_distance = d


@functools.total_ordering
class ObjectWithPos:
    """Any object that (eventually) has a logical position on the page."""

    def __init__(self, pos: typ.Optional[Pos] = None):
        self.pos = pos

    def __lt__(self, other: object) -> bool:
        if isinstance(other, ObjectWithPos):
            assert self.pos is not None
            assert other.pos is not None
            return self.pos < other.pos
        return NotImplemented

    def update_pageseq(self, component: LTComponent, pageseq: int) -> None:
        """Delegates to Pos.update_pageseq"""
        if self.pos is not None:
            self.pos.update_pageseq(component, pageseq)


class AnnotationType(enum.Enum):
    """A supported PDF annotation type. Enumerant names match the Subtype names of the PDF spec."""

    # A "sticky note" comment annotation.
    Text = enum.auto()

    # Markup annotations that apply to one or more regions on the page.
    Highlight = enum.auto()
    Squiggly = enum.auto()
    StrikeOut = enum.auto()
    Underline = enum.auto()

    # A single rectangle, that is abused by some Apple tools to render custom
    # highlights. We do not attempt to capture the affected text.
    Square = enum.auto()

    # Free-form text written somewhere on the page.
    FreeText = enum.auto()


class Annotation(ObjectWithPos):
    """
    A PDF annotation, and its extracted text.

    Attributes:
        subtype      PDF annotation type
        contents     Contents of the annotation in the PDF (e.g. comment/description)
        text         Text in the order captured (use gettext() for a cleaner form)
        author       Author of the annotation
        created      Timestamp the annotation was created
        last_charseq Sequence number of the most recent character in text

    Attributes updated only for StrikeOut annotations:
        pre_context  Text captured just prior to the beginning of 'text'
        post_context Text captured just after the end of 'text'
    """

    contents: typ.Optional[str]
    boxes: typ.List[Box]
    text: typ.List[str]
    pre_context: typ.Optional[str]
    post_context: typ.Optional[str]

    def __init__(
            self,
            page: Page,
            subtype: AnnotationType,
            quadpoints: typ.Optional[typ.Sequence[float]] = None,
            rect: typ.Optional[BoxCoords] = None,
            contents: typ.Optional[str] = None,
            author: typ.Optional[str] = None,
            created: typ.Optional[datetime.datetime] = None):

        # Construct boxes from quadpoints
        boxes = []
        if quadpoints is not None:
            assert len(quadpoints) % 8 == 0
            while quadpoints != []:
                (x0, y0, x1, y1, x2, y2, x3, y3) = quadpoints[:8]
                quadpoints = quadpoints[8:]
                xvals = [x0, x1, x2, x3]
                yvals = [y0, y1, y2, y3]
                box = Box(min(xvals), min(yvals), max(xvals), max(yvals))
                boxes.append(box)

        # Compute a meaningful position of this annotation on the page
        assert rect or boxes
        (x0, y0, x1, y1) = rect if rect else boxes[0].get_coords()
        # XXX: assume left-to-right top-to-bottom text
        pos = Pos(page, min(x0, x1), max(y0, y1))
        super().__init__(pos)

        # Initialise the attributes
        self.subtype = subtype
        self.contents = contents if contents else None
        self.author = author
        self.created = created
        self.text = []
        self.pre_context = None
        self.post_context = None
        self.boxes = boxes
        self.last_charseq = 0

    def __repr__(self) -> str:
        return ('<Annotation %s %r%s%s>' %
                (self.subtype.name, self.pos,
                 " '%s'" % self.contents[:10] if self.contents else '',
                 " '%s'" % ''.join(self.text[:10]) if self.text else ''))

    def capture(self, text: str, charseq: int = 0) -> None:
        """Capture text (while rendering the PDF page)."""
        self.text.append(text)
        if charseq:
            assert charseq > self.last_charseq
            self.last_charseq = charseq

    def gettext(self, remove_hyphens: bool = False) -> typ.Optional[str]:
        """Retrieve cleaned-up text, after rendering."""
        if self.boxes:
            if self.text:
                captured = ''.join(self.text)
                return merge_lines(captured, remove_hyphens, strip_space=(not self.has_context()))
            else:
                # something's strange -- we have boxes but no text for them
                logger.warning('Missing text for %s annotation at %s', self.subtype.name, self.pos)
                return ""
        else:
            return None

    def wants_context(self) -> bool:
        """Returns true if this annotation type should include context."""
        return self.subtype == AnnotationType.StrikeOut

    def set_pre_context(self, pre_context: str) -> None:
        assert self.pre_context is None
        self.pre_context = pre_context

    def set_post_context(self, post_context: str) -> None:
        assert self.post_context is None

        # If the captured text ends in space, move it to the context.
        if self.text:
            whitespace = []
            while self.text[-1].isspace():
                whitespace.append(self.text.pop())
            if whitespace:
                post_context = ''.join(whitespace) + post_context

        self.post_context = post_context

    def has_context(self) -> bool:
        """Returns true if this annotation captured context."""
        return self.pre_context is not None or self.post_context is not None

    def get_context(self, remove_hyphens: bool = False) -> typ.Tuple[str, str]:
        """Returns context captured for this annotation, as a tuple (pre, post)."""
        return (merge_lines(self.pre_context or '', remove_hyphens, strip_space=False),
                merge_lines(self.post_context or '', remove_hyphens, strip_space=False))

    def postprocess(self) -> None:
        """Update internal state once all text and context has been captured."""
        # The Skim PDF reader (https://skim-app.sourceforge.io/) creates annotations whose
        # default initial contents are a copy of the selected text. Unless the user goes to
        # the trouble of editing each annotation, this goes badly for us because we have
        # duplicate text and contents (e.g., for simple highlights and strikeout).
        if self.contents and self.text and ''.join(self.text).strip() == self.contents.strip():
            self.contents = None


UnresolvedPage = typ.Union[int, PDFObjRef]
"""A reference to a page that is *either* a page number, or a PDF object ID."""


class Outline(ObjectWithPos):
    """
    A PDF outline (also known as a bookmark).

    Outlines are used to navigate the PDF, and are often headings in the
    document's table of contents. A single outline has a title (name), and a
    target location in the PDF (page and X/Y coordinates). Initially the page is
    referred to by reference, but the reference is unresolved -- it is either a
    page number, or a PDF object ID. While rendering the PDF, the page is
    resolved to a Page object, and the pos attribute is updated.
    """

    def __init__(
        self,
        title: str,
        pageref: UnresolvedPage,
        target: typ.Optional[typ.Tuple[float, float]]
    ):
        super().__init__()
        self.title = title
        self.pageref = pageref
        self.target = target

    def __repr__(self) -> str:
        return '<Outline \'%s\' %r>' % (self.title, self.pos)

    def resolve(self, page: Page) -> None:
        """Resolve our page reference to the given page, and update our position."""
        assert self.pos is None
        if isinstance(self.pageref, PDFObjRef):
            assert self.pageref.objid == page.objid
        else:
            assert self.pageref == page.pageno

        if self.target is None:
            # XXX: "first" point on the page, assuming left-to-right top-to-bottom order
            (targetx, targety) = (page.mediabox.x0, page.mediabox.y1)
        else:
            (targetx, targety) = self.target

        self.pos = Pos(page, targetx, targety)


class Document:
    """
    A fully-extracted PDF document.

    This is really just a list of pages and some helpers.

    Attributes:
        pages   An ordered list of Page objects, indexed by zero-based page number.
    """

    pages: typ.List[Page]

    def __init__(self) -> None:
        self.pages = []

    def iter_annots(self) -> typ.Iterator[Annotation]:
        """Iterate over all the annotations in the document."""
        for p in self.pages:
            yield from p.annots

    def nearest_outline(
        self,
        pos: Pos
    ) -> typ.Optional[Outline]:
        """Return the first outline occuring prior to the given position, in reading order."""

        # Search pages backwards from the given pos
        for pageno in range(pos.page.pageno, -1, -1):
            page = self.pages[pageno]
            assert page.pageno == pageno

            # Outlines are pre-sorted, so we can use bisect to find the first outline < pos
            idx = bisect.bisect(page.outlines, ObjectWithPos(pos))
            if idx:
                return page.outlines[idx - 1]

        return None
