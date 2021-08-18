#!/usr/bin/env python3

import argparse
from datetime import datetime, timedelta, timezone
import functools
import json
import unittest
import operator
import pathlib
import typing

import pdfminer.layout

import pdfannots
import pdfannots.utils
from pdfannots.types import AnnotationType
from pdfannots.printer.markdown import MarkdownPrinter, GroupedMarkdownPrinter
from pdfannots.printer.json import JsonPrinter


class UnitTests(unittest.TestCase):
    def test_decode_datetime(self) -> None:
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
    filename: str

    # Permit a test to customise the columns_per_page or LAParams
    columns_per_page: typing.Optional[int] = None
    laparams = pdfminer.layout.LAParams()

    def setUp(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f, columns_per_page=self.columns_per_page,
                                              laparams=self.laparams)
            self.annots = [a for p in self.doc.pages for a in p.annots]
            self.outlines = [o for p in self.doc.pages for o in p.outlines]


class ExtractionTests(ExtractionTestBase):
    filename = 'hotos17.pdf'
    columns_per_page = 2  # for test_nearest_outline

    def test_annots(self) -> None:
        EXPECTED = [
            (0, AnnotationType.Squiggly, None, 'recent Intel CPUs have introduced'),
            (0, AnnotationType.Text, 'This is a note with no text attached.', None),
            (1, AnnotationType.Highlight, None,
             'TSX launched with "Haswell" in 2013 but was later disabled due to a bug. '
             '"Broadwell" CPUs with the bug fix shipped in late 2014.'),
            (1, AnnotationType.Highlight, 'This is lower in column 1',
             'user-mode access to FS/GS registers, and TLB tags for non-VM address spaces'),
            (1, AnnotationType.Highlight, 'This is at the top of column two',
             'The jump is due to extensions introduced with the "Skylake" microarchitecture'),
            (3, AnnotationType.Squiggly, 'This is a nit.',
             'Control transfer in x86 is already very complex'),
            (3, AnnotationType.Underline, 'This is a different nit',
             'Besides modifying semantics of all indirect control transfers'),
            (3, AnnotationType.StrikeOut, None,
             'While we may disagree with some of the design choices,')]

        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            assert a.pos is not None
            self.assertEqual(
                (a.pos.page.pageno, a.subtype, a.contents, a.gettext(remove_hyphens=True)),
                expected)
        self.assertEqual(self.annots[0].created, datetime(
            2019, 1, 19, 21, 29, 42, tzinfo=timezone(-timedelta(hours=8))))

    def test_outlines(self) -> None:
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

    def test_nearest_outline(self) -> None:
        # Page 1 (Introduction) Squiggly: "recent Intel CPUs have introduced"
        a = self.doc.pages[0].annots[0]
        assert a.pos is not None
        o = self.doc.nearest_outline(a.pos)
        assert o is not None
        self.assertEqual(o.title, 'Introduction')

        # Page 4 (Case study: CET) Squiggly: "Control transfer in x86 is already very complex"
        # Note: pdfminer gets this wrong as of 20201018; we must set columns_per_page to fix it
        a = self.doc.pages[3].annots[0]
        assert a.pos is not None
        o = self.doc.nearest_outline(a.pos)
        assert o is not None
        self.assertEqual(o.title, 'Case study: CET')


class Issue9(ExtractionTestBase):
    filename = 'issue9.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        a = self.annots[0]
        self.assertEqual(a.gettext(), 'World')


class Issue13(ExtractionTestBase):
    filename = 'issue13.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        a = self.annots[0]
        self.assertEqual(a.gettext(), 'This is a sample statement.')


class Pr24(ExtractionTestBase):
    filename = 'pr24.pdf'

    # Workaround for https://github.com/pdfminer/pdfminer.six/issues/658
    laparams = pdfminer.layout.LAParams(boxes_flow=None)

    def test(self) -> None:
        EXPECTED = [
            (AnnotationType.Highlight, 'long highlight',
             'Heading Link to heading that is working with vim-pandoc. Link to heading that'),
            (AnnotationType.Highlight, 'short highlight', 'not working'),
            (AnnotationType.Text, None, None),
            (AnnotationType.Highlight, None, 'Some more text'),
            (AnnotationType.Text, 's', None),
            (AnnotationType.Text, 'dual\n\npara note', None)]
        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual((a.subtype, a.contents, a.gettext()), expected)


class PrinterTestBase(unittest.TestCase):
    filename = 'hotos17.pdf'

    def setUp(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f)


class MarkdownPrinterTest(PrinterTestBase):
    # There's not a whole lot of value in testing the precise output format,
    # but let's make sure we produce a non-trivial result and don't crash.
    def test_flat(self) -> None:
        args = argparse.Namespace()
        args.printfilename = True
        args.remove_hyphens = False
        args.wrap = None
        args.condense = True

        p = MarkdownPrinter(args)

        linecount = 0
        charcount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 5)
        self.assertGreater(charcount, 500)

    def test_grouped(self) -> None:
        args = argparse.Namespace()
        args.printfilename = False
        args.remove_hyphens = True
        args.wrap = 80
        args.condense = True
        args.sections = GroupedMarkdownPrinter.ALL_SECTIONS

        p = GroupedMarkdownPrinter(args)

        linecount = 0
        charcount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 10)
        self.assertGreater(charcount, 900)


class JsonPrinterTest(PrinterTestBase):
    def test_flat(self) -> None:
        args = argparse.Namespace()
        args.printfilename = False
        args.remove_hyphens = False
        p = JsonPrinter(args)

        j = json.loads(
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())

        self.assertTrue(isinstance(j, list))
        self.assertEqual(len(j), 8)

    def test_files(self) -> None:
        args = argparse.Namespace()
        args.printfilename = True
        args.remove_hyphens = False
        p = JsonPrinter(args)

        # print the same file twice
        s = p.begin()
        for _ in range(2):
            s += functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
        s += p.end()

        j = json.loads(s)

        self.assertTrue(isinstance(j, list))
        self.assertEqual(len(j), 2)
        self.assertEqual(j[0], j[1])


if __name__ == "__main__":
    unittest.main()
