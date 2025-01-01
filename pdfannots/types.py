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

    def __repr__(self) -> str:
        return '<Box (%f,%f) (%f,%f)>' % (self.x0, self.y0, self.x1, self.y1)

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

    def get_area(self) -> float:
        """Return the area of the box."""
        return self.get_height() * self.get_width()

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
        return self.format_name()

    def format_name(self, use_label: bool = True, page_number_offset: int = 0) -> str:
        if self.label and use_label:
            return 'page %s' % self.label
        else:
            # + 1 for 1-based page numbers in normal program output (error messages, etc.)
            return 'page #%d' % (self.pageno + 1 + page_number_offset)

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

    def update_pageseq(self, component: LTComponent, pageseq: int) -> bool:
        """If close-enough to the given component, adopt its sequence number and return True."""
        assert pageseq > 0
        if self.item_hit(component):
            # This pos is inside the component area
            self._pageseq = pageseq
            self._pageseq_distance = 0
            return True
        else:
            d = Box.from_item(component).square_of_distance_to_closest_point((self.x, self.y))
            if self._pageseq == 0 or self._pageseq_distance > d:
                self._pageseq = pageseq
                self._pageseq_distance = d
                return True
            return False

    def discard_pageseq(self, pageseq: int) -> None:
        """If we have been assigned the specified pageseq, forget about it."""
        if self._pageseq == pageseq:
            self._pageseq = 0
            self._pageseq_distance = 0.0


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

    def update_pageseq(self, component: LTComponent, pageseq: int) -> bool:
        """Delegates to Pos.update_pageseq"""
        return False if self.pos is None else self.pos.update_pageseq(component, pageseq)

    def discard_pageseq(self, pageseq: int) -> None:
        """Delegates to Pos.discard_pageseq"""
        if self.pos is not None:
            self.pos.discard_pageseq(pageseq)


class AnnotationType(enum.Enum):
    """A supported PDF annotation type. Enumerant names match the Subtype names of the PDF spec."""

    # A "sticky note" comment annotation.
    Text = enum.auto()

    # Markup annotations that apply to one or more regions on the page.
    Highlight = enum.auto()
    Squiggly = enum.auto()
    StrikeOut = enum.auto()
    Underline = enum.auto()

    Caret = enum.auto()

    # A single rectangle, that is abused by some Apple tools to render custom
    # highlights. We do not attempt to capture the affected text.
    Square = enum.auto()

    # Free-form text written somewhere on the page.
    FreeText = enum.auto()


class Annotation(ObjectWithPos):
    """
    A PDF annotation, and its extracted text.

    Attributes:
        author          Author of the annotation
        color           RGB color of the annotation
        contents        Contents of the annotation in the PDF (e.g. comment/description)
        created         Timestamp the annotation was created
        group_children  Annotations grouped together with this one
        in_reply_to     Reference to another annotation on the page that this is "in reply to"
        is_group_child  Is this annotation a member of a parent group?
        last_charseq    Sequence number of the most recent character in text
        name            If present, uniquely identifies this annotation among others on the page
        replies         Annotations replying to this one (reverse of in_reply_to)
        subtype         PDF annotation type
        text            Text in the order captured (use gettext() for a cleaner form)

    Attributes updated for StrikeOut and Caret annotations:
        pre_context  Text captured just prior to the beginning of 'text'
        post_context Text captured just after the end of 'text'
    """

    boxes: typ.List[Box]
    contents: typ.Optional[str]
    group_children: typ.List[Annotation]
    in_reply_to: typ.Optional[Annotation]
    pre_context: typ.Optional[str]
    post_context: typ.Optional[str]
    replies: typ.List[Annotation]
    text: typ.List[str]

    def __init__(
            self,
            page: Page,
            subtype: AnnotationType,
            *,
            author: typ.Optional[str] = None,
            created: typ.Optional[datetime.datetime] = None,
            color: typ.Optional[RGB] = None,
            contents: typ.Optional[str] = None,
            in_reply_to_ref: typ.Optional[PDFObjRef] = None,
            is_group_child: bool = False,
            name: typ.Optional[str] = None,
            quadpoints: typ.Optional[typ.Sequence[float]] = None,
            rect: typ.Optional[BoxCoords] = None):

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

        # Kludge for Caret annotations that lack quadpoints, but need to capture context
        if quadpoints is None and subtype == AnnotationType.Caret:
            assert rect is not None
            boxes.append(Box.from_coords(rect))

        # Compute a meaningful position of this annotation on the page
        assert rect or boxes
        (x0, y0, x1, y1) = rect if rect else boxes[0].get_coords()
        # XXX: assume left-to-right top-to-bottom text
        pos = Pos(page, min(x0, x1), max(y0, y1))
        super().__init__(pos)

        # Initialise the attributes
        self.author = author
        self.boxes = boxes
        self.color = color
        self.contents = contents if contents else None
        self.created = created
        self.group_children = []
        self.name = name
        self.last_charseq = 0
        self.post_context = None
        self.pre_context = None
        self.replies = []
        self.subtype = subtype
        self.text = []

        # The in_reply_to reference will be resolved in postprocess()
        self.in_reply_to = None
        self._in_reply_to_ref = in_reply_to_ref
        self.is_group_child = is_group_child
        if is_group_child:
            assert in_reply_to_ref

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

    def get_child_by_type(self, child_type: AnnotationType) -> typ.Optional[Annotation]:
        """Return the first child of the given type."""
        for c in self.group_children:
            if c.subtype == child_type:
                return c
        return None

    def wants_context(self) -> bool:
        """Returns true if this annotation type should include context."""
        return self.subtype in {AnnotationType.Caret, AnnotationType.StrikeOut}

    def set_pre_context(self, pre_context: str) -> None:
        assert self.pre_context is None
        self.pre_context = pre_context

    def set_post_context(self, post_context: str) -> None:
        assert self.post_context is None

        # If the text ends in a (broadcast) newline, discard it lest it mess up the context below.
        if self.text and self.text[-1] == '\n':
            self.text.pop()

        # If the captured text ends in any (other) space, move it to the context.
        whitespace = []
        while self.text and self.text[-1].isspace():
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

    def postprocess(self, annots_by_objid: typ.Dict[int, Annotation]) -> None:
        """Update internal state once all text and context has been captured."""
        # Resole the in_reply_to object reference to its annotation
        if self._in_reply_to_ref is not None:
            assert self.in_reply_to is None  # This should be called once only
            a = annots_by_objid.get(self._in_reply_to_ref.objid)
            if a is None:
                logger.warning("IRT reference (%d) not found in page annotations",
                               self._in_reply_to_ref.objid)
            elif self.is_group_child:
                a.group_children.append(self)
            else:
                self.in_reply_to = a
                a.replies.append(self)

        # The Skim PDF reader (https://skim-app.sourceforge.io/) creates annotations whose
        # default initial contents are a copy of the selected text. Unless the user goes to
        # the trouble of editing each annotation, this goes badly for us because we have
        # duplicate text and contents (e.g., for simple highlights and strikeout).
        if self.contents and (text := self.gettext()) and text.strip() == self.contents.strip():
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

    def iter_annots(self, *, include_replies: bool = False) -> typ.Iterator[Annotation]:
        """
        Iterate over all the annotations in the document.

        Only the primary annotation for a group is included.
        Replies are included only if include_replies is True.
        """

        for p in self.pages:
            for a in p.annots:
                if not a.is_group_child and (include_replies or not a.in_reply_to):
                    yield a

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


class RGB(typ.NamedTuple):
    red: float
    green: float
    blue: float

    def ashex(self) -> str:
        "Return a 6-character string representing the 24-bit hex code for this colour."
        red_hex = format(int(self.red * 255), '02x')
        green_hex = format(int(self.green * 255), '02x')
        blue_hex = format(int(self.blue * 255), '02x')
        return red_hex + green_hex + blue_hex

    def __str__(self) -> str:
        return f"RGB({self.ashex()})"
