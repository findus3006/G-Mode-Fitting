"""Loading of two-column Raman spectra and conversion to Raman shift.

Files are plain text with the spectral axis in the first and the intensity in
the second column (tab, space, comma or semicolon separated; header and
comment lines are skipped). The spectral axis may be the absolute wavelength
in nm or the Raman shift in cm⁻¹; :func:`detect_unit` tells them apart using
the laser wavelength, which :func:`laser_from_filename` reads from names such
as ``Probe1_532nm_G.txt``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

__all__ = [
    "Spectrum",
    "read_columns",
    "laser_from_filename",
    "detect_unit",
    "to_raman_shift",
    "load_spectrum",
]

#: Largest Raman shift (cm⁻¹) still accepted when guessing that x is in nm.
MAX_SHIFT = 4000.0

_LASER_RE = re.compile(r"(?<![\d.])(\d{3,4}(?:[.,]\d+)?)\s*nm", re.IGNORECASE)
_SPLIT_RE = re.compile(r"[\s;,]+")


@dataclass
class Spectrum:
    """A loaded spectrum on the Raman-shift axis.

    ``raw_x`` is the spectral axis as stored in the file, ``shift`` the Raman
    shift in cm⁻¹ *including* ``offset``. Both are sorted ascending in shift.
    """

    path: Path
    raw_x: np.ndarray
    y: np.ndarray
    shift: np.ndarray
    unit: str                      # unit of raw_x: "nm" or "cm-1"
    laser_nm: float | None
    offset: float = 0.0
    meta: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.path.name


def read_columns(path: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """Read the first two numeric columns of a text file.

    Lines that do not start with two numbers (headers, comments) are skipped.
    A decimal comma is accepted when the columns are tab or semicolon
    separated.
    """
    xs, ys = [], []
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line or line[0] in "#%;":
                continue
            if ("\t" in line or ";" in line) and "," in line and "." not in line:
                line = line.replace(",", ".")
            parts = [p for p in _SPLIT_RE.split(line) if p]
            if len(parts) < 2:
                continue
            try:
                x, y = float(parts[0]), float(parts[1])
            except ValueError:
                continue
            xs.append(x)
            ys.append(y)
    if len(xs) < 5:
        raise ValueError(f"{Path(path).name}: found fewer than 5 numeric data rows.")
    return np.asarray(xs), np.asarray(ys)


def laser_from_filename(name: str | Path) -> float | None:
    """Laser wavelength in nm from a file name such as ``Probe1_532nm_G.txt``."""
    match = _LASER_RE.search(Path(name).name)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    return value if 200 <= value <= 2000 else None


def detect_unit(x: np.ndarray, laser_nm: float | None) -> str:
    """Guess whether ``x`` is an absolute wavelength (``"nm"``) or a shift (``"cm-1"``).

    ``x`` counts as a wavelength when it lies on the Stokes side of the laser
    within :data:`MAX_SHIFT`. Without a laser wavelength, values below
    1100 are taken as nm (a G-mode window in cm⁻¹ lies around 1500–1700).
    """
    lo, hi = float(np.min(x)), float(np.max(x))
    if laser_nm is None:
        return "nm" if hi < 1100 else "cm-1"
    if lo > laser_nm:
        shift_hi = 1e7 / laser_nm - 1e7 / hi
        if shift_hi <= MAX_SHIFT:
            return "nm"
    return "cm-1"


def to_raman_shift(wavelength_nm: np.ndarray, laser_nm: float) -> np.ndarray:
    """Stokes Raman shift (cm⁻¹) of an absolute wavelength (nm)."""
    return 1e7 / laser_nm - 1e7 / np.asarray(wavelength_nm, dtype=float)


def load_spectrum(path: str | Path, *, laser_nm: float | None = None, unit: str = "auto",
                  offset: float = 0.0) -> Spectrum:
    """Load ``path`` and return it on the Raman-shift axis.

    Parameters
    ----------
    laser_nm :
        Excitation wavelength. ``None`` reads it from the file name.
    unit :
        ``"auto"``, ``"nm"`` or ``"cm-1"`` – unit of the file's first column.
    offset :
        Added to the Raman shift (calibration correction, cm⁻¹).
    """
    path = Path(path)
    raw_x, y = read_columns(path)
    if laser_nm is None:
        laser_nm = laser_from_filename(path)
    if unit == "auto":
        unit = detect_unit(raw_x, laser_nm)
    if unit == "nm":
        if laser_nm is None:
            raise ValueError("The x axis is a wavelength in nm; enter the laser wavelength "
                             "to convert it to Raman shift.")
        shift = to_raman_shift(raw_x, laser_nm)
    elif unit == "cm-1":
        shift = raw_x.astype(float)
    else:
        raise ValueError(f"Unknown unit {unit!r}; use 'auto', 'nm' or 'cm-1'.")
    shift = shift + offset
    order = np.argsort(shift, kind="stable")
    return Spectrum(path=path, raw_x=raw_x[order], y=y[order].astype(float),
                    shift=shift[order], unit=unit, laser_nm=laser_nm, offset=offset)
