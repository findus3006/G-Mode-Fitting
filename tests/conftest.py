import os
import sys
from pathlib import Path

import pytest

# Headless Qt for the GUI tests; the package is imported from the repository.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Real spectra are not in the repository (git-ignored); tests using them are
# skipped when the folder is missing.
DATA = ROOT / "tests" / "testdata"
needs_data = pytest.mark.skipif(not (DATA / "Probe1_633nm_G.txt").is_file(),
                                reason="real test spectra not in tests/testdata")
