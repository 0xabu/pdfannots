from setuptools import setup


def main():
    name = 'pdfannots'
    setup(
        name=name,
        zip_safe=False,
        py_modules=[name],
        install_requires=open('requirements.txt').read().splitlines(),
    )


if __name__ == '__main__':
    main()
