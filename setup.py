from setuptools import setup
import os.path
import pathlib

here = pathlib.Path(__file__).parent.resolve()

def get_version_from_file(filename):
    with open(here / filename, 'r') as fh:
        for line in fh.readlines():
            if line.startswith('__version__'):
                delim = '"' if '"' in line else "'"
                return line.split(delim)[1]

    raise RuntimeError("Unable to find version string in " + filename)

def main():
    name = 'pdfannots'
    setup(
        name=name,
        version=get_version_from_file(name + '.py'),
        description='Tool to extract PDF annotations as markdown for reviewing',
        long_description=(here/'README.md').read_text(),
        long_description_content_type='text/markdown',
        url='https://github.com/0xabu/pdfannots',
        classifiers=[
            'Intended Audience :: Science/Research',
            'Topic :: Text Processing',
            'License :: OSI Approved :: MIT License',
            'Programming Language :: Python :: 3',
        ],
        zip_safe=False,
        py_modules=[name],
        entry_points={
          'console_scripts': [
            'pdfannots=pdfannots:main',
            ],
        },
        python_requires='>=3',
        install_requires=['pdfminer.six'],
    )


if __name__ == '__main__':
    main()
