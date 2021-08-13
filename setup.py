from setuptools import setup, find_packages
import os.path
import pathlib

def get_version_from_file(filename):
    with open(filename, 'r') as fh:
        for line in fh.readlines():
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]

    raise RuntimeError("Unable to find version string in " + filename)

def main():
    here = pathlib.Path(__file__).parent.resolve()
    name = 'pdfannots'
    setup(
        name=name,
        version=get_version_from_file(here / name / '__init__.py'),
        description='Tool to extract PDF annotations as markdown for reviewing',
        long_description=(here/'README.md').read_text(),
        long_description_content_type='text/markdown',
        url='https://github.com/0xabu/pdfannots',
        classifiers=[
            'Intended Audience :: Science/Research',
            'Topic :: Text Processing',
            'License :: OSI Approved :: MIT License',
            'Programming Language :: Python :: 3',
            'Programming Language :: Python :: 3.6',
            'Programming Language :: Python :: 3.7',
            'Programming Language :: Python :: 3.8',
            'Programming Language :: Python :: 3.9',
        ],
        packages=find_packages(include=['pdfannots', 'pdfannots.*']),
        entry_points={
          'console_scripts': [
            'pdfannots=pdfannots.cli:main',
            ],
        },
        python_requires='>=3.6',
        install_requires=['pdfminer.six'],
    )


if __name__ == '__main__':
    main()
