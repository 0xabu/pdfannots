#!/usr/bin/env python3

import functools
import json
import operator
import pathlib
import re
import sys
import typing as typ
import unittest
from datetime import datetime, timedelta, timezone

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
    columns_per_page: typ.Optional[int] = None
    laparams = pdfminer.layout.LAParams()

    def setUp(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f, columns_per_page=self.columns_per_page,
                                              laparams=self.laparams)
            self.annots = [a for p in self.doc.pages for a in p.annots]
            self.outlines = [o for p in self.doc.pages for o in p.outlines]

    if sys.version_info < (3, 14):
        def assertEndsWith(self, bigstr: str, suffix: str) -> None:
            self.assertEqual(bigstr[-len(suffix):], suffix)

    if sys.version_info < (3, 14):
        def assertStartsWith(self, bigstr: str, prefix: str) -> None:
            self.assertEqual(bigstr[:len(prefix)], prefix)


class ExtractionTests(ExtractionTestBase):
    filename = 'hotos17.pdf'
    columns_per_page = 2  # for test_nearest_outline

    def test_annots(self) -> None:
        EXPECTED = [
            (0, AnnotationType.Squiggly, None, 'recent Intel CPUs have introduced'),
            (0, AnnotationType.Text, 'This is a note with no text attached.', None),
            (0, AnnotationType.StrikeOut, None, 'e'),
            (1, AnnotationType.Highlight, None,
             'TSX launched with "Haswell" in 2013 but was later disabled due to a bug. '
             '"Broadwell" CPUs with the bug fix shipped in late 2014.'),
            (1, AnnotationType.Highlight, 'This is lower in column 1',
             'user-mode access to FS/GS registers, and TLB tags for non-VM address spaces'),
            (1, AnnotationType.Highlight, None,
             'segmentation, task switching, and 16-bit modes.'),
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

        # test for correct whitespace on the strikeout annot
        a = self.annots[2]
        self.assertTrue(a.has_context())
        (pre, post) = a.get_context()
        self.assertEndsWith(pre, 'widths, ar')
        self.assertStartsWith(post, ' counted')

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


class Issue46(ExtractionTestBase):
    filename = 'issue46.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 3)

        self.assertEqual(self.annots[0].subtype, AnnotationType.Highlight)
        self.assertEqual(self.annots[0].gettext(), 'C – Curate')

        self.assertEqual(self.annots[1].subtype, AnnotationType.Square)
        self.assertEqual(self.annots[1].gettext(), None)

        self.assertEqual(self.annots[2].subtype, AnnotationType.Highlight)
        self.assertEqual(self.annots[2].gettext(), 'This was a novel idea at the time')


class Issue61(ExtractionTestBase):
    filename = 'issue61.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        a = self.annots[0]
        self.assertEqual(a.subtype, AnnotationType.Caret)
        self.assertEqual(a.contents, 'and machine learning')
        self.assertTrue(a.has_context())


class Pr24(ExtractionTestBase):
    filename = 'pr24.pdf'

    def test(self) -> None:
        EXPECTED = [
            (AnnotationType.Highlight, 'long highlight',
             'Heading Link to heading that is working with vim-pandoc. Link to heading that'),
            (AnnotationType.Highlight, 'short highlight', 'not working'),
            (AnnotationType.Text, None, None),
            (AnnotationType.Highlight, None, 'Some more text'),
            (AnnotationType.Text, 'dual\n\npara note', None),
            (AnnotationType.Text, 's', None)]
        self.assertEqual(len(self.annots), len(EXPECTED))
        for a, expected in zip(self.annots, EXPECTED):
            self.assertEqual((a.subtype, a.contents, a.gettext()), expected)


class Issue121(ExtractionTestBase):
    filename = 'issue121.pdf'

    def test(self) -> None:
        self.assertTrue(self.annots)  # and we didn't crash


class Issue132(ExtractionTestBase):
    filename = 'issue132.pdf'

    def test(self) -> None:
        self.assertTrue(self.annots)  # and we didn't crash


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


class FreeTextAnnotation(ExtractionTestBase):
    filename = 'FreeText-annotation.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        self.assertEqual(self.annots[0].subtype, AnnotationType.FreeText)
        self.assertEqual(self.annots[0].contents, 'Annotation with subtype "FreeText".')
        self.assertEqual(self.annots[0].gettext(), None)


class IndirectObjects(ExtractionTestBase):
    # /Subtype and /Contents of the annotation are indirect objects
    filename = 'indirect-objects.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        self.assertEqual(self.annots[0].subtype, AnnotationType.Text)
        self.assertEqual(self.annots[0].contents, 'A comment stored as an indirect object')


class SwappedCorners(ExtractionTestBase):
    # /MediaBox and the caret's /Rect are given by their upper-left and lower-right corners
    filename = 'swapped-corners.pdf'

    def test(self) -> None:
        self.assertEqual(self.doc.pages[0].mediabox.get_coords(), (0, 0, 300, 300))
        self.assertEqual(len(self.annots), 1)
        self.assertEqual(self.annots[0].subtype, AnnotationType.Caret)
        self.assertEqual(self.annots[0].boxes[0].get_coords(), (50, 250, 70, 270))


class RotatedPages(ExtractionTestBase):
    # Pages with /Rotate 0, 90, 180 and 270, and one whose /MediaBox does not start at
    # (0, 0), each with a highlight over its first line, as in pdfplumber's
    # annotations-rotated-90.pdf
    filename = 'rotated-pages.pdf'

    def test(self) -> None:
        self.assertEqual([a.gettext() for a in self.annots], [
            'Page 1, not rotated',
            'Page 2, rotated by 90',
            'Page 3, rotated by 180',
            'Page 4, rotated by 270',
            'Page 5, with its origin moved',
        ])


class DanglingOutlines(ExtractionTestBase):
    # A 3-page excerpt of a US FDA guidance document, from the ICDAR 2013 table
    # competition dataset. Its 5 outlines refer to pages that were not extracted.
    filename = 'excerpt-with-dangling-outlines.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.doc.pages), 3)
        self.assertEqual(self.outlines, [])

    def test_warns(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with self.assertLogs('pdfannots', level='WARNING') as logs, path.open('rb') as f:
            pdfannots.process_file(f)
        self.assertEqual(sum('Ignoring outline' in line for line in logs.output), 5)


class MissingNamedDestination(ExtractionTestBase):
    # The second of three outlines refers to a named destination that the
    # document doesn't define, as in pypdf's outlines-with-invalid-destinations.pdf
    filename = 'missing-named-destination.pdf'

    def test(self) -> None:
        self.assertEqual([o.title for o in self.outlines], ['Chapter 1', 'Chapter 3'])

    def test_warns(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with self.assertLogs('pdfannots', level='WARNING') as logs, path.open('rb') as f:
            pdfannots.process_file(f)
        self.assertEqual(sum("Ignoring outline 'Chapter 2'" in line for line in logs.output), 1)


class AnnotsEntriesWithoutSubtype(ExtractionTestBase):
    # /Annots also lists a link's action dictionary and a border array, as in
    # PyMuPDF's test_2861.pdf (https://github.com/pymupdf/PyMuPDF/issues/2861)
    filename = 'annots-entries-without-subtype.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 1)
        self.assertEqual(self.annots[0].subtype, AnnotationType.Text)
        self.assertEqual(self.annots[0].contents,
                         'A comment after two entries that are not annotations')


class CaretAnnotations(ExtractionTestBase):
    filename = 'caret.pdf'

    def test(self) -> None:
        self.assertEqual(len(self.annots), 5)
        a = self.annots[0]
        self.assertEqual(a.subtype, AnnotationType.StrikeOut)
        self.assertEqual(a.gettext(), 'Adobe Acrobat Reader')
        self.assertTrue(a.is_group_child)
        self.assertEqual(a.group_children, [])
        g = self.annots[3]
        self.assertEqual(g.subtype, AnnotationType.Caret)
        self.assertEqual(g.contents, 'Google Chrome')
        self.assertFalse(g.is_group_child)
        self.assertEqual(g.group_children, [a])
        self.assertEqual(g.get_child_by_type(AnnotationType.StrikeOut), a)


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
        p = MarkdownPrinter(print_filename=True, remove_hyphens=False)

        linecount = 0
        charcount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 5)
        self.assertGreater(charcount, 500)

    def test_flat_page_number_offset(self) -> None:
        p = MarkdownPrinter(page_number_offset=-1)

        page_numbers = []
        for line in p.print_file('dummyfile', self.doc):
            m = re.match(r'.+Page #([0-9])', line)
            if m:
                page_numbers.append(m[1])

        self.assertEqual(page_numbers, ['0', '0', '0', '1', '1', '1', '1', '3', '3', '3'])

    def test_print_author(self) -> None:
        annot = next(self.doc.iter_annots())
        annot.author = "Author"
        assert annot.pos is not None
        page = annot.pos.page.format_name().title()
        expected = "%s [Author]" % page

        labelled = MarkdownPrinter(print_author=True).print_file('dummyfile', self.doc)
        self.assertTrue(any(expected in line for line in labelled))

        unlabelled = MarkdownPrinter().print_file('dummyfile', self.doc)
        self.assertFalse(any("Author" in line for line in unlabelled))

    def test_grouped(self) -> None:
        p = GroupedMarkdownPrinter(wrap_column=80)

        linecount = 0
        charcount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 10)
        self.assertGreater(charcount, 900)

    def test_multicolorgrouping(self) -> None:
        p = GroupedMarkdownPrinter(group_by_color=True)

        linecount = 0
        charcount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')
            charcount += len(line)

        self.assertGreater(linecount, 10)
        self.assertGreater(charcount, 900)


class MarkdownCaretPrinterTest(unittest.TestCase):
    filename = 'pr119_caret.pdf'

    def setUp(self) -> None:
        path = pathlib.Path(__file__).parent / 'tests' / self.filename
        with path.open('rb') as f:
            self.doc = pdfannots.process_file(f)

    def test_no_crash(self) -> None:
        p = MarkdownPrinter()

        linecount = 0
        for line in p.print_file('dummyfile', self.doc):
            linecount += line.count('\n')

        self.assertGreater(linecount, 5)


class JsonPrinterTest(PrinterTestBase):
    def test_flat(self) -> None:
        p = JsonPrinter(remove_hyphens=False, output_codec='utf-8')

        j = json.loads(
            p.begin()
            + functools.reduce(operator.add, p.print_file('dummyfile', self.doc))
            + p.end())

        self.assertTrue(isinstance(j, list))
        self.assertEqual(len(j), 10)


if __name__ == "__main__":
    unittest.main()
