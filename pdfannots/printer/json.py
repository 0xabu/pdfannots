import argparse
import json
import typing

from . import Printer
from ..types import Annotation, Document


def annot_to_dict(doc: Document, annot: Annotation) -> typing.Dict[str, typing.Any]:
    """Convert an annotation to a dictionary representation suitable for JSON encoding."""
    assert annot.pos

    result = {
        "type": annot.tagname,
        "page": annot.pos.page.pageno + 1,
        "start_xy": (annot.pos.x, annot.pos.y),
    }

    outline = doc.nearest_outline(annot.pos)
    if outline:
        result["prior_outline"] = outline.title

    if annot.text:
        result['text'] = annot.gettext()

    if annot.contents:
        result['contents'] = annot.contents

    if annot.author:
        result['author'] = annot.author

    if annot.created:
        result['created'] = annot.created.strftime('%Y-%m-%dT%H:%M:%S')

    return result


class JsonPrinter(Printer):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)

        # We overload the printfilename option to decide whether to emit a structured
        # JSON file with one entry per file, or just a flat array of annotations.
        self.printfilename = args.printfilename
        self.seen_first = False

    def begin(self) -> str:
        return '[\n' if self.printfilename else ''

    def end(self) -> str:
        return '\n]\n' if self.printfilename else '\n'

    def print_file(
        self,
        filename: str,
        doc: Document
    ) -> typing.Iterator[str]:

        # insert a , between successive files
        if self.seen_first:
            if self.printfilename:
                yield ',\n'
            else:
                # The flat array format is incompatible with multiple input files
                # TODO: Ideally we'd catch this at invocation time
                raise RuntimeError("When used with multiple input files, the "
                                   "JSON formatter requires --print-filename")
        else:
            self.seen_first = True

        annot_dicts = [annot_to_dict(doc, a) for a in doc.iter_annots()]

        if self.printfilename:
            dictobj = {
                "file": filename,
                "annotations": annot_dicts
            }

        yield from json.JSONEncoder(indent=2).iterencode(
            dictobj if self.printfilename else annot_dicts)
