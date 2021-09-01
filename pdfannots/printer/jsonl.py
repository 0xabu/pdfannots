import argparse
import json
import typing

from . import DictBasedPrinter
from ..types import Document


class JsonlPrinter(DictBasedPrinter):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.remove_hyphens = args.remove_hyphens  # Whether to remove hyphens across a line break

        self.seen_first = False

    def end(self) -> str:
        return '\n'

    def print_file(self, filename: str, document: Document) -> typing.Iterator[str]:
        # insert a newline between successive files
        if self.seen_first:
            yield '\n'
        else:
            self.seen_first = True

        annot_dicts = [self.annot_to_dict(document, a) for a in document.iter_annots()]
        dictobj = {
            "file": filename,
            "annotations": annot_dicts
        }

        yield from json.JSONEncoder(indent=None).iterencode(dictobj)
