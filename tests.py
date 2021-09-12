#!/usr/bin/env python3

import argparse
import csv
import functools
import json
import operator
import pathlib
import typing
import unittest
from datetime import datetime, timedelta, timezone
from io import StringIO

import pdfminer.layout

import pdfannots
import pdfannots.utils
from pdfannots.printer.csv import CsvPrinter
from pdfannots.printer.json import JsonPrinter
from pdfannots.printer.jsonl import JsonlPrinter
from pdfannots.printer.markdown import GroupedMarkdownPrinter, MarkdownPrinter
from pdfannots.printer.todocsv import TodocsvPrinter
from pdfannots.types import AnnotationType


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

    def assertEndsWith(self, bigstr: str, suffix: str) -> None:
        self.assertEqual(bigstr[-len(suffix):], suffix)

    def assertStartsWith(self, bigstr: str, prefix: str) -> None:
        self.assertEqual(bigstr[:len(prefix)], prefix)


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


class Landscape2Column(ExtractionTestBase):
    filename = 'word2column.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 9)

        a = self.annots[0]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'nostrud exercitation')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(
            pre, 'Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor '
            'incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis ')
        self.assertStartsWith(
            post, ' ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor')

        a = self.annots[1]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'Duis')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(pre, 'ullamco laboris nisi ut aliquip ex ea commodo consequat. ')
        self.assertStartsWith(
            post, ' aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu '
            'fugiat nulla pariatur.')

        a = self.annots[2]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'laborum')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(pre, ', sunt in culpa qui officia deserunt mollit anim id est ')
        self.assertStartsWith(post, '. Heading 2 Sed ut perspiciatis,')

        a = self.annots[3]
        self.assertEqual(a.subtype, AnnotationType.Highlight)
        self.assertEqual(
            a.gettext(), 'At vero eos et accusamus et iusto odio dignissimos ducimus, qui '
            'blanditiis praesentium voluptatum deleniti atque corrupti,')
        self.assertFalse(a.has_context())

        a = self.annots[4]
        self.assertEqual(a.subtype, AnnotationType.Squiggly)
        self.assertEqual(
            a.gettext(), 'Itaque earum rerum hic tenetur a sapiente delectus, ut aut reiciendis '
            'voluptatibus maiores alias consequatur aut perferendis doloribus asperiores repellat.')
        self.assertEqual(a.contents, 'Nonsense!')
        self.assertFalse(a.has_context())

        a = self.annots[5]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'equal')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(pre, 'the pain and trouble that are bound to ensue; and ')
        self.assertStartsWith(post, ' blame belongs to those who fail in their')  # end of page

        a = self.annots[6]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'duty')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEqual(pre, '')  # start of page
        self.assertStartsWith(post, ' through weakness of will, which')

        a = self.annots[7]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'In a free hour,')
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(pre, 'These cases are perfectly simple and easy to distinguish. ')
        self.assertStartsWith(post, ' when our power of choice is untrammeled and when nothing')


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

    def test_printfile(self) -> None:
        args = argparse.Namespace()
        args.printfilename = True
        args.remove_hyphens = False
        p = JsonPrinter(args)

        j = json.loads(
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())

        self.assertTrue(isinstance(j, dict))
        self.assertTrue('dummyfile' in j)
        self.assertTrue(isinstance(j['dummyfile'], list))
        self.assertEqual(len(j['dummyfile']), 8)


class JsonlPrinterTest(PrinterTestBase):
    def test_flat(self) -> None:
        args = argparse.Namespace()
        args.remove_hyphens = False
        p = JsonlPrinter(args)

        j = json.loads(
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())

        self.assertTrue(isinstance(j, dict))
        self.assertEqual(j.get('file', ''), 'dummyfile')
        self.assertEqual(len(j.get('annotations', [])), 8)

    def test_multiple(self) -> None:
        args = argparse.Namespace()
        args.remove_hyphens = False
        p = JsonlPrinter(args)

        output = (
            p.begin()
            + functools.reduce(operator.add, p.print_file('a.pdf', self.doc))
            + functools.reduce(operator.add, p.print_file('b.pdf', self.doc))
            + p.end()).splitlines()

        self.assertEqual(len(output), 2)

        a = json.loads(output[0])
        b = json.loads(output[1])

        self.assertTrue(isinstance(a, dict))
        self.assertEqual(a.get('file', ''), 'a.pdf')
        self.assertEqual(len(a.get('annotations', [])), 8)

        self.assertTrue(isinstance(b, dict))
        self.assertEqual(b.get('file', ''), 'b.pdf')
        self.assertEqual(len(b.get('annotations', [])), 8)


class CsvPrinterTest(PrinterTestBase):
    def test_flat(self) -> None:
        args = argparse.Namespace()
        args.printfilename = True
        args.remove_hyphens = False
        p = CsvPrinter(args)

        out = (
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())
        f = StringIO(out)
        reader = csv.DictReader(f)
        result = list(reader)

        self.assertEqual(len(result), 8)
        self.assertEqual(result[0]['filename'], 'dummyfile')
        self.assertEqual(result[0]['text'], 'recent Intel CPUs have introduced')


class TodocsvPrinterTest(PrinterTestBase):
    def test_flat(self) -> None:
        args = argparse.Namespace()
        args.printfilename = True
        args.remove_hyphens = False
        p = TodocsvPrinter(args)

        out = (
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())
        f = StringIO(out)
        reader = csv.DictReader(f)
        result = list(reader)

        self.assertEqual(len(result), 8)

        self.assertEqual(result[0]['filename'], 'dummyfile')
        self.assertEqual(result[0]['location'], 'p1: Introduction')
        self.assertEqual(result[0]['context'], 'recent Intel CPUs have introduced')
        self.assertEqual(result[0]['explanation'], '')

        self.assertEqual(result[1]['filename'], 'dummyfile')
        self.assertEqual(result[1]['location'], 'p1: Introduction')
        self.assertEqual(result[1]['context'], '-')
        self.assertEqual(result[1]['explanation'], 'This is a note with no text attached.')


if __name__ == "__main__":
    unittest.main()
