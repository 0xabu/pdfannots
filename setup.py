from setuptools import setup, find_packages  # type:ignore
import pathlib


def get_version_from_file(filename: pathlib.Path) -> str:
    with open(filename, 'r') as fh:
        for line in fh.readlines():
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]

    raise RuntimeError("Unable to find version string in %s" % filename)


def main() -> None:
    here = pathlib.Path(__file__).parent.resolve()
    setup(
        name='pdfannots',
        version=get_version_from_file(here / 'pdfannots' / '__init__.py'),
        description='Tool to extract and pretty-print PDF annotations for reviewing',
        long_description=(here / 'README.md').read_text(),
        long_description_content_type='text/markdown',
        url='https://github.com/0xabu/pdfannots',
        author='Andrew Baumann',
        author_email='pdfannots.pypi.org@ab.id.au',
        classifiers=[
            'Intended Audience :: Science/Research',
            'Topic :: Text Processing',
            'License :: OSI Approved :: MIT License',
            'Programming Language :: Python :: 3',
            'Programming Language :: Python :: 3.7',
            'Programming Language :: Python :: 3.8',
            'Programming Language :: Python :: 3.9',
            'Programming Language :: Python :: 3.10',
            'Programming Language :: Python :: 3.11',
        ],
        packages=find_packages(include=['pdfannots', 'pdfannots.*']),
        package_data={'pdfannots': ['py.typed']},
        entry_points={
            'console_scripts': [
                'pdfannots=pdfannots.cli:main',
            ],
        },
        python_requires='>=3.7',
        install_requires=['pdfminer.six >= 20220319'],
    )


if __name__ == '__main__':
    main()
