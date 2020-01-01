# -*- coding: utf-8 -*-
from setuptools import setup
from setuptools.command.install import install
import os


def create_shortcut():
    sh = os.path.join(os.path.expanduser('~'), '.shortcuts')
    if not os.path.exists(sh):
        os.mkdir(sh)
    with open(os.path.join(sh, 'Nauta-Proxy'), 'w') as fd:
        fd.write('''#!/usr/bin/bash
CMD="nauta-proxy"
SELF="bash $0 -r"
$CMD --stats | termux-notification -t "Nauta Proxy" -i nauta_proxy --ongoin --alert-once --action "$CMD --options; $SELF" --button2 "Options" --button2-action "$CMD --options" --button1 "Reload" --button1-action "$SELF"

if [ $# == 0 ]; then
    $CMD
fi
''')


class InstallCommand(install):
    def run(self):
        create_shortcut()
        install.run(self)


with open('README.rst') as fd:
    long_desc = fd.read()


setup(
    name='nauta_proxy',
    version='0.1.2',
    description='A simple Python proxy for Delta Chat and Nauta email server',
    long_description=long_desc,
    long_description_content_type='text/x-rst',
    author='Asiel Díaz Benítez',
    author_email='adbenitez@nauta.cu',
    url='https://github.com/adbenitez/nauta_proxy',
    packages=['nauta_proxy'],
    classifiers=['Development Status :: 3 - Alpha',
                 'License :: OSI Approved :: GNU General Public License v3 (GPLv3)',
                 'Topic :: Utilities',
                 'Programming Language :: Python :: 3'],
    entry_points='''
        [console_scripts]
        nauta-proxy=nauta_proxy:main
    ''',
    python_requires='>=3.5',
    # install_requires=[],
    include_package_data=True,
    zip_safe=False,
    cmdclass={
        'install': InstallCommand,
    },
)
