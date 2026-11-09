"""G-mode fitting of (resonance) Raman spectra of carbon nanotubes.

The package is split into a Qt-free core and an optional GUI:

* :mod:`gmode_fit.io` – load two-column spectra, convert wavelength to Raman shift
* :mod:`gmode_fit.lineshapes` – Voigt, Lorentz, Gauss and BWF (Fano) line shapes
* :mod:`gmode_fit.fitting` – composite model with bounds/fixed parameters, fit,
  uncertainties, G⁻/G⁺ area ratio
* :mod:`gmode_fit.gui` – PySide6 window (``python -m gmode_fit``); uses the
  plot panel and wheel zoom / middle-drag pan of ``kpfm_pl``
"""

__version__ = "0.1.0"
