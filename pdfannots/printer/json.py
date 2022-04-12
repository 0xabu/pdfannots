import json
import typing as typ

from . import Printer
from ..types import Annotation, Document


def annot_to_dict(
    doc: Document,
    annot: Annotation,
    remove_hyphens: bool
) -> typ.Dict[str, typ.Any]:
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
        result['text'] = annot.gettext(remove_hyphens)

    if annot.contents:
        result['contents'] = annot.contents

    if annot.author:
        result['author'] = annot.author

    if annot.created:
        result['created'] = annot.created.strftime('%Y-%m-%dT%H:%M:%S')

    return result


class JsonPrinter(Printer):
    def __init__(self, *, remove_hyphens: bool) -> None:
        self.remove_hyphens = remove_hyphens  # Whether to remove hyphens across a line break
        self.seen_first = False

    def end(self) -> str:
        return '\n'

    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typ.Iterator[str]:
        if self.seen_first:
            # The flat array format is incompatible with multiple input files
            # TODO: Ideally we'd catch this at invocation time
            raise RuntimeError("The JSON output format does not support multiple files.")
        else:
            self.seen_first = True

        annots = [annot_to_dict(document, a, self.remove_hyphens) for a in document.iter_annots()]
        yield from json.JSONEncoder(indent=2).iterencode(annots)
