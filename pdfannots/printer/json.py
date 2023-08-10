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
        "page_number": annot.pos.page.pageno + 1,
        "page_label": annot.pos.page.label,
        "start_xy": (annot.pos.x, annot.pos.y),
        "prior_outline": getattr(doc.nearest_outline(annot.pos), 'title', None),
        "text": annot.gettext(remove_hyphens),
        "contents": annot.contents,
        "author": annot.author,
        "created": annot.created.strftime('%Y-%m-%dT%H:%M:%S') if annot.created else None,
        "color": annot.color.ashex() if annot.color else None
    }

    # Remove keys with None values in nested dictionary and return
    return {k: v for k, v in result.items() if v is not None}


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
