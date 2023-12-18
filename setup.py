#!/usr/bin/env python
import re
from distutils.command.build import build
from itertools import chain
from os import fspath
from pathlib import Path

from setuptools import find_packages
from setuptools import setup
from setuptools.command.develop import develop
from setuptools.command.easy_install import easy_install
from setuptools.command.install_lib import install_lib

pth_file = Path(__file__).parent.joinpath('src', 'manhole.pth')


class BuildWithPTH(build):
    def run(self):
        super().run()
        self.copy_file(fspath(pth_file), fspath(Path(self.build_lib, pth_file.name)))


class EasyInstallWithPTH(easy_install):
    def run(self, *args, **kwargs):
        super().run(*args, **kwargs)
        self.copy_file(fspath(pth_file), str(Path(self.install_dir, pth_file.name)))


class InstallLibWithPTH(install_lib):
    def run(self):
        super().run()
        dest = str(Path(self.install_dir, pth_file.name))
        self.copy_file(fspath(pth_file), dest)
        self.outputs = [dest]

    def get_outputs(self):
        return chain(install_lib.get_outputs(self), self.outputs)


class DevelopWithPTH(develop):
    def run(self):
        super().run()
        self.copy_file(fspath(pth_file), str(Path(self.install_dir, pth_file.name)))


def read(*names, **kwargs):
    with Path(__file__).parent.joinpath(*names).open(encoding=kwargs.get('encoding', 'utf8')) as fh:
        return fh.read()


setup(
    name='manhole',
    version='1.8.0',
    license='BSD-2-Clause',
    description='Manhole is in-process service that will accept unix domain socket connections and present the'
    'stacktraces for all threads and an interactive prompt.',
    long_description='{}\n{}'.format(
        re.compile('^.. start-badges.*^.. end-badges', re.M | re.S).sub('', read('README.rst')),
        re.sub(':[a-z]+:`~?(.*?)`', r'``\1``', read('CHANGELOG.rst')),
    ),
    author='Ionel Cristian Mărieș',
    author_email='contact@ionelmc.ro',
    url='https://github.com/ionelmc/python-manhole',
    packages=find_packages('src'),
    package_dir={'': 'src'},
    py_modules=[path.stem for path in Path('src').glob('*.py')],
    include_package_data=True,
    zip_safe=False,
    classifiers=[
        # complete classifier list: http://pypi.python.org/pypi?%3Aaction=list_classifiers
        'Development Status :: 5 - Production/Stable',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: BSD License',
        'Operating System :: Unix',
        'Operating System :: POSIX',
        'Programming Language :: Python',
        'Topic :: Software Development :: Debuggers',
        'Topic :: Utilities',
        'Topic :: System :: Monitoring',
        'Topic :: System :: Networking',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3 :: Only',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
        # uncomment if you test on these interpreters:
        # "Programming Language :: Python :: Implementation :: IronPython",
        # "Programming Language :: Python :: Implementation :: Jython",
        # "Programming Language :: Python :: Implementation :: Stackless",
        'Topic :: Utilities',
    ],
    project_urls={
        'Documentation': 'https://python-manhole.readthedocs.io/',
        'Changelog': 'https://python-manhole.readthedocs.io/en/latest/changelog.html',
        'Issue Tracker': 'https://github.com/ionelmc/python-manhole/issues',
    },
    entry_points={
        'console_scripts': [
            'manhole-cli = manhole.cli:main',
        ]
    },
    keywords=['debugging', 'manhole', 'thread', 'socket', 'unix domain socket'],
    python_requires='>=3.8',
    install_requires=[
        # eg: "aspectlib==1.1.1", "six>=1.7",
    ],
    extras_require={
        # eg:
        #   "rst": ["docutils>=0.11"],
        #   ":python_version=="2.6"": ["argparse"],
    },
    cmdclass={
        'build': BuildWithPTH,
        'easy_install': EasyInstallWithPTH,
        'install_lib': InstallLibWithPTH,
        'develop': DevelopWithPTH,
    },
)
