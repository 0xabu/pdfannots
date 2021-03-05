#!/usr/bin/env python3

import unittest, pathlib
import pdfannots

class ExtractionTestBase(unittest.TestCase):
    columns_per_page = 1

    def setUp(self):
        pdfannots.COLUMNS_PER_PAGE = self.columns_per_page

        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            (annots, outlines) = pdfannots.process_file(f)
            self.annots = annots
            self.outlines = outlines

class ExtractionTests(ExtractionTestBase):
    filename = 'hotos17.pdf'
    columns_per_page = 2

    def test_annots(self):
        EXPECTED = [
            (0, 'Squiggly', None, 'recent Intel CPUs have introduced'),
            (0, 'Text', 'This is a note with no text attached.', None),
            (1, 'Highlight', None, 'TSX launched with "Haswell" in 2013 but was later disabled due to a bug. "Broadwell" CPUs with the bug fix shipped in late 2014.'),
            (1, 'Highlight', 'This is lower in column 1', 'user-mode access to FS/GS registers, and TLB tags for non-VM address spaces'),
            (1, 'Highlight', 'This is at the top of column two', 'The jump is due to extensions introduced with the "Skylake" microarchitecture'),
            (3, 'Squiggly', 'This is a nit.', 'Control transfer in x86 is already very complex'),
            (3, 'Underline', 'This is a different nit', 'Besides modifying semantics of all indirect control transfers'),
            (3, 'StrikeOut', None, 'While we may disagree with some of the design choices,')]

        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual((a.page.pageno, a.tagname, a.contents, a.gettext()), expected)

    def test_outlines(self):
        EXPECTED = [
            'Introduction',
            'Background: x86 extensions',
            'Case study: SGX',
            'Case study: CET',
            'Implications',
            'Concluding remarks']

        self.assertEqual(len(self.outlines), len(EXPECTED))
        for o, expected in zip(self.outlines, EXPECTED):
            self.assertEqual(o.title, expected)

class Issue9(ExtractionTestBase):
    filename = 'issue9.pdf'

    def test(self):
        self.assertEqual(len(self.annots), 1)
        a = self.annots[0]
        self.assertEqual(a.gettext(), 'World')

class Issue13(ExtractionTestBase):
    filename = 'issue13.pdf'

    def test(self):
        self.assertEqual(len(self.annots), 1)
        a = self.annots[0]
        self.assertEqual(a.gettext(), 'This is a sample statement.')

class Pr24(ExtractionTestBase):
    filename = 'pr24.pdf'

    def test(self):
        EXPECTED = [
            ('Highlight', 'long highlight', 'Link to heading that is working with vim-pandoc. Link to heading that Heading'), # BUG: Heading is captured out of order!
            ('Highlight', 'short highlight', 'not working'),
            ('Text', None, None),
            ('Highlight', None, 'Some more text'),
            ('Text', 's', None),
            ('Text', 'dual\n\npara note', None)]

        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual((a.tagname, a.contents, a.gettext()), expected)

if __name__ == "__main__":
    unittest.main()
