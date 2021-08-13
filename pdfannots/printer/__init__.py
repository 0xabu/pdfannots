import abc
import argparse
import typing

from ..types import Outline, Annotation


class Printer(abc.ABC):
    """
    Base class for pretty-printers.
    """
    output: typing.TextIO  # File handle for output

    def __init__(self, args: argparse.Namespace):
        """
        Perform initialisation and capture any relevant output options from the args object.
        """
        self.output = args.output

    @abc.abstractmethod
    def __call__(
        self,
        annots: typing.Sequence[Annotation],
        outlines: typing.Sequence[Outline]
    ) -> None:
        """
        Pretty-print the extracted annotations.
        """
        pass
