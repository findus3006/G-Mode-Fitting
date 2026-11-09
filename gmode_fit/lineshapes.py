"""Line shapes for the G-mode fit, parameterised by their integrated area.

Every peak function takes ``(x, area, center, ...)``; for Gauss, Lorentz and
Voigt ``area`` is the exact integral over all x, so the fit returns the
integral and its uncertainty directly.

The Breit-Wigner-Fano (BWF) line of metallic tubes,

    I(ω) = I₀ · [1 + 2(ω−ω₀)/(qΓ)]² / [1 + (2(ω−ω₀)/Γ)²],

tends to I₀/q² far from the peak, so its integral is infinite. Its ``area`` is
the *Lorentzian-equivalent area* π·I₀·Γ/2 (the area of the same line with
1/q = 0), which does not depend on the selected range. The asymmetry is set
by ``inv_q`` = 1/q (negative for the usual low-frequency tail of metallic
tubes; 0 gives a Lorentzian).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import voigt_profile

__all__ = [
    "PeakKind",
    "PEAK_KINDS",
    "gauss",
    "lorentz",
    "voigt",
    "bwf",
    "voigt_fwhm",
    "bwf_i0",
    "bwf_maximum",
    "polynomial_baseline",
    "BASELINES",
]

_FWHM_TO_SIGMA = 1.0 / (2.0 * np.sqrt(2.0 * np.log(2.0)))


def gauss(x, area, center, fwhm):
    """Gaussian with integral ``area`` and full width at half maximum ``fwhm``."""
    sigma = fwhm * _FWHM_TO_SIGMA
    return area / (sigma * np.sqrt(2 * np.pi)) * np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentz(x, area, center, fwhm):
    """Lorentzian with integral ``area`` and full width at half maximum ``fwhm``."""
    hw = 0.5 * fwhm
    return area / np.pi * hw / ((x - center) ** 2 + hw ** 2)


def voigt(x, area, center, fwhm_g, fwhm_l):
    """Voigt profile: Gaussian (FWHM ``fwhm_g``) convolved with Lorentzian (FWHM ``fwhm_l``).

    ``fwhm_g`` is typically the instrument resolution and can be fixed when
    it is known; ``fwhm_l`` is the intrinsic (lifetime) width.
    """
    return area * voigt_profile(x - center, fwhm_g * _FWHM_TO_SIGMA, 0.5 * fwhm_l)


def bwf(x, area, center, fwhm, inv_q):
    """Breit-Wigner-Fano line with Lorentzian-equivalent area ``area`` (see module doc)."""
    i0 = bwf_i0(area, fwhm)
    s = 2.0 * (x - center) / fwhm
    return i0 * (1.0 + s * inv_q) ** 2 / (1.0 + s ** 2)


def bwf_i0(area, fwhm):
    """Peak intensity parameter I₀ of a BWF line with Lorentzian-equivalent ``area``."""
    return 2.0 * area / (np.pi * fwhm)


def bwf_maximum(center, fwhm, inv_q):
    """Position of the BWF maximum, ω₀ + Γ/(2q); differs from ω₀ when 1/q ≠ 0."""
    return center + 0.5 * fwhm * inv_q


def voigt_fwhm(fwhm_g, fwhm_l):
    """Total FWHM of a Voigt profile (Olivero & Longbothum, accuracy ~0.02 %)."""
    return 0.5346 * fwhm_l + np.sqrt(0.2166 * fwhm_l ** 2 + fwhm_g ** 2)


@dataclass(frozen=True)
class PeakKind:
    """A line shape: its function, parameter names and display labels."""

    name: str
    func: object
    params: tuple[str, ...]
    labels: tuple[str, ...]
    units: tuple[str, ...]


#: Available peak types, keyed by display name.
PEAK_KINDS: dict[str, PeakKind] = {
    "Voigt": PeakKind("Voigt", voigt, ("area", "center", "fwhm_g", "fwhm_l"),
                      ("Area", "Position ω₀", "FWHM Gauss", "FWHM Lorentz"),
                      ("cts·cm⁻¹", "cm⁻¹", "cm⁻¹", "cm⁻¹")),
    "Lorentz": PeakKind("Lorentz", lorentz, ("area", "center", "fwhm"),
                        ("Area", "Position ω₀", "FWHM"), ("cts·cm⁻¹", "cm⁻¹", "cm⁻¹")),
    "Gauss": PeakKind("Gauss", gauss, ("area", "center", "fwhm"),
                      ("Area", "Position ω₀", "FWHM"), ("cts·cm⁻¹", "cm⁻¹", "cm⁻¹")),
    "BWF": PeakKind("BWF", bwf, ("area", "center", "fwhm", "inv_q"),
                    ("Area (Lor.-equiv.)", "Position ω₀", "FWHM Γ", "1/q"),
                    ("cts·cm⁻¹", "cm⁻¹", "cm⁻¹", "")),
}

#: Baseline types and their polynomial degree (``None``: no baseline).
BASELINES: dict[str, int | None] = {"none": None, "constant": 0, "linear": 1, "quadratic": 2}


def polynomial_baseline(x, coeffs, x_ref):
    """``c0 + c1·(x−x_ref) + c2·(x−x_ref)² …``; centring keeps the fit well conditioned."""
    dx = np.asarray(x, dtype=float) - x_ref
    out = np.zeros_like(dx)
    for power, c in enumerate(coeffs):
        out = out + c * dx ** power
    return out
