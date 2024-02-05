import argparse
import logging
import sys
import typing as typ

from pdfminer.layout import LAParams

from . import __doc__, __version__, process_file
from .printer import Printer
from .printer.markdown import MarkdownPrinter, GroupedMarkdownPrinter
from .printer.json import JsonPrinter


MD_FORMAT_ARGS = frozenset([
    'condense',
    'group_highlights_by_color',
    'page_number_offset',
    'print_filename',
    'sections',
    'use_page_labels',
    'wrap_column',
])
"""Names of arguments passed to the markdown printer."""


def _float_or_disabled(x: str) -> typ.Optional[float]:
    if x.lower().strip() == "disabled":
        return None
    try:
        return float(x)
    except ValueError as ex:
        raise argparse.ArgumentTypeError("invalid float value: {}".format(x)) from ex


def parse_args() -> typ.Tuple[argparse.Namespace, LAParams]:
    p = argparse.ArgumentParser(prog='pdfannots', description=__doc__)

    p.add_argument('--version', action='version',
                   version='%(prog)s ' + __version__)

    p.add_argument("input", metavar="INFILE", type=argparse.FileType("rb"),
                   help="PDF files to process", nargs='+')

    g = p.add_argument_group('Basic options')
    g.add_argument("-p", "--progress", default=False, action="store_true",
                   help="Emit progress information to stderr.")
    g.add_argument("-o", metavar="OUTFILE", type=argparse.FileType("w", encoding="utf-8"),
                   dest="output", default=sys.stdout, help="Output file (default is stdout).")
    g.add_argument("-n", "--cols", default=None, type=int, metavar="COLS", dest="cols",
                   help="Assume a fixed top-to-bottom left-to-right page layout with this many "
                        "columns per page. If unset, PDFMiner's layout detection logic is used.")
    g.add_argument("--keep-hyphens", dest="remove_hyphens", default=True, action="store_false",
                   help="When capturing text across a line break, don't attempt to remove hyphens.")
    g.add_argument("-f", "--format", choices=["md", "json"], default="md",
                   help="Output format (default: markdown).")

    g = p.add_argument_group('Options controlling markdown output')
    mutex_group = g.add_mutually_exclusive_group()
    mutex_group.add_argument(
        "--no-group",
        dest="group",
        default=True, action="store_false",
        help="Emit annotations in order, don't group into sections."
    )
    mutex_group.add_argument(
        "--group-highlights-by-color",
        dest="group_highlights_by_color",
        default=False, action="store_true",
        help="Group highlights by color in grouped output."
    )

    g.add_argument("-s", "--sections", metavar="SEC", nargs="*",
                   choices=GroupedMarkdownPrinter.ALL_SECTIONS,
                   default=GroupedMarkdownPrinter.ALL_SECTIONS,
                   help=("sections to emit (default: %s)" %
                         ', '.join(GroupedMarkdownPrinter.ALL_SECTIONS)))
    g.add_argument("--no-condense", dest="condense", default=True, action="store_false",
                   help="Emit annotations as a blockquote regardless of length.")
    g.add_argument("--no-page-labels", dest="use_page_labels", default=True, action="store_false",
                   help="Ignore page labels if present, just print 1-based page numbers.")
    g.add_argument("--page-number-offset", dest="page_number_offset", default=0, type=int,
                   help="Increase or decrease page numbers with a fixed offset.")
    g.add_argument("--print-filename", dest="print_filename", default=False, action="store_true",
                   help="Print the name of each file with annotations.")
    g.add_argument("-w", "--wrap", dest="wrap_column", metavar="COLS", type=int,
                   help="Wrap text at this many output columns.")

    g = p.add_argument_group(
        "Advanced options affecting PDFMiner text layout analysis")
    laparams = LAParams()
    g.add_argument(
        "--line-overlap", metavar="REL_HEIGHT", type=float, default=laparams.line_overlap,
        help="If two characters have more overlap than this they are considered to be "
             "on the same line. The overlap is specified relative to the minimum height "
             "of both characters. Default: %s" % laparams.line_overlap)
    g.add_argument(
        "--char-margin", metavar="REL_WIDTH", type=float, default=laparams.char_margin,
        help="If two characters are closer together than this margin they "
             "are considered to be part of the same line. The margin is "
             "specified relative to the character width. Default: %s" % laparams.char_margin)
    g.add_argument(
        "--word-margin", metavar="REL_WIDTH", type=float, default=laparams.word_margin,
        help="If two characters on the same line are further apart than this "
             "margin then they are considered to be two separate words, and "
             "an intermediate space will be added for readability. The margin "
             "is specified relative to the character width. Default: %s" % laparams.word_margin)
    g.add_argument(
        "--line-margin", metavar="REL_HEIGHT", type=float, default=laparams.line_margin,
        help="If two lines are close together they are considered to "
             "be part of the same paragraph. The margin is specified "
             "relative to the height of a line. Default: %s" % laparams.line_margin)
    g.add_argument(
        "--boxes-flow", type=_float_or_disabled, default=laparams.boxes_flow,
        help="Specifies how much a horizontal and vertical position of a "
             "text matters when determining the order of lines. The value "
             "should be within the range of -1.0 (only horizontal position "
             "matters) to +1.0 (only vertical position matters). You can also "
             "pass 'disabled' to disable advanced layout analysis, and "
             "instead return text based on the position of the bottom left "
             "corner of the text box. Default: %s" % laparams.boxes_flow)

    # The next two booleans are described as if they default off, so let's ensure that.
    assert not laparams.detect_vertical
    assert not laparams.all_texts
    g.add_argument(
        "--detect-vertical", default=laparams.detect_vertical,
        action="store_const", const=(not laparams.detect_vertical),
        help="Consider vertical text during layout analysis.")
    g.add_argument(
        "--all-texts", default=laparams.all_texts,
        action="store_const", const=(not laparams.all_texts),
        help="Perform layout analysis on text in figures.")

    args = p.parse_args()

    # Propagate parsed layout parameters back to LAParams object
    for param in ("line_overlap", "char_margin", "word_margin", "line_margin",
                  "boxes_flow", "detect_vertical", "all_texts"):
        setattr(laparams, param, getattr(args, param))

    return args, laparams


def main() -> None:
    args, laparams = parse_args()
    logging.basicConfig(format='%(levelname)s: %(message)s',
                        level=logging.WARNING)

    # construct appropriate Printer
    printer: Printer
    if args.format == "md":
        mdargs = {k: getattr(args, k) for k in MD_FORMAT_ARGS}
        printer = (GroupedMarkdownPrinter if args.group else MarkdownPrinter)(**mdargs)
    elif args.format == "json":
        printer = JsonPrinter(
            remove_hyphens=args.remove_hyphens,
            output_codec=args.output.encoding)

    def write_if_nonempty(s: str) -> None:
        if s:
            args.output.write(s)

    write_if_nonempty(printer.begin())

    # iterate over files
    for file in args.input:
        doc = process_file(
            file,
            columns_per_page=args.cols,
            emit_progress_to=(sys.stderr if args.progress else None),
            laparams=laparams)
        for line in printer.print_file(file.name, doc):
            args.output.write(line)

    write_if_nonempty(printer.end())
