#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Extracts annotations from a PDF file in a text format for use in reviewing.
"""

import sys, io, textwrap, argparse, codecs
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LAParams, LTContainer, LTAnno, LTChar, LTTextBox
from pdfminer.converter import TextConverter
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument, PDFNoOutlines
from pdfminer.psparser import PSLiteralTable, PSLiteral
import pdfminer.pdftypes as pdftypes
import pdfminer.settings

pdfminer.settings.STRICT = False

SUBSTITUTIONS = {
    u'ﬀ': 'ff',
    u'ﬁ': 'fi',
    u'ﬂ': 'fl',
    u'’': "'",
    u'“': "``",
    u'”': "''",
}

ANNOT_SUBTYPES = frozenset({'Text', 'Highlight', 'Squiggly', 'StrikeOut', 'Underline'})
ANNOT_NITS = frozenset({'Squiggly', 'StrikeOut', 'Underline'})

DEBUG_BOXHIT = False

def boxhit(item, box):
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
    def __init__(self, rsrcmgr, codec='utf-8', pageno=1, laparams=None):
        dummy = io.StringIO()
        TextConverter.__init__(self, rsrcmgr, outfp=dummy, codec=codec, pageno=pageno, laparams=laparams)
        self.annots = set()

    def setannots(self, annots):
        self.annots = {a for a in annots if a.boxes}

    # main callback from parent PDFConverter
    def receive_layout(self, ltpage):
        self._lasthit = frozenset()
        self._curline = set()
        self.render(ltpage)

    def testboxes(self, item):
        hits = frozenset({a for a in self.annots if any({boxhit(item, b) for b in a.boxes})})
        self._lasthit = hits
        self._curline.update(hits)
        return hits

    # "broadcast" newlines to _all_ annotations that received any text on the
    # current line, in case they see more text on the next line, even if the
    # most recent character was not covered.
    def capture_newline(self):
        for a in self._curline:
            a.capture('\n')
        self._curline = set()

    def render(self, item):
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



class Page:
    def __init__(self, pageno, mediabox):
        self.pageno = pageno
        self.mediabox = mediabox
        self.annots = []

    def __eq__(self, other):
        return self.pageno == other.pageno

    def __lt__(self, other):
        return self.pageno < other.pageno

class Annotation:
    def __init__(self, page, tagname, coords=None, rect=None, contents=None):
        self.page = page
        self.tagname = tagname
        if contents == '':
            self.contents = None
        else:
            self.contents = contents
        self.rect = rect
        self.text = ''

        if coords is None:
            self.boxes = None
        else:
            assert len(coords) % 8 == 0
            self.boxes = []
            while coords != []:
                (x0,y0,x1,y1,x2,y2,x3,y3) = coords[:8]
                coords = coords[8:]
                xvals = [x0, x1, x2, x3]
                yvals = [y0, y1, y2, y3]
                box = (min(xvals), min(yvals), max(xvals), max(yvals))
                self.boxes.append(box)

    def capture(self, text):
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

    def gettext(self):
        if self.text:
            # replace tex ligatures (and other common odd characters)
            return ''.join([SUBSTITUTIONS.get(c, c) for c in self.text.strip()])
        else:
            return None

    def getstartpos(self):
        if self.rect:
            (x0, y0, x1, y1) = self.rect
        elif self.boxes:
            (x0, y0, x1, y1) = self.boxes[0]
        else:
            return None
        # XXX: assume left-to-right top-to-bottom text
        return Pos(self.page, min(x0, x1), max(y0, y1))

    # custom < operator for sorting
    def __lt__(self, other):
        return self.getstartpos() < other.getstartpos()

class Pos:
    def __init__(self, page, x, y):
        self.page = page
        self.x = x
        self.y = y

    def __lt__(self, other):
        if self.page < other.page:
            return True
        elif self.page == other.page:
            assert self.page is other.page
            # XXX: assume two-column left-to-right top-to-bottom documents
            (sx, sy) = self.normalise_to_mediabox()
            (ox, oy) = other.normalise_to_mediabox()
            (x0, y0, x1, y1) = self.page.mediabox
            colwidth = (x1 - x0) / 2
            self_col = (sx - x0) // colwidth
            other_col = (ox - x0) // colwidth
            return self_col < other_col or (self_col == other_col and sy > oy)
        else:
            return False

    def normalise_to_mediabox(self):
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

def getannots(pdfannots, page, codec):
    annots = []
    for pa in pdfannots:
        subtype = pa.get('Subtype')
        if subtype is not None and subtype.name not in ANNOT_SUBTYPES:
            continue

        contents = pa.get('Contents')
        if contents is not None:
            contents, _ = codec.decode(contents)
            contents = contents.replace('\r\n', '\n').replace('\r', '\n')

        coords = pdftypes.resolve1(pa.get('QuadPoints'))
        rect = pdftypes.resolve1(pa.get('Rect'))
        a = Annotation(page, subtype.name, coords, rect, contents)
        annots.append(a)

    return annots

def prettyprint(annots, outlines, outfile, do_group, sections, wrapcol):
    """
    Pretty-print the extracted annotations according to the output options.

    annots   List of extracted annotations, in the order they appear
    outlines List of outlines
    outfile  Output file handle to print to
    do_group Boolean, enables grouping by annotation type
    sections When grouping by type, this controls the order of sections output
             e.g.: ["highlights", "comments", "nits"]
    wrapcol  If not None, specifies the column at which output is word-wrapped
    """

    def nearest_outline(pos):
        prev = None
        for o in outlines:
            if o.pos < pos:
                prev = o
            else:
                break
        return prev

    def fmtpos(annot):
        apos = annot.getstartpos()
        o = nearest_outline(apos) if apos else None
        if o:
            return "Page %d (%s)" % (annot.page.pageno + 1, o.title)
        else:
            return "Page %d" % (annot.page.pageno + 1)

    def fmttext(annot):
        if annot.boxes:
            if annot.gettext():
                return '"%s"' % annot.gettext()
            else:
                return "(XXX: missing text!)"
        else:
            return ''

    if wrapcol:
        # we need two text wrappers: one for the leading bullet on the first paragraph, one without
        tw1 = textwrap.TextWrapper(width=wrapcol, initial_indent=" * ", subsequent_indent="   ")
        tw2 = textwrap.TextWrapper(width=wrapcol, initial_indent="   ", subsequent_indent="   ")

    def printannot(annot, extra=None):
        # we are either printing: item text and item contents, or one of the two
        # if we see an annotation with neither, something has gone wrong
        parts = [s for s in [fmttext(annot), annot.contents] if s]
        assert parts != []

        # break each part into paragraphs
        lines = [[l for l in p.splitlines() if l] for p in parts]
        assert len(lines) in {1,2}

        if len(lines) > 1:
            # If we have a short text section and a short comment, join them
            # into one paragraph. Otherwise, we'll use multiple output paragraphs.
            if len(lines[0]) == 1 and len(lines[1]) == 1:
                msglines = [lines[0][0] + " -- " + lines[1][0]]
            else:
                msglines = lines[0] + ["-- " + lines[1][0]] + lines[1][1:]
        else:
            msglines = lines[0]

        # prepend the formatted position (and extra bit if needed)
        label = fmtpos(annot) + (" " + extra if extra else "")
        msglines[0] = label + ": " + msglines[0]

        # emit Markdown bullet, wrapped as desired
        if wrapcol:
            msg = tw1.fill(msglines[0]) + ('\n\n' if msglines[1:] else '') + '\n\n'.join(tw2.fill(m) for m in msglines[1:])
        else:
            msg = " * " + msglines[0] + ('\n' if msglines[1:] else '') + '\n'.join('   ' + m for m in msglines[1:])

        # print it!
        print(msg + "\n", file=outfile)

    def printheader(name):
        # emit blank separator line if needed
        if printheader.called:
            print("", file=outfile)
        else:
            printheader.called = True
        print("## " + name + "\n", file=outfile)
    printheader.called = False

    if do_group:
        highlights = [a for a in annots if a.tagname == 'Highlight' and a.contents is None]
        comments = [a for a in annots if a.tagname not in ANNOT_NITS and a.contents]
        nits = [a for a in annots if a.tagname in ANNOT_NITS]

        for secname in sections:
            if highlights and secname == 'highlights':
                printheader("Highlights")
                for a in highlights:
                    printannot(a)

            if comments and secname == 'comments':
                printheader("Detailed comments")
                for a in comments:
                    printannot(a)

            if nits and secname == 'nits':
                printheader("Nits")
                for a in nits:
                    printannot(a)

    else:
        for a in annots:
            printannot(a, a.tagname)

def resolve_dest(doc, dest):
    if isinstance(dest, bytes):
        dest = pdftypes.resolve1(doc.get_dest(dest))
    elif isinstance(dest, PSLiteral):
        dest = pdftypes.resolve1(doc.get_dest(dest.name))
    if isinstance(dest, dict):
        dest = dest['D']
    return dest

class Outline:
    def __init__(self, title, dest, pos):
        self.title = title
        self.dest = dest
        self.pos = pos

def get_outlines(doc, pagesdict):
    result = []
    for (_, title, destname, actionref, _) in doc.get_outlines():
        if destname is None and actionref:
            action = actionref.resolve()
            if isinstance(action, dict):
                subtype = action.get('S')
                if subtype is PSLiteralTable.intern('GoTo'):
                    destname = action.get('D')
        if destname is None:
            continue
        dest = resolve_dest(doc, destname)
        # consider targets of the form [page /XYZ left top zoom]
        if dest[1] is PSLiteralTable.intern('XYZ'):
            (pageref, _, targetx, targety, _) = dest
            page = pagesdict[pageref.objid]
            pos = Pos(page, targetx, targety)
            result.append(Outline(title, destname, pos))
    return result

def process_file(fh, codec, emit_progress):
    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    device = RectExtractor(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    parser = PDFParser(fh)
    doc = PDFDocument(parser)

    pagesdict = {} # map from PDF page object ID to Page object
    allannots = []

    for (pageno, pdfpage) in enumerate(PDFPage.create_pages(doc)):
        page = Page(pageno, pdfpage.mediabox)
        pagesdict[pdfpage.pageid] = page
        if pdfpage.annots:
            # emit progress indicator
            if emit_progress:
                sys.stderr.write((" " if pageno > 0 else "") + "%d" % (pageno + 1))
                sys.stderr.flush()

            pdfannots = []
            for a in pdftypes.resolve1(pdfpage.annots):
                if isinstance(a, pdftypes.PDFObjRef):
                    pdfannots.append(a.resolve())
                else:
                    sys.stderr.write('Warning: unknown annotation: %s\n' % a)

            page.annots = getannots(pdfannots, page, codec)
            page.annots.sort()
            device.setannots(page.annots)
            interpreter.process_page(pdfpage)
            allannots.extend(page.annots)

    if emit_progress:
        sys.stderr.write("\n")

    outlines = []
    try:
        outlines = get_outlines(doc, pagesdict)
    except PDFNoOutlines:
        if emit_progress:
            sys.stderr.write("Document doesn't include outlines (\"bookmarks\")\n")
    except Exception as ex:
        sys.stderr.write("Warning: failed to retrieve outlines: %s\n" % ex)

    device.close()

    return (allannots, outlines)

def parse_args():
    p = argparse.ArgumentParser(description=__doc__)

    p.add_argument("input", metavar="INFILE", type=argparse.FileType("rb"),
                   help="PDF file to process")

    g = p.add_argument_group('Basic options')
    g.add_argument("-p", "--progress", default=False, action="store_true",
                   help="emit progress information")
    g.add_argument("-c", "--codec", default="cp1252", type=codecs.lookup,
                   help="text encoding for annotations (default: windows-1252)")
    g.add_argument("-o", metavar="OUTFILE", type=argparse.FileType("w"), dest="output",
                   default=sys.stdout, help="output file (default is stdout)")

    g = p.add_argument_group('Options controlling output format')
    allsects = ["highlights", "comments", "nits"]
    g.add_argument("-s", "--sections", metavar="SEC", nargs="*",
                   choices=allsects, default=allsects,
                   help=("sections to emit (default: %s)" % ', '.join(allsects)))
    g.add_argument("--no-group", dest="group", default=True, action="store_false",
                   help="emit annotations in order, don't group into sections")
    g.add_argument("-w", "--wrap", metavar="COLS", type=int,
                   help="wrap text at this many columns")

    return p.parse_args()

def main():
    args = parse_args()
    (annots, outlines) = process_file(args.input, args.codec, args.progress)
    prettyprint(annots, outlines, args.output, args.group, args.sections, args.wrap)
    return 0

if __name__ == "__main__":
    sys.exit(main())
