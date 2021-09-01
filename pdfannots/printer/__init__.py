import abc
import argparse
import typing

from ..types import Annotation, Document


class Printer(abc.ABC):
    """
    Base class for pretty-printers.
    """

    def __init__(self, args: argparse.Namespace):
        """
        Perform initialisation and capture any relevant output options from the args object.
        """

    def begin(self) -> str:
        """Called once prior to print_file call. Returns initial output."""
        return ''

    @abc.abstractmethod
    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typing.Iterator[str]:
        """
        Pretty-print a single document.

        Pretty-print the extracted annotations, yielding output (incrementally) as strings.
        Called multiple times, once per file.
        """

    def end(self) -> str:
        """Called once after the final print_file call. Returns any final additional output."""
        return ''


class DictBasedPrinter(Printer):
    """
    Base class for printers formatting a dictionary like data-structure
    """

    def annot_to_dict(self, doc: Document, annot: Annotation) -> typing.Dict[str, typing.Any]:
        """Convert an annotation to a dictionary representation enabling further encoding."""
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
            result['text'] = annot.gettext(self.remove_hyphens)

        if annot.contents:
            result['contents'] = annot.contents

        if annot.author:
            result['author'] = annot.author

        if annot.created:
            result['created'] = annot.created.strftime('%Y-%m-%dT%H:%M:%S')

        return result
