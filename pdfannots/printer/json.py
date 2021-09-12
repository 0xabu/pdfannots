import argparse
import json
import typing

from . import DictBasedPrinter
from ..types import Document


class JsonPrinter(DictBasedPrinter):
    def __init__(self, args: argparse.Namespace):
        super().__init__(args)
        self.remove_hyphens = args.remove_hyphens  # Whether to remove hyphens across a line break

        # Multiple input files in a single output require to have a filename
        self.printfilename = args.printfilename if (
            not (hasattr(args, "input") and len(args.input) > 1)) else True
        self.seen_first = False

    def begin(self) -> str:
        return '{\n' if self.printfilename else ''

    def end(self) -> str:
        return '\n}\n' if self.printfilename else '\n'

    def print_file(self, filename: str, document: Document) -> typing.Iterator[str]:
        # insert a , between successive files
        if self.seen_first:
            yield ',\n'
        else:
            self.seen_first = True

        annot_dicts = [self.annot_to_dict(document, a) for a in document.iter_annots()]

        if self.printfilename:
            yield '  "%s": ' % filename

        yield from json.JSONEncoder(indent=4).iterencode(annot_dicts)
