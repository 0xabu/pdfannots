"""Tests for CLI argument validation (pdfannots.cli.parse_args)."""

import pathlib
import sys
import unittest
from unittest import mock

from pdfannots.cli import parse_args

TEST_PDF = str(pathlib.Path(__file__).parent / 'hotos17.pdf')


def parse(argv):
    with mock.patch.object(sys, 'argv', argv):
        return parse_args()


class ColsValidationTests(unittest.TestCase):
    def test_cols_zero_is_rejected(self):
        # --cols 0 used to be accepted and then crash deep inside layout
        # code with a bare AssertionError; it must be a clean CLI error.
        with self.assertRaises(SystemExit) as ctx:
            parse(['pdfannots', '--cols', '0', TEST_PDF])
        self.assertEqual(ctx.exception.code, 2)

    def test_cols_negative_is_rejected(self):
        with self.assertRaises(SystemExit) as ctx:
            parse(['pdfannots', '--cols', '-3', TEST_PDF])
        self.assertEqual(ctx.exception.code, 2)

    def test_cols_positive_still_accepted(self):
        args, _laparams = parse(['pdfannots', '--cols', '2', TEST_PDF])
        self.assertEqual(args.cols, 2)

    def test_cols_unset_still_accepted(self):
        args, _laparams = parse(['pdfannots', TEST_PDF])
        self.assertIsNone(args.cols)


if __name__ == '__main__':
    unittest.main()
