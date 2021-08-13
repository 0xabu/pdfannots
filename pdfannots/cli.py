import argparse
import sys

from . import __doc__, __version__, process_file
from .printer.markdown import MarkdownPrinter, GroupedMarkdownPrinter


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog='pdfannots', description=__doc__)

    p.add_argument('--version', action='version',
                   version='%(prog)s ' + __version__)

    p.add_argument("input", metavar="INFILE", type=argparse.FileType("rb"),
                   help="PDF files to process", nargs='+')

    g = p.add_argument_group('Basic options')
    g.add_argument("-p", "--progress", default=False, action="store_true",
                   help="emit progress information")
    g.add_argument("-o", metavar="OUTFILE", type=argparse.FileType("w"), dest="output",
                   default=sys.stdout, help="output file (default is stdout)")
    g.add_argument("-n", "--cols", default=2, type=int, metavar="COLS", dest="cols",
                   help="number of columns per page in the document (default: 2)")

    g = p.add_argument_group('Options controlling output format')
    g.add_argument("-s", "--sections", metavar="SEC", nargs="*",
                   choices=GroupedMarkdownPrinter.ALL_SECTIONS,
                   default=GroupedMarkdownPrinter.ALL_SECTIONS,
                   help=("sections to emit (default: %s)" % ', '.join(GroupedMarkdownPrinter.ALL_SECTIONS)))
    g.add_argument("--no-condense", dest="condense", default=True, action="store_false",
                   help="do not use condensed format, emit annotations as a blockquote regardless of length")
    g.add_argument("--no-group", dest="group", default=True, action="store_false",
                   help="emit annotations in order, don't group into sections")
    g.add_argument("--print-filename", dest="printfilename", default=False, action="store_true",
                   help="print the filename when it has annotations")
    g.add_argument("-w", "--wrap", metavar="COLS", type=int,
                   help="wrap text at this many output columns")

    return p.parse_args()


def main() -> None:
    args = parse_args()

    # construct Printer instance
    # TODO: replace with appropriate factory logic
    printer = (GroupedMarkdownPrinter if args.group else MarkdownPrinter)(args)

    for file in args.input:
        (annots, outlines) = process_file(file, args.cols, args.progress)

        if args.printfilename and annots:
            print("# File: '%s'\n" % file.name, file=args.output)

        printer(annots, outlines)
