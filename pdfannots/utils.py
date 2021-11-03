import datetime
import string
import typing

CHARACTER_SUBSTITUTIONS = {
    'ﬀ': 'ff',
    'ﬁ': 'fi',
    'ﬂ': 'fl',
    'ﬃ': 'ffi',
    'ﬄ': 'ffl',
    '‘': "'",
    '’': "'",
    '“': '"',
    '”': '"',
    '…': '...',
}


def cleanup_text(text: str) -> str:
    """
    Normalise line endings and replace common special characters with plain ASCII equivalents.
    """
    if '\r' in text:
        text = text.replace('\r\n', '\n').replace('\r', '\n')
    return ''.join([CHARACTER_SUBSTITUTIONS.get(c, c) for c in text])


def merge_lines(captured_text: str, remove_hyphens: bool = False, strip_space: bool = True) -> str:
    """
    Merge and cleanup lines in captured text, optionally removing hyphens.

    Any number of consecutive newlines is replaced by a single space, unless the
    prior line ends in a hyphen, in which case they are just removed entirely.
    This makes it easier for the renderer to "broadcast" newlines to active
    annotations regardless of box hits. (Detecting paragraph breaks is tricky,
    and left for future work!)
    """
    results = []

    lines = captured_text.splitlines()
    for i in range(len(lines)):
        thisline = lines[i]
        if thisline == '':
            continue

        nextline = lines[i + 1] if i + 1 < len(lines) else None

        if (len(thisline) >= 2
                and thisline[-1] == '-'       # Line ends in an apparent hyphen
                and thisline[-2].islower()):  # Prior character was a lowercase letter
            # We have a likely hyphen. Remove it if desired.
            if remove_hyphens:
                thisline = thisline[:-1]
        elif (not thisline[-1].isspace()
              and nextline is not None
              and (nextline == '' or not nextline[0].isspace())):
            # Insert space to replace the line break
            thisline += ' '

        results.append(cleanup_text(thisline))

    if results and strip_space:
        results[0] = results[0].lstrip()
        results[-1] = results[-1].rstrip()

    return ''.join(results)


def decode_datetime(dts: str) -> typing.Optional[datetime.datetime]:
    if dts.startswith('D:'):  # seems 'optional but recommended'
        dts = dts[2:]
    dts = dts.replace("'", '')
    zi = dts.find('Z')
    if zi != -1:  # sometimes it's Z/Z0000
        dts = dts[:zi] + '+0000'
    fmt = '%Y%m%d%H%M%S'
    # dates in PDFs are quite flaky and underspecified... so perhaps worth defensive code here
    for suf in ['%z', '']:  # sometimes timezone is missing
        try:
            return datetime.datetime.strptime(dts, fmt + suf)
        except ValueError:
            continue
    return None


ROMAN_ONES = ['i', 'x', 'c', 'm']
ROMAN_FIVES = ['v', 'l', 'd']


def format_roman(value: int) -> str:
    """Format a number as lowercase Roman numerals."""

    assert 0 < value < 4000
    result: typing.List[str] = []
    index = 0

    while value != 0:
        value, remainder = divmod(value, 10)
        if remainder == 9:
            result.insert(0, ROMAN_ONES[index])
            result.insert(1, ROMAN_ONES[index + 1])
        elif remainder == 4:
            result.insert(0, ROMAN_ONES[index])
            result.insert(1, ROMAN_FIVES[index])
        else:
            over_five = remainder >= 5
            if over_five:
                result.insert(0, ROMAN_FIVES[index])
                remainder -= 5
            result.insert(1 if over_five else 0, ROMAN_ONES[index] * remainder)
        index += 1

    return ''.join(result)


def format_alpha(value: int) -> str:
    """Format a number as lowercase letters a-z, aa-zz, etc."""

    assert value > 0
    result: typing.List[str] = []

    while value != 0:
        value, remainder = divmod(value - 1, len(string.ascii_lowercase))
        result.insert(0, string.ascii_lowercase[remainder])

    return ''.join(result)
