import datetime
import typing
from .utils import cleanup_text

Box = typing.Tuple[float, float, float, float] # (x0, y0, x1, y1)


class Page:
    pageno: int
    mediabox: Box
    ncolumns: int
    annots: typing.List["Annotation"]

    def __init__(self, pageno: int, mediabox: Box, ncolumns: int):
        self.pageno = pageno
        self.mediabox = mediabox
        self.ncolumns = ncolumns
        self.annots = []

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno == other.pageno

    def __lt__(self, other: typing.Any) -> bool:
        if not isinstance(other, Page):
            return NotImplemented
        return self.pageno < other.pageno


class Pos:
    def __init__(self, page: Page, x: float, y: float):
        self.page = page
        self.x = x
        self.y = y

    def __lt__(self, other: typing.Any) -> bool:
        if not isinstance(other, Pos):
            return NotImplemented
        if self.page < other.page:
            return True
        elif self.page == other.page:
            assert self.page is other.page
            # XXX: assume left-to-right top-to-bottom documents
            (sx, sy) = self.normalise_to_mediabox()
            (ox, oy) = other.normalise_to_mediabox()
            (x0, y0, x1, y1) = self.page.mediabox
            colwidth = (x1 - x0) / self.page.ncolumns
            self_col = (sx - x0) // colwidth
            other_col = (ox - x0) // colwidth
            return self_col < other_col or (self_col == other_col and sy > oy)
        else:
            return False

    def normalise_to_mediabox(self) -> typing.Tuple[float, float]:
        x, y = self.x, self.y
        (x0, y0, x1, y1) = self.page.mediabox
        if x < x0:
            x = x0
        elif x > x1:
            x = x1
        if y < y0:
            y = y0
        elif y > y1:
            y = y1
        return (x, y)


class Annotation:
    contents: typing.Optional[str]
    boxes: typing.List[Box]
    text: str

    def __init__(self,
                 page: Page,
                 tagname: str,
                 coords:typing.Optional[typing.Sequence[float]] =None,
                 rect:typing.Optional[Box] =None,
                 contents:typing.Optional[str] =None,
                 author:typing.Optional[str] =None,
                 created:typing.Optional[datetime.datetime] =None):
        self.page = page
        self.tagname = tagname
        if contents == '':
            self.contents = None
        else:
            self.contents = contents
        self.rect = rect
        self.author = author
        self.created = created
        self.text = ''

        self.boxes = []
        if coords:
            assert len(coords) % 8 == 0
            while coords != []:
                (x0,y0,x1,y1,x2,y2,x3,y3) = coords[:8]
                coords = coords[8:]
                xvals = [x0, x1, x2, x3]
                yvals = [y0, y1, y2, y3]
                box = (min(xvals), min(yvals), max(xvals), max(yvals))
                self.boxes.append(box)

    def capture(self, text: str) -> None:
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
        if self.boxes:
            if self.text:
                # replace tex ligatures (and other common odd characters)
                return cleanup_text(self.text.strip())
            else:
                # something's strange -- we have boxes but no text for them
                return "(XXX: missing text!)"
        else:
            return None

    def getstartpos(self) -> typing.Optional[Pos]:
        if self.rect:
            (x0, y0, x1, y1) = self.rect
        elif self.boxes:
            (x0, y0, x1, y1) = self.boxes[0]
        else:
            return None
        # XXX: assume left-to-right top-to-bottom text
        return Pos(self.page, min(x0, x1), max(y0, y1))

    # custom < operator for sorting
    def __lt__(self, other: typing.Any) -> bool:
        if isinstance(other, Annotation):
            mypos = self.getstartpos()
            otherpos = other.getstartpos()
            if mypos is not None and otherpos is not None:
                return mypos < otherpos
        return NotImplemented


class Outline:
    def __init__(self, title: str, dest: typing.Any, pos: Pos):
        self.title = title
        self.dest = dest
        self.pos = pos
