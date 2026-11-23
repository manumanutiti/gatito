"""Test environment: state, notebooks and profiles in a temporary folder.

Import it before anything from gatitod: the paths are read when core is imported. That way
the tests never touch ~/gatito/state or the real notebooks.
"""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix='gatito-probes-'))
atexit.register(shutil.rmtree, TMP, True)

os.environ['GATITO_STATE'] = str(TMP / 'state')
os.environ['GATITO_NOTEBOOKS'] = str(TMP / 'notebooks')
os.environ['GATITO_PROFILES'] = str(TMP / 'profiles')
(TMP / 'notebooks').mkdir()
# a copy of the repo profiles: tests add and break their own without touching these
shutil.copytree(REPO / 'profiles', TMP / 'profiles')
sys.path.insert(0, str(REPO / 'gatitod'))


def profile(name: str, text: str) -> Path:
    """Writes a test profile and returns its path."""
    f = TMP / 'profiles' / f'{name}.md'
    f.write_text(text, encoding='utf-8')
    return f


class Process:
    """What subprocess.run would return, without launching anything."""
    def __init__(self, stdout='', returncode=0, stderr=''):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
