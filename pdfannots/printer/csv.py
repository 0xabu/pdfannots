import argparse
import io
import typing
import csv

from ..types import Document
from . import DictBasedPrinter


class CsvPrinter(DictBasedPrinter):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.remove_hyphens = args.remove_hyphens  # Whether to remove hyphens across a line break

        # Multiple input files in a single output require to have a filename
        self.printfilename = args.printfilename if (
            not (hasattr(args, "input") and len(args.input) > 1)) else True

        self.memcsvfile = io.StringIO()
        self.writer = csv.DictWriter(self.memcsvfile, fieldnames=(
            ['filename'] if self.printfilename else []) + self.all_fieldnames)

    def begin(self) -> str:
        self.writer.writeheader()
        return self.memcsvfile.getvalue()

    def print_file(self, filename: str, document: Document) -> typing.Iterator[str]:
        # Empty the file buffer
        self.memcsvfile.truncate(0)
        self.memcsvfile.seek(0)

        for a in document.iter_annots():
            ad = self.annot_to_dict(document, a)

            if self.printfilename:
                ad["filename"] = filename
            self.writer.writerow(ad)
        yield self.memcsvfile.getvalue()
