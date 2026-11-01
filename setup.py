import re
from pathlib import Path

from setuptools import setup

script = Path(__file__).with_name("corral").read_text()
setup(version=re.search(r'^VERSION = "(.+)"$', script, re.MULTILINE).group(1))
