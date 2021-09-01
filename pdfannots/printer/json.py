import argparse
import json
import typing

from . import DictBasedPrinter
from ..types import Document


class JsonPrinter(DictBasedPrinter):
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

