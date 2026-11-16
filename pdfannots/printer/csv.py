import csv
import io
import typing as typ

from . import Printer
from .json import annot_to_dict
from ..types import Document


CSV_FIELDS = [
    "filename",
    "name",
    "type",
    "page",
    "page_label",
    "start_x",
    "start_y",
    "prior_outline",
    "text",
    "contents",
    "author",
    "created",
    "color",
    "in_reply_to",
]
"""Column names of the CSV output, in order."""


class CsvPrinter(Printer):
    def __init__(
            self,
            *,
            remove_hyphens: bool
    ) -> None:
        self.remove_hyphens = remove_hyphens

    def _write_rows(self, rows: typ.Iterable[typ.Sequence[typ.Any]]) -> typ.Iterator[str]:
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator='\n')
        for row in rows:
            writer.writerow(row)
            yield buf.getvalue()
            buf.seek(0)
            buf.truncate()

    def begin(self) -> str:
        return ''.join(self._write_rows([CSV_FIELDS]))

    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typ.Iterator[str]:
        rows = []
        for annot in document.iter_annots(include_replies=True):
            d = annot_to_dict(document, annot, self.remove_hyphens)
            start_x, start_y = d.pop("start_xy")
            d.update(filename=filename, start_x=start_x, start_y=start_y)
            rows.append([d.get(field, '') for field in CSV_FIELDS])
        yield from self._write_rows(rows)
