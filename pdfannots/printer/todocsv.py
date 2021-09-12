from .csv import CsvPrinter

import typing
from ..types import Annotation, Document


class TodocsvPrinter(CsvPrinter):
    """
    Create a todo-list of all comments to keep track, which comments were addressed
    and add an option to extend and work with them within spreadsheets.
    """

    all_fieldnames = ["location", "context", "explanation"]

    def annot_to_dict(self, doc: Document, annot: Annotation) -> typing.Dict[str, typing.Any]:
        a = super().annot_to_dict(doc, annot)

        if annot.pos:
            o = doc.nearest_outline(annot.pos)

        return {
            'location': ("p%d" % a['page']) + (": " + o.title if o else ""),
            "context": a.get('text', '-'),
            "explanation": a.get('contents', '')
        }
