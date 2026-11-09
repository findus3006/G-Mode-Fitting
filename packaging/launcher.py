"""Entry script for the PyInstaller build (``G-Mode-Fit.exe [spectrum.txt]``)."""

from gmode_fit.gui import main

if __name__ == "__main__":
    raise SystemExit(main())
