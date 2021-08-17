import abc
import argparse
import typing

from ..types import Document


class Printer(abc.ABC):
    """
    Base class for pretty-printers.
    """

    def __init__(self, args: argparse.Namespace):
        """
        Perform initialisation and capture any relevant output options from the args object.
        """
        pass

    @abc.abstractmethod
    def __call__(
        self,
        filename: str,
        document: Document
    ) -> typing.Iterator[str]:
        """
        Pretty-print the extracted annotations, yielding output (incrementally) as strings.
        """
        pass
