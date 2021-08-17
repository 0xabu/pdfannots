import argparse
import textwrap
import typing

from . import Printer
from ..types import Pos, Annotation, Document


class MarkdownPrinter(Printer):
    BULLET_INDENT1 = " * "
    BULLET_INDENT2 = "   "
    QUOTE_INDENT = BULLET_INDENT2 + "> "

    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.printfilename = args.printfilename  # Whether to print file names
        self.wrapcol = args.wrap       # Column at which output is word-wrapped
        self.condense = args.condense  # Permit use of the condensed format

        if self.wrapcol:
            # For bullets, we need two text wrappers: one for the leading
            # bullet on the first paragraph, one without.
            self.bullet_tw1 = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.BULLET_INDENT1,
                subsequent_indent=self.BULLET_INDENT2)

            self.bullet_tw2 = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.BULLET_INDENT2,
                subsequent_indent=self.BULLET_INDENT2)

            # For blockquotes, each line is prefixed with "> "
            self.quote_tw = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.QUOTE_INDENT,
                subsequent_indent=self.QUOTE_INDENT)

    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typing.Iterator[str]:
        iter = self.emit_body(document)

        if self.printfilename:
            # Print the file name, only if there is some output.
            try:
                first = next(iter)
            except StopIteration:
                pass
            else:
                yield "# File: '%s'\n\n" % filename
                yield first

        yield from iter

    def format_pos(
        self,
        pos: Pos,
        document: Document
    ) -> str:

        o = document.nearest_outline(pos)
        if o:
            return "Page %d (%s)" % (pos.page.pageno + 1, o.title)
        else:
            return "Page %d" % (pos.page.pageno + 1)

    def format_bullet(
        self,
        paras: typing.List[str],
        quote: typing.Optional[typing.Tuple[int, int]] = None
    ) -> str:
        """
        Format a Markdown bullet, wrapped as desired.
        """

        if quote is not None:
            (quotepos, quotelen) = quote
            assert quotepos > 0  # first paragraph to format as a block-quote
            assert quotelen > 0  # length of the blockquote in paragraphs
            assert quotepos + quotelen <= len(paras)

        # emit the first paragraph with the bullet
        if self.wrapcol:
            ret = self.bullet_tw1.fill(paras[0])
        else:
            ret = self.BULLET_INDENT1 + paras[0]

        # emit subsequent paragraphs
        npara = 1
        for para in paras[1:]:
            # are we in a blockquote?
            inquote = quote and npara >= quotepos and npara < quotepos + quotelen

            # emit a paragraph break
            # if we're going straight to a quote, we don't need an extra newline
            ret = ret + ('\n' if quote and npara == quotepos else '\n\n')

            if self.wrapcol:
                tw = self.quote_tw if inquote else self.bullet_tw2
                ret = ret + tw.fill(para)
            else:
                indent = self.QUOTE_INDENT if inquote else self.BULLET_INDENT2
                ret = ret + indent + para

            npara += 1

        return ret

    def format_annot(
        self,
        annot: Annotation,
        document: Document,
        extra: typing.Optional[str] = None
    ) -> str:

        # capture item text and contents (i.e. the comment), and split each into paragraphs
        rawtext = annot.gettext()
        text = ([l for l in rawtext.strip().splitlines() if l]
                if rawtext else [])
        comment = ([l for l in annot.contents.splitlines() if l]
                   if annot.contents else [])

        # we are either printing: item text and item contents, or one of the two
        # if we see an annotation with neither, something has gone wrong
        assert text or comment

        # compute the formatted position (and extra bit if needed) as a label
        assert annot.pos is not None
        label = self.format_pos(annot.pos, document) + \
            (" " + extra if extra else "") + ":"

        # If we have short (single-paragraph, few words) text with a short or no
        # comment, and the text contains no embedded full stops or quotes, then
        # we'll just put quotation marks around the text and merge the two into
        # a single paragraph.
        if (self.condense
            and len(text) == 1
            and len(text[0].split()) <= 10  # words
            and all([x not in text[0] for x in ['"', '. ']])
                and (not comment or len(comment) == 1)):
            msg = label + ' "' + text[0] + '"'
            if comment:
                msg = msg + ' -- ' + comment[0]
            return self.format_bullet([msg]) + "\n\n"

        # If there is no text and a single-paragraph comment, it also goes on
        # one line.
        elif comment and not text and len(comment) == 1:
            msg = label + " " + comment[0]
            return self.format_bullet([msg]) + "\n\n"

        # Otherwise, text (if any) turns into a blockquote, and the comment (if
        # any) into subsequent paragraphs.
        else:
            msgparas = [label] + text + comment
            quotepos = (1, len(text)) if text else None
            return self.format_bullet(msgparas, quotepos) + "\n\n"

    def emit_body(
        self,
        document: Document
    ) -> typing.Iterator[str]:
        for a in document.iter_annots():
            yield self.format_annot(a, document, a.tagname)


class GroupedMarkdownPrinter(MarkdownPrinter):
    ANNOT_NITS = frozenset({'Squiggly', 'StrikeOut', 'Underline'})
    ALL_SECTIONS = ["highlights", "comments", "nits"]

    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.sections = args.sections  # controls the order of sections output

    def emit_body(
        self,
        document: Document
    ) -> typing.Iterator[str]:

        self._fmt_header_called = False

        def fmt_header(name: str) -> str:
            # emit blank separator line if needed
            prefix = '\n' if self._fmt_header_called else ''
            self._fmt_header_called = True
            return prefix + "## " + name + "\n\n"

        # Partition annotations into nits, comments, and highlights.
        nits = []
        comments = []
        highlights = []
        for a in document.iter_annots():
            if a.tagname in self.ANNOT_NITS:
                nits.append(a)
            elif a.contents:
                comments.append(a)
            elif a.tagname == 'Highlight':
                highlights.append(a)

        for secname in self.sections:
            if highlights and secname == 'highlights':
                yield fmt_header("Highlights")
                for a in highlights:
                    yield self.format_annot(a, document)

            if comments and secname == 'comments':
                yield fmt_header("Detailed comments")
                for a in comments:
                    yield self.format_annot(a, document)

            if nits and secname == 'nits':
                yield fmt_header("Nits")
                for a in nits:
                    extra = "delete" if a.tagname == 'StrikeOut' else None
                    yield self.format_annot(a, document, extra)
