import datetime
import logging
import typing
from pdfminer.layout import LTComponent, LTTextLine
from pdfminer.pdftypes import PDFObjRef
from .utils import cleanup_text

logger = logging.getLogger('pdfannots')

Point = typing.Tuple[float, float]
"""An (x, y) point in PDF coordinates, i.e. bottom left is 0,0."""

BoxCoords = typing.Tuple[float, float, float, float]
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
    def from_item(item: LTComponent) -> "Box":
        """Construct a Box from the bounding box of a given PDF component."""
        return Box(item.x0, item.y0, item.x1, item.y1)

    @staticmethod
    def from_coords(coords: BoxCoords) -> "Box":
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

    def get_overlap(self, other: "Box") -> float:
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
                item.get_text(),
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


class Page:
    """
    Page.

    A page object uniquely represents a page in the PDF. It is identified by a
    zero-based page number, and a PDF object ID. It holds a list of Annotation
    objects for annotations on the page, and Outline objects for outlines that
    link to somewhere on the page.
    """

    annots: typing.List["Annotation"]
    outlines: typing.List["Outline"]

    def __init__(
        self,
        pageno: int,
        objid: typing.Any,
        mediabox: BoxCoords,
        fixed_columns: typing.Optional[int] = None
    ):
        assert pageno >= 0
        assert fixed_columns is None or fixed_columns > 0
        self.pageno = pageno
        self.objid = objid
        self.annots = []
        self.outlines = []
        self.mediabox = Box.from_coords(mediabox)
        self.fixed_columns = fixed_columns

    def __repr__(self) -> str:
        return ('<Page %d>' % self.pageno)

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno == other.pageno

    def __lt__(self, other: typing.Any) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno < other.pageno


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
        # + 1 for 1-based page numbers in normal program output (error messages, etc.)
        return ('page %d (%.3f,%.3f)' % (self.page.pageno + 1, self.x, self.y))

    def __repr__(self) -> str:
        return ('<Pos pg%d (%.3f,%.3f) #%d>' % (self.page.pageno, self.x, self.y, self._pageseq))

    def __lt__(self, other: typing.Any) -> bool:
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
                        if self.y == other.y:
                            return self.x < other.x
                        else:
                            return self.y > other.y
                    else:
                        return self._pageseq < other._pageseq
            else:
                return self.page < other.page
        else:
            return NotImplemented

    def item_hit(self, item: LTComponent) -> bool:
        """Is this pos within the bounding box of the given PDF component?"""
        return (self.x >= item.x0  # type:ignore
                and self.x <= item.x1
                and self.y >= item.y0
                and self.y <= item.y1)

    def update_pageseq(self, line: LTTextLine, pageseq: int) -> None:
        """If close-enough to the text line, adopt its sequence number."""
        assert pageseq > 0
        if self.item_hit(line):
            # This pos is inside the line area
            self._pageseq = pageseq
            self._pageseq_distance = 0
        else:
            d = Box.from_item(line).square_of_distance_to_closest_point((self.x, self.y))
            if self._pageseq == 0 or self._pageseq_distance > d:
                self._pageseq = pageseq
                self._pageseq_distance = d


class ObjectWithPos:
    """Any object that (eventually) has a logical position on the page."""

    def __init__(self, pos: typing.Optional[Pos] = None):
        self.pos = pos

    def __lt__(self, other: typing.Any) -> bool:
        if isinstance(other, ObjectWithPos):
            assert self.pos is not None
            assert other.pos is not None
            return self.pos < other.pos
        return NotImplemented

    def update_pageseq(self, line: LTTextLine, pageseq: int) -> None:
        """Delegates to Pos.update_pageseq"""
        if self.pos is not None:
            self.pos.update_pageseq(line, pageseq)


class Annotation(ObjectWithPos):
    """A PDF annotation, and its extracted text."""

    contents: typing.Optional[str]
    boxes: typing.List[Box]
    rect: typing.Optional[BoxCoords]
    text: str

    def __init__(
            self,
            page: Page,
            tagname: str,
            coords: typing.Optional[typing.Sequence[float]] = None,
            rect: typing.Optional[BoxCoords] = None,
            contents: typing.Optional[str] = None,
            author: typing.Optional[str] = None,
            created: typing.Optional[datetime.datetime] = None):

        # Construct boxes from coords
        boxes = []
        if coords:
            assert len(coords) % 8 == 0
            while coords != []:
                (x0, y0, x1, y1, x2, y2, x3, y3) = coords[:8]
                coords = coords[8:]
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
        self.tagname = tagname
        self.contents = contents if contents else None
        self.rect = rect
        self.author = author
        self.created = created
        self.text = ''
        self.boxes = boxes

    def __repr__(self) -> str:
        return ('<Annotation %s %r%s%s>' %
                (self.tagname, self.pos,
                 " '%s'" % self.contents[:10] if self.contents else '',
                 " '%s'" % self.text[:10] if self.text else ''))

    def capture(self, text: str) -> None:
        """Capture text (while rendering the PDF page)."""
        if text == '\n':
            # Kludge for latex: elide hyphens
            if self.text.endswith('-'):
                self.text = self.text[:-1]

            # Join lines, treating newlines as space, while ignoring successive
            # newlines. This makes it easier for the for the renderer to
            # "broadcast" LTAnno newlines to active annotations regardless of
            # box hits. (Detecting paragraph breaks is tricky anyway, and left
            # for future future work!)
            elif not self.text.endswith(' '):
                self.text += ' '
        else:
            self.text += text

    def gettext(self) -> typing.Optional[str]:
        """Retrieve cleaned-up text, after rendering."""
        if self.boxes:
            if self.text:
                # replace tex ligatures (and other common odd characters)
                return cleanup_text(self.text.strip())
            else:
                # something's strange -- we have boxes but no text for them
                logger.warning('Missing text for %s annotation at %s', self.tagname, self.pos)
                return ""
        else:
            return None


UnresolvedPage = typing.Union[int, PDFObjRef]
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
        target: typing.Tuple[float, float]
    ):
        super().__init__()
        self.title = title
        self.pageref = pageref
        self.target = target

    def __repr__(self) -> str:
        return ('<Outline \'%s\' %r>' % (self.title, self.pos))

    def resolve(self, page: Page) -> None:
        """Resolve our page reference to the given page, and update our position."""
        assert self.pos is None
        if type(self.pageref) is PDFObjRef:
            assert self.pageref.objid == page.objid
        else:
            assert self.pageref == page.pageno

        targetx, targety = self.target
        self.pos = Pos(page, targetx, targety)
