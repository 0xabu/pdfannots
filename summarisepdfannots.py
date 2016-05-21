#!/usr/bin/python

from __future__ import print_function
import sys
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LAParams, LTContainer, LTPage, LTAnno, LTText, LTChar, LTTextLine, LTTextBox
from pdfminer.converter import TextConverter
from pdfminer.pdfparser import PDFParser
from pdfminer.pdfdocument import PDFDocument
from pdfminer.psparser import PSLiteralTable
import pdfminer.pdftypes as pdftypes

class RectExtractor(TextConverter):
    def __init__(self, rsrcmgr, codec='utf-8', pageno=1, laparams=None):
        TextConverter.__init__(self, rsrcmgr, outfp=None, codec=codec, pageno=pageno, laparams=laparams)
        self.annots = []

    def setcoords(self, annots):
        self.annots = [a for a in annots if a.boxes]
        self._lasttestpassed = None

    def testboxes(self, item):
        def testbox(item, box):
            (x0, y0, x1, y1) = box
            return ((item.x0 >= x0 and item.y0 >= y0 and item.x0 <= x1 and item.y0 <= y1) or
                    (item.x1 >= x0 and item.y0 >= y0 and item.x1 <= x1 and item.y0 <= y1))

        for a in self.annots:
            if any([testbox(item, b) for b in a.boxes]):
                self._lasttestpassed = a
                return a

    def receive_layout(self, ltpage):
        def render(item):
            if isinstance(item, LTContainer):
                for child in item:
                    render(child)
            elif isinstance(item, LTAnno):
                if self._lasttestpassed:
                    self._lasttestpassed.capture(item.get_text())
            elif isinstance(item, LTText):
                a = self.testboxes(item)
                if a:
                    a.capture(item.get_text())
            if isinstance(item, LTTextBox):
                a = self.testboxes(item)
                if a:
                    a.capture('\n')

        render(ltpage)

class Annotation:
    def __init__(self, pageno, tagname, coords=None, rect=None, contents=None):
        self.pageno = pageno
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
            assert(len(coords) % 8 == 0)
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
            # kludge for latex: elide hyphens, join lines
            if self.text.endswith('-'):
                self.text = self.text[:-1]
            else:
                self.text += ' '
        else:
            self.text += text

    def gettext(self):
        if self.text:
            return self.text.strip()
        else:
            return None

    def getstartpos(self):
        if self.rect:
            (x0, y0, x1, y1) = self.rect
        elif self.boxes:
            (x0, y0, x1, y1) = self.boxes[0]
        else:
            return None
        return (min(x0, x1), max(y0, y1)) # assume left-to-right top-to-bottom text :)

ANNOT_SUBTYPES = set(['Text', 'Highlight', 'Squiggly', 'StrikeOut'])

def getannots(pdfannots, pageno):
    annots = []
    for pa in pdfannots:
        subtype = pa.get('Subtype')
        if subtype is not None and subtype.name not in ANNOT_SUBTYPES:
            continue

        a = Annotation(pageno, subtype.name.lower(), pa.get('QuadPoints'), pa.get('Rect'), pa.get('Contents'))
        annots.append(a)

    return annots

def nearest_outline(outlines, mediaboxes, pageno, (x, y)):
    prev = None
    for o in outlines:
        if o.pageno < pageno:
            prev = o
        elif o.pageno > pageno:
            return prev
        else:
            # XXX: assume two-column left-to-right top-to-bottom documents
            (x0, y0, x1, y1) = mediaboxes[pageno]
            assert(o.x >= x0 and o.x <= x1)
            assert(x >= x0 and x <= x1)
            colwidth = (x1 - x0) / 2
            outline_col = (o.x - x0) // colwidth
            pos_col = (x - x0) // colwidth
            if outline_col > pos_col or (outline_col == pos_col and o.y < y):
                return prev
            else:
                prev = o
    return prev


def prettyprint(annots, outlines, mediaboxes):

    def fmtpos(annot):
        apos = annot.getstartpos()
        if apos:
            o = nearest_outline(outlines, mediaboxes, annot.pageno, apos)
        else:
            o = None
        if o:
            return "Page %d (%s):" % (annot.pageno + 1, o.title)
        else:
            return "Page %d:" % (annot.pageno + 1)

    def fmttext(annot):
        if a.gettext():
            return '"%s"' % a.gettext()
        else:
            return ''

    nits = [a for a in annots if a.tagname in ['squiggly', 'strikeout']]
    comments = [a for a in annots if a.tagname in ['highlight', 'text'] and a.contents]
    highlights = [a for a in annots if a.tagname == 'highlight' and a.contents is None]
    
    if highlights:
        print("Highlights:")
        for a in highlights:
            print(fmtpos(a), fmttext(a), "\n")

    if comments:
        print("\nDetailed comments:")
        for a in comments:
            text = fmttext(a)
            if text:
                # XXX: lowercase the first word, to join it to the "Regarding" sentence
                contents = a.contents
                firstword = contents.split()[0]
                if firstword != 'I' and not firstword.startswith("I'"):
                    contents = contents[0].lower() + contents[1:]
                print(fmtpos(a), "Regarding", text + ",", contents, "\n")
            else:
                print(fmtpos(a), a.contents, "\n")

    if nits:
        print("\nNits:")
        for a in nits:
            if a.contents:
                print(fmtpos(a), "\"%s\" -> %s" % (a.gettext(), a.contents))
            else:
                print(fmtpos(a), "\"%s\"" % a.gettext())

def resolve_dest(doc, dest):
    if isinstance(dest, str):
        dest = pdftypes.resolve1(doc.get_dest(dest))
    elif isinstance(dest, PSLiteral):
        dest = pdftypes.resolve1(doc.get_dest(dest.name))
    if isinstance(dest, dict):
        dest = dest['D']
    return dest

class Outline:
    def __init__(self, title, dest, pageno, x, y):
        self.title = title
        self.dest = dest
        self.pageno = pageno
        self.x = x
        self.y = y

def get_outlines(doc, pagesdict):
    result = []
    for (level, title, destname, actionref, _) in doc.get_outlines():
        if destname is None and actionref:
            action = actionref.resolve()
            if isinstance(action, dict):
                subtype = action.get('S')
                if subtype is PSLiteralTable.intern('GoTo'):
                    destname = action.get('D')
        if destname is None:
            continue
        dest = resolve_dest(doc, destname)
        pageno = pagesdict[dest[0].objid]
        (_, _, targetx, targety, _) = dest
        result.append(Outline(title, destname, pageno, targetx, targety))
    return result

def main(pdffile):
    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    device = RectExtractor(rsrcmgr, laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    fp = file(pdffile, 'rb')
    parser = PDFParser(fp)
    doc = PDFDocument(parser)

    pagesdict = {}
    mediaboxes = {}
    allannots = []

    for (pageno, page) in enumerate(PDFPage.create_pages(doc)):
        pagesdict[page.pageid] = pageno
        mediaboxes[pageno] = page.mediabox
        if page.annots is None or page.annots is []:
            continue
        sys.stderr.write((" " if pageno > 0 else "") + "%d" % (pageno + 1))
        pdfannots = [ar.resolve() for ar in pdftypes.resolve1(page.annots)]
        pageannots = getannots(pdfannots, pageno)
        device.setcoords(pageannots)
        interpreter.process_page(page)
        allannots.extend(pageannots)
    sys.stderr.write("\n")

    try:
        outlines = get_outlines(doc, pagesdict)
    except:
        e = sys.exc_info()[0]
        sys.stderr.write("Warning: failed to retrieve outlines: %s\n" % e) 
        outlines = []

    device.close()
    fp.close()

    prettyprint(allannots, outlines, mediaboxes)

if __name__ == "__main__":
    main(sys.argv[1])
