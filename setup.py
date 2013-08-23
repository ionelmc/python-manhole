# -*- encoding: utf8 -*-
from setuptools import setup, find_packages

import os

setup(
    name = "manhole",
    version = "0.5.2",
    url = 'https://github.com/ionelmc/python-manhole',
    download_url = '',
    license = 'BSD',
    description = "Inpection manhole for python applications. Connection is done via unix domain sockets.",
    long_description = open(os.path.join(os.path.dirname(__file__), 'README.rst')).read(),
    author = 'Ionel Cristian Mărieș',
    author_email = 'contact@ionelmc.ro',
    package_dir = {'':'src'},
    py_modules = ['manhole'],
    include_package_data = True,
    zip_safe = False,
    classifiers = [
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: Unix',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Software Development :: Debuggers',
        'Topic :: Utilities',
        'Topic :: System :: Monitoring',
        'Topic :: System :: Networking',
        'Programming Language :: Python :: 2.6',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],
    install_requires=[
    ]
)
