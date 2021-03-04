#!/usr/bin/env python3

import unittest, pathlib
import pdfannots

class ExtractionTestBase(unittest.TestCase):
    def setUp(self):
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            (annots, outlines) = pdfannots.process_file(f)
            self.annots = annots
            self.outlines = outlines

class ExtractionTests(ExtractionTestBase):
    filename = 'hotos17.pdf'

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
        self.assertEqual(
            [o.title for o in self.outlines],
            ['Introduction',
             'Background: x86 extensions',
             'Case study: SGX',
             'Case study: CET',
             'Implications',
             'Concluding remarks'])

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

if __name__ == "__main__":
    unittest.main()
