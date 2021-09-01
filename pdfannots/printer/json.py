import argparse
import json
import typing

from . import Printer
from ..types import Annotation, Document


class JsonPrinter(Printer):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.remove_hyphens = args.remove_hyphens  # Whether to remove hyphens across a line break

        # We overload the printfilename option to decide whether to emit a structured
        # JSON file with one entry per file, or just a flat array of annotations.
        self.printfilename = args.printfilename if len(args.input) < 2 else True
        self.seen_first = False

    def begin(self) -> str:
        return '[\n' if self.printfilename else ''

    def end(self) -> str:
        return '\n]\n' if self.printfilename else '\n'

    def print_file(self, filename: str, document: Document) -> typing.Iterator[str]:
        # insert a , between successive files
        if self.seen_first:
            yield ',\n'
        else:
            self.seen_first = True

        annot_dicts = [self.annot_to_dict(document, a) for a in document.iter_annots()]

        if self.printfilename:
            dictobj = {
                "file": filename,
                "annotations": annot_dicts
            }

        yield from json.JSONEncoder(indent=2).iterencode(
            dictobj if self.printfilename else annot_dicts)

    def annot_to_dict(self, doc: Document, annot: Annotation) -> typing.Dict[str, typing.Any]:
        """Convert an annotation to a dictionary representation suitable for JSON encoding."""
        assert annot.pos

        result = {
            "type": annot.subtype.name,
            "page": annot.pos.page.pageno + 1,
            "start_xy": (annot.pos.x, annot.pos.y),
        }

        outline = doc.nearest_outline(annot.pos)
        if outline:
            result["prior_outline"] = outline.title

        if annot.text:
            result['text'] = annot.gettext(self.remove_hyphens)

        if annot.contents:
            result['contents'] = annot.contents

        if annot.author:
            result['author'] = annot.author

        if annot.created:
            result['created'] = annot.created.strftime('%Y-%m-%dT%H:%M:%S')

        return result
