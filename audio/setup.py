#!/usr/bin/python2.4
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab


import ez_setup
ez_setup.use_setuptools()

from glob import glob
from setuptools import setup

NAME = "pycopia-audio"
VERSION = "1.0"
REVISION="$Revision$"

DNAME = NAME.split("-", 1)[-1]
EGGNAME = "%s-%s.dev_r%s" % (NAME.replace("-", "_"), VERSION, REVISION[1:-1].split(":")[-1].strip())

setup (name=NAME, version=VERSION,
    namespace_packages = ["pycopia"],
    packages = ["pycopia", "pycopia.audio"],
    scripts =glob("bin/*"), 
    data_files=[('/etc/pycopia', glob("etc/*.py") + glob("etc/*.example"))],
    # Also requires the mgetty/vgetty software installed on your system.
    install_requires = ['pycopia-process>=1.0.dev-r138,==dev'],
    dependency_links = [
            "http://www.pycopia.net/download/"
                ],
    test_suite = "test.AudioTests",

    description = "Audio and telephony modules for Python.",
    long_description = """Audio and telephony modules for Python.
    Provides modules for controlling the alsaplayer program, and
    interfacing to mgetty/vgetty. Also includes a basic telephone answering
    machine, with email message delivery (you need a voice modem).
    NOTE: I can't test this code right now, and the alsaplayer interface
    is changing. But it all used to work...
    """,
    license = "LGPL",
    author = "Keith Dart",
    author_email = "keith@kdart.com",
    keywords = "pycopia audio framework",
    url = "http://www.pycopia.net/",
    download_url = "http://pycopia.googlecode.com/svn/trunk/%s#egg=%s" % (DNAME, EGGNAME),
    #download_url = "ftp://ftp.pycopia.net/pub/python/%s.%s.tar.gz" % (NAME, VERSION),
    classifiers = ["Operating System :: POSIX", 
                   "Topic :: Software Development :: Libraries :: Python Modules",
                   "Topic :: Multimedia :: Sound/Audio :: Capture/Recording",
                   "Topic :: Multimedia :: Sound/Audio :: Players",
                   "Topic :: Multimedia :: Sound/Audio :: Speech",
                   "Intended Audience :: Developers"],
)


