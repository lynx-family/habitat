# coding: utf-8

import io
import os

from setuptools import find_packages, setup

NAME = 'habitat'
DESCRIPTION = 'A lightweight command line tool to manage source and binary dependencies.'
EMAIL = 'wangjianliang0@126.com'
AUTHOR = 'wangjianliang'

REQUIRES = [
    'coloredlogs>=15.0.0,<16.0.0',
    'asyncio-atexit==1.0.1',
    'httpx==0.27.0'
]

DEV_REQUIRES = [
    'flake8>=3.5.0,<4.0.0',
    'tox>=3.0.0,<4.0.0',
    'isort>=4.0.0,<5.0.0',
    'pytest>=4.0.0,<5.0.0',
    'pytest_httpserver==1.0.12',
    'pex'
] + REQUIRES

here = os.path.abspath(os.path.dirname(__file__))

try:
    with io.open(os.path.join(here, 'README.md'), encoding='utf-8') as f:
        long_description = '\n' + f.read()
except IOError:
    long_description = DESCRIPTION

about = {}
with io.open(os.path.join(here, 'core/__version__.py')) as f:
    exec(f.read(), about)

setup(
    name=NAME,
    version=about['__version__'],
    description=DESCRIPTION,
    long_description=long_description,
    long_description_content_type='text/markdown',
    author=AUTHOR,
    author_email=EMAIL,
    classifiers=[
        # Trove classifiers
        # Full list: https://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Intended Audience :: Developers',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.5',
    ],
    keywords='boilerplate',
    packages=find_packages(exclude=['docs', 'tests']),
    install_requires=REQUIRES,
    tests_require=[
        'pytest>=4.0.0,<5.0.0'
    ],
    python_requires='>=3.5',
    extras_require={
        'dev': DEV_REQUIRES,
    },
    entry_points={
        'console_scripts': [
            'hab=core.main:main',
        ]
    },
    package_data={
        # for PEP484 & PEP561
        NAME: ['py.typed', '*.pyi'],
    },
)
