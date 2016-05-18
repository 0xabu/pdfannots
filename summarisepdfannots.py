#!/usr/bin/python

from __future__ import print_function
import sys
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LAParams, LTContainer, LTPage, LTAnno, LTText, LTChar, LTTextLine, LTTextBox
from pdfminer.converter import TextConverter

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
            if any(map(lambda box: testbox(item, box), a.boxes)):
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
    def __init__(self, pageno, tagname, coords=None, contents=None):
        self.pageno = pageno
        self.tagname = tagname
        if contents == '':
            self.contents = None
        else:
            self.contents = contents
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
        return self.text.strip()

    def getpos(self):
        return "Page %d:" % (self.pageno + 1)


ANNOT_SUBTYPES = set(['Text', 'Highlight', 'Squiggly', 'StrikeOut'])

def getannots(pdfannots, pageno):
    annots = []
    for pa in pdfannots:
        subtype = pa.get('Subtype')
        if subtype is not None and subtype.name not in ANNOT_SUBTYPES:
            continue

        a = Annotation(pageno, subtype.name.lower(), pa.get('QuadPoints'), pa.get('Contents'))
        annots.append(a)

    return annots


def prettyprint(annots):
    nits = [a for a in annots if a.tagname in ['squiggly', 'strikeout']]
    comments = [a for a in annots if a.tagname in ['highlight', 'text'] and a.contents]
    highlights = [a for a in annots if a.tagname == 'highlight' and a.contents is None]

    if highlights:
        print("Highlights:")
        for a in highlights:
            print(a.getpos(), "\"%s\"\n" % a.gettext())

    if comments:
        print("\nDetailed comments:")
        for a in comments:
            if a.text:
                print(a.getpos(), "Regarding \"%s\"," % a.gettext(), a.contents, "\n")
            else:
                print(a.getpos(), a.contents, "\n")

    if nits:
        print("\nNits:")
        for a in nits:
            if a.contents:
                print(a.getpos(), "\"%s\" -> %s" % (a.gettext(), a.contents))
            else:
                print(a.getpos(), "\"%s\"" % a.gettext())


def main(pdffile):
    rsrcmgr = PDFResourceManager()
    laparams = LAParams()
    fp = file(pdffile, 'rb')
    device = RectExtractor(rsrcmgr, codec='utf-8', laparams=laparams)
    interpreter = PDFPageInterpreter(rsrcmgr, device)
    allannots = []

    for (pageno, page) in enumerate(PDFPage.get_pages(fp)):
        if page.annots is None or page.annots is []:
            continue
        sys.stderr.write((" " if pageno > 0 else "") + "%d" % (pageno + 1))
        pdfannots = [ar.resolve() for ar in page.annots]
        pageannots = getannots(pdfannots, pageno)
        device.setcoords(pageannots)
        interpreter.process_page(page)
        allannots.extend(pageannots)
    sys.stderr.write("\n")

    device.close()
    fp.close()

    prettyprint(allannots)

if __name__ == "__main__":
    main(sys.argv[1])
