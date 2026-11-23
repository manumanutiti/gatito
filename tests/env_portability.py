"""Separate test state: nothing from the real ~/gatito/state, ~/.claude or ~/.local/share.
Import it before any gatitod module (core creates folders when imported)."""
import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if 'GATITO_ROOT' not in os.environ:
    _t = Path(tempfile.mkdtemp(prefix='gatito-test-'))
    atexit.register(shutil.rmtree, _t, True)   # removed when the tests finish
    for f in ('config.json', 'actions.json'):
        shutil.copy(REPO / f, _t / f)
    (_t / 'projects.json').write_text('[]\n')
    os.environ.update(GATITO_ROOT=str(_t), GATITO_DATA=str(_t / 'data'),
                      GATITO_NOTEBOOKS=str(_t / 'notebooks'), CLAUDE_CONFIG_DIR=str(_t / 'claude'))
sys.path.insert(0, str(REPO / 'gatitod'))
