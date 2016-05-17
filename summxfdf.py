#!/usr/bin/python3

import sys
import xml.etree.ElementTree as ET
from pdfminer.pdfinterp import PDFResourceManager, PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.layout import LAParams, LTContainer, LTPage, LTAnno, LTText, LTChar, LTTextLine, LTTextBox
from pdfminer.converter import TextConverter

class RectExtractor(TextConverter):
    def __init__(self, rsrcmgr, coords_str, codec='utf-8', pageno=1, laparams=None):
        TextConverter.__init__(self, rsrcmgr, outfp=None, codec=codec, pageno=pageno, laparams=laparams)
        coords = map(float, coords_str.split(','))
        assert(len(coords) % 8 == 0)
        self.boxes = []
        while coords != []:
            (x0,y0,x1,y1,x2,y2,x3,y3) = coords[:8]
            coords = coords[8:]
            xvals = [x0, x1, x2, x3]
            yvals = [y0, y1, y2, y3]
            box = (min(xvals), min(yvals), max(xvals), max(yvals))
            self.boxes.append(box)

        self._lasttestpassed = False
        self.captured_text = ''

    def testboxes(self, item):
        def testbox(item, box):
            (x0, y0, x1, y1) = box
            return ((item.x0 >= x0 and item.y0 >= y0 and item.x0 <= x1 and item.y0 <= y1) or
                    (item.x1 >= x0 and item.y0 >= y0 and item.x1 <= x1 and item.y0 <= y1))

        result = any(map(lambda box: testbox(item, box), self.boxes))
        self._lasttestpassed = result
        return result

    def capture(self, text):
        if text == '\n':
            # kludge for latex: elide hyphens
            if self.captured_text.endswith('-'):
                self.captured_text = self.captured_text[:-1]
            else:
                self.captured_text += ' '
        else:
            self.captured_text += text

    def receive_layout(self, ltpage):
        def render(item):
            #print item
            if isinstance(item, LTContainer):
                for child in item:
                    render(child)
            elif isinstance(item, LTAnno):
                if self._lasttestpassed:
                    self.capture(item.get_text())
            elif isinstance(item, LTText):
                if self.testboxes(item):
                    self.capture(item.get_text())
            if isinstance(item, LTTextBox):
                if self.testboxes(item):
                    self.capture('\n')

        render(ltpage)

    def getresult(self):
        return self.captured_text.strip()

class MyPDFExtractor:
    def __init__(self, pdffile):
        self.rsrcmgr = PDFResourceManager()
        self.laparams = LAParams()
        self.fp = file(pdffile, 'rb')

    def extracttext(self, pageno, coords):
        device = RectExtractor(self.rsrcmgr, coords, codec='utf-8', laparams=self.laparams)
        interpreter = PDFPageInterpreter(self.rsrcmgr, device)
        for page in PDFPage.get_pages(self.fp, {pageno}):
            interpreter.process_page(page)
        result = device.getresult()
        device.close()
        return result

    def close(self):
        self.fp.close()

XFDFURI = "http://ns.adobe.com/xfdf/"
NS = {"xfdf": XFDFURI}

def main(xfdffile, pdffile):
    tree = ET.parse(xfdffile)
    pdfex = MyPDFExtractor(pdffile)
    root = tree.getroot()
    annots = root.find("./xfdf:annots", NS)
    for n in annots.findall("./*/xfdf:contents/..", NS):
        tagname = n.tag.replace("{" + XFDFURI + "}", "", 1)
        if tagname not in ['highlight', 'text']:
            continue
        pageno = int(n.get("page"))
        contents = n.find("xfdf:contents", NS)
        coords = n.get("coords")
        if coords:
            text = pdfex.extracttext(pageno, coords)
            print("Page %s: Regarding \"%s\", %s\n" % (pageno + 1, text, contents.text))
        else:
            print("Page %s: %s\n" % (pageno + 1, contents.text))

    print("\nNits:\n")
    for n in annots:
        tagname = n.tag.replace("{" + XFDFURI + "}", "", 1)
        if tagname not in ['squiggly', 'strikeout']:
            continue
        pageno = int(n.get("page"))
        contents = n.find("xfdf:contents", NS)
        coords = n.get("coords")
        text = pdfex.extracttext(pageno, coords)
        if contents is not None:
            print("Page %s: \"%s\" -> %s\n" % (pageno + 1, text, contents.text))
        else:
            print("Page %s: \"%s\"\n" % (pageno + 1, text))

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
