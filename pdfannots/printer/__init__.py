import abc
import typing as typ

from ..types import Document


class Printer(abc.ABC):
    """
    Base class for pretty-printers.
    """

    def begin(self) -> str:
        """Called once prior to print_file call. Returns initial output."""
        return ''

    @abc.abstractmethod
    def print_file(
        self,
        filename: str,
        document: Document
    ) -> typ.Iterator[str]:
        """
        Pretty-print a single document.

        Pretty-print the extracted annotations, yielding output (incrementally) as strings.
        Called multiple times, once per file.
        """

    def end(self) -> str:
        """Called once after the final print_file call. Returns any final additional output."""
        return ''
