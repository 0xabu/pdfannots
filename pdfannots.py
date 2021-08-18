#!/usr/bin/env python3

# This script, which is not part of the pdfannots package, allows pdfannots
# to by run directly from a source tree clone.

import sys
from pdfannots.cli import main

if __name__ == '__main__':
    sys.exit(main())
