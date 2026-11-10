# PyInstaller spec: one-file, windowed G-Mode-Fit.exe.
#
# Build from the repository folder:
#     python -m PyInstaller packaging/G-Mode-Fit.spec --distpath dist --workpath build
# The exe lands in dist/G-Mode-Fit.exe; build/ can be deleted afterwards.

from pathlib import Path

ROOT = Path(SPECPATH).parent
# kpfm_pl is found when installed; its source next to this repository is a fallback.
KPFM_SRC = ROOT.parent / "kpfm_pl" / "src"

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT), str(KPFM_SRC)],
    hiddenimports=["matplotlib.backends.backend_qtagg"],
    # The fitting guide shown by Help → Fitting guide.
    datas=[(str(ROOT / "gmode_fit" / "fitting_guide.md"), "gmode_fit")],
    # Not used by the program; keeps the exe smaller.
    excludes=["tkinter", "PyQt5", "PyQt6", "PySide2", "IPython", "jupyter", "notebook",
              "pandas", "pytest", "sphinx", "docutils"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="G-Mode-Fit",
    console=False,
    upx=False,
)
