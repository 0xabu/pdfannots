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
        result['created'] = annot.created.strftime('%Y-%m-%dT%H:%M:%S.%f')

    return result


class JsonPrinter(Printer):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)

    def __call__(
        self,
        filename: str,
        doc: Document
    ) -> typing.Iterator[str]:
        # TODO: produce valid JSON output for multiple input files
        yield from json.JSONEncoder(indent=2).iterencode(
            [annot_to_dict(doc, a) for a in doc.iter_annots()])
        yield '\n'
