import argparse
import textwrap
import typing

from . import Printer
from ..types import Pos, Outline, Annotation

class MarkdownPrinter(Printer):
    BULLET_INDENT1 = " * "
    BULLET_INDENT2 = "   "
    QUOTE_INDENT = BULLET_INDENT2 + "> "

    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.wrapcol = args.wrap      # Specifies the column at which output is word-wrapped
        self.condense = args.condense # Permit use of the condensed format

        if self.wrapcol:
            # for bullets, we need two text wrappers: one for the leading bullet on the first paragraph, one without
            self.bullet_tw1 = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.BULLET_INDENT1,
                subsequent_indent=self.BULLET_INDENT2)

            self.bullet_tw2 = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.BULLET_INDENT2,
                subsequent_indent=self.BULLET_INDENT2)

            # for blockquotes, each line is prefixed with "> "
            self.quote_tw = textwrap.TextWrapper(
                width=self.wrapcol,
                initial_indent=self.QUOTE_INDENT,
                subsequent_indent=self.QUOTE_INDENT)

    def nearest_outline(self, outlines: typing.Sequence[Outline], pos: Pos) -> typing.Optional[Outline]:
        prev = None
        for o in outlines:
            if o.pos < pos:
                prev = o
            else:
                break
        return prev

    def format_pos(self, annot: Annotation, outlines: typing.Sequence[Outline]) -> str:
        apos = annot.getstartpos()
        o = self.nearest_outline(outlines, apos) if apos else None
        if o:
            return "Page %d (%s)" % (annot.page.pageno + 1, o.title)
        else:
            return "Page %d" % (annot.page.pageno + 1)

    # format a Markdown bullet, wrapped as desired
    def format_bullet(self, paras: typing.List[str], quotepos=None, quotelen=None) -> str:
        # quotepos/quotelen specify the first paragraph (if any) to be formatted
        # as a block-quote, and the length of the blockquote in paragraphs
        if quotepos:
            assert quotepos > 0
            assert quotelen > 0
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
            inquote = quotepos and npara >= quotepos and npara < quotepos + quotelen

            # emit a paragraph break
            # if we're going straight to a quote, we don't need an extra newline
            ret = ret + ('\n' if npara == quotepos else '\n\n')

            if self.wrapcol:
                tw = self.quote_tw if inquote else self.bullet_tw2
                ret = ret + tw.fill(para)
            else:
                indent = self.QUOTE_INDENT if inquote else self.BULLET_INDENT2
                ret = ret + indent + para

            npara += 1

        return ret

    def format_annot(self, annot: Annotation, outlines: typing.Sequence[Outline], extra=None) -> str:
        # capture item text and contents (i.e. the comment), and split each into paragraphs
        rawtext = annot.gettext()
        text = [l for l in rawtext.strip().splitlines() if l] if rawtext else []
        comment = [l for l in annot.contents.splitlines() if l] if annot.contents else []

        # we are either printing: item text and item contents, or one of the two
        # if we see an annotation with neither, something has gone wrong
        assert text or comment

        # compute the formatted position (and extra bit if needed) as a label
        label = self.format_pos(annot, outlines) + (" " + extra if extra else "") + ":"

        # If we have short (single-paragraph, few words) text with a short or no
        # comment, and the text contains no embedded full stops or quotes, then
        # we'll just put quotation marks around the text and merge the two into
        # a single paragraph.
        if (self.condense
            and len(text) == 1
            and len(text[0].split()) <= 10 # words
            and all([x not in text[0] for x in ['"', '. ']])
            and (not comment or len(comment) == 1)):
            msg = label + ' "' + text[0] + '"'
            if comment:
                msg = msg + ' -- ' + comment[0]
            return self.format_bullet([msg]) + "\n"

        # If there is no text and a single-paragraph comment, it also goes on
        # one line.
        elif comment and not text and len(comment) == 1:
            msg = label + " " + comment[0]
            return self.format_bullet([msg]) + "\n"

        # Otherwise, text (if any) turns into a blockquote, and the comment (if
        # any) into subsequent paragraphs.
        else:
            msgparas = [label] + text + comment
            quotepos = 1 if text else None
            quotelen = len(text) if text else None
            return self.format_bullet(msgparas, quotepos, quotelen) + "\n"

    def __call__(self, annots: typing.Sequence[Annotation], outlines: typing.Sequence[Outline]):
        for a in annots:
            print(self.format_annot(a, outlines, a.tagname), file=self.output)


class GroupedMarkdownPrinter(MarkdownPrinter):
    ANNOT_NITS = frozenset({'Squiggly', 'StrikeOut', 'Underline'})
    ALL_SECTIONS = ["highlights", "comments", "nits"]

    def __init__(self, args):
        super().__init__(args)
        self.sections = args.sections # controls the order of sections output

    def __call__(self, annots: typing.Sequence[Annotation], outlines: typing.Sequence[Outline]):
        self._printheader_called = False

        def printheader(name):
            # emit blank separator line if needed
            if self._printheader_called:
                print("", file=self.output)
            else:
                self._printheader_called = True
            print("## " + name + "\n", file=self.output)

        highlights = [a for a in annots if a.tagname == 'Highlight' and a.contents is None]
        comments = [a for a in annots if a.tagname not in self.ANNOT_NITS and a.contents]
        nits = [a for a in annots if a.tagname in self.ANNOT_NITS]

        for secname in self.sections:
            if highlights and secname == 'highlights':
                printheader("Highlights")
                for a in highlights:
                    print(self.format_annot(a, outlines), file=self.output)

            if comments and secname == 'comments':
                printheader("Detailed comments")
                for a in comments:
                    print(self.format_annot(a, outlines), file=self.output)

            if nits and secname == 'nits':
                printheader("Nits")
                for a in nits:
                    extra = "delete" if a.tagname == 'StrikeOut' else None
                    print(self.format_annot(a, outlines, extra), file=self.output)
