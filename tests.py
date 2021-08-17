#!/usr/bin/env python3
# mypy: ignore-errors

import argparse
from datetime import datetime, timedelta, timezone
import unittest
import pathlib
import pdfminer.layout
import pdfannots
import pdfannots.utils
from pdfannots.printer.markdown import MarkdownPrinter, GroupedMarkdownPrinter


class UnitTests(unittest.TestCase):
    def test_decode_datetime(self):
        datas = [
            ("D:123456", None),  # defensive on bad datetimes
            ("D:20190119212926-08'00'",
             datetime(2019, 1, 19, 21, 29, 26, tzinfo=timezone(-timedelta(hours=8)))),
            ("20200102030405Z0000",
             datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)),
            ("D:20101112191817", datetime(2010, 11, 12, 19, 18, 17)),
        ]
        for dts, expected in datas:
            dt = pdfannots.utils.decode_datetime(dts)
            self.assertEqual(dt, expected)


class ExtractionTestBase(unittest.TestCase):
    # Permit a test to customise the columns_per_page or LAParams
    columns_per_page = None
    laparams = pdfminer.layout.LAParams()

    def setUp(self):
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f, columns_per_page=self.columns_per_page,
                                              laparams=self.laparams)
            self.annots = [a for p in self.doc.pages for a in p.annots]
            self.outlines = [o for p in self.doc.pages for o in p.outlines]


class ExtractionTests(ExtractionTestBase):
    filename = 'hotos17.pdf'
    columns_per_page = 2  # for test_nearest_outline

    def test_annots(self):
        EXPECTED = [
            (0, 'Squiggly', None, 'recent Intel CPUs have introduced'),
            (0, 'Text', 'This is a note with no text attached.', None),
            (1, 'Highlight', None,
             'TSX launched with "Haswell" in 2013 but was later disabled due to a bug. '
             '"Broadwell" CPUs with the bug fix shipped in late 2014.'),
            (1, 'Highlight', 'This is lower in column 1',
             'user-mode access to FS/GS registers, and TLB tags for non-VM address spaces'),
            (1, 'Highlight', 'This is at the top of column two',
             'The jump is due to extensions introduced with the "Skylake" microarchitecture'),
            (3, 'Squiggly', 'This is a nit.',
             'Control transfer in x86 is already very complex'),
            (3, 'Underline', 'This is a different nit',
             'Besides modifying semantics of all indirect control transfers'),
            (3, 'StrikeOut', None, 'While we may disagree with some of the design choices,')]

        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual(
                (a.pos.page.pageno, a.tagname, a.contents, a.gettext()), expected)
        self.assertEqual(self.annots[0].created, datetime(
            2019, 1, 19, 21, 29, 42, tzinfo=timezone(-timedelta(hours=8))))

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

    def test_nearest_outline(self):
        # Page 1 (Introduction) Squiggly: "recent Intel CPUs have introduced"
        o = self.doc.nearest_outline(self.doc.pages[0].annots[0].pos)
        self.assertIsNotNone(o)
        self.assertEqual(o.title, 'Introduction')

        # Page 4 (Case study: CET) Squiggly: "Control transfer in x86 is already very complex"
        # Note: pdfminer gets this wrong as of 20201018; we must set columns_per_page to fix it
        o = self.doc.nearest_outline(self.doc.pages[3].annots[0].pos)
        self.assertIsNotNone(o)
        self.assertEqual(o.title, 'Case study: CET')


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

    # Workaround for https://github.com/pdfminer/pdfminer.six/issues/658
    laparams = pdfminer.layout.LAParams(boxes_flow=None)

    def test(self):
        EXPECTED = [
            ('Highlight', 'long highlight',
             'Heading Link to heading that is working with vim-pandoc. Link to heading that'),
            ('Highlight', 'short highlight', 'not working'),
            ('Text', None, None),
            ('Highlight', None, 'Some more text'),
            ('Text', 's', None),
            ('Text', 'dual\n\npara note', None)]
        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual((a.tagname, a.contents, a.gettext()), expected)


class PrinterTestBase(unittest.TestCase):
    filename = 'hotos17.pdf'

    def setUp(self):
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f)


class MarkdownPrinterTest(PrinterTestBase):
    # There's not a whole lot of value in testing the precise output format,
    # but let's make sure we produce a non-trivial result and don't crash.
    def test_flat(self):
        args = argparse.Namespace()
        args.printfilename = True
        args.wrap = None
        args.condense = True

        p = MarkdownPrinter(args)

        linecount = 0
        charcount = 0
        for line in p('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 5)
        self.assertGreater(charcount, 500)

    def test_grouped(self):
        args = argparse.Namespace()
        args.printfilename = False
        args.wrap = 80
        args.condense = True
        args.sections = GroupedMarkdownPrinter.ALL_SECTIONS

        p = GroupedMarkdownPrinter(args)

        linecount = 0
        charcount = 0
        for line in p('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 10)
        self.assertGreater(charcount, 900)


if __name__ == "__main__":
    unittest.main()
