# G-mode fit

A small GUI for fitting the G band of (resonance) Raman spectra of carbon
nanotubes, one spectrum at a time. It fits Voigt, Lorentz, Gauss and
Breit-Wigner-Fano (BWF) lines plus a polynomial baseline. It reports the
integrated areas of G⁻ and G⁺ with 1σ errors and their ratio, which helps
tell metallic from semiconducting tubes.

## Start

```bash
python -m gmode_fit                 # or double-click G-Mode-Fit.bat
python -m gmode_fit spectrum.txt    # open a file right away
```

Requirements: Python ≥ 3.10, numpy, scipy, matplotlib, PySide6 and the
[`kpfm_pl`](../kpfm_pl) toolbox with its GUI extra (`pip install -e .[gui]` in
its folder). The plot panel, the wheel zoom / middle-drag pan and the CSV /
figure export come from `kpfm_pl`. `G-Mode-Fit.bat` also finds `kpfm_pl`
when it sits next to this folder and is not installed.

## Workflow

1. **Spectrum.** Open a file with *Open spectrum…* or Ctrl+O, or drop it onto the window.
   The file needs two numeric columns; header lines are skipped.
   - The first column can be the absolute wavelength in nm or the Raman shift in cm⁻¹.
     *auto-detect* tells them apart. The laser wavelength is read from the file name
     (`…_532nm_…`) and can be edited.
   - **Shift offset** corrects the calibration. It is added to the Raman shift and
     remembered per laser wavelength. Example: the 532 nm test files put G⁺
     at about 1607–1612 cm⁻¹, so an offset of about −17 cm⁻¹ brings it to about 1592.
2. **Fit range.** Left-drag on the plot, or type the limits. *Full range* drops the
   outermost 3 points, because the first point of these files is a spike.
3. **Model.**
   - *Semiconducting* = G⁻ Voigt + G⁺ Voigt.
   - *Metallic* = G⁻ BWF + G⁺ Voigt.
   - *+ Add peak* adds further lines.
   - Every parameter has a start value, optional min/max (empty = none) and **Fix**.
     Fix the Gaussian Voigt width when your instrument resolution is known; when free,
     it is strongly correlated with the Lorentzian width.
   - *Auto-guess* takes start values from the data: G⁺ on the highest maximum, G⁻ on
     the strongest signal below it, areas and baseline solved linearly.
   - Until you fit, the dashed curves show the start model.
4. **Fit** (Ctrl+F). The fitted values become the new start values, and *Revert*
   restores the previous ones. Parameters that end on a bound are reported, because
   their errors are then unreliable.
5. **Export.**
   - *Export results (CSV)* writes the peak table with values, errors and derived
     quantities. Every parameter, bound and setting goes in `#` header lines.
   - *Append to summary CSV* adds one row per file (G⁻, G⁺, ratio, R², χ²_red), so you
     can compare samples and lasers in one table.
   - *Save figure…* writes PNG/SVG/PDF, and *Export data (CSV)…* writes the curves.

Plot navigation: mouse wheel zooms (Shift: x only, Ctrl: y only), middle-drag
pans, Home resets the view.

## Line shapes and areas

| Type    | Parameters                         | Area |
|---------|------------------------------------|------|
| Gauss   | area, ω₀, FWHM                     | exact integral |
| Lorentz | area, ω₀, FWHM                     | exact integral |
| Voigt   | area, ω₀, FWHM Gauss, FWHM Lorentz | exact integral |
| BWF     | area, ω₀, Γ, 1/q                   | Lorentzian-equivalent area π·I₀·Γ/2 |

BWF: I(ω) = I₀·[1 + 2(ω−ω₀)/(qΓ)]² / [1 + (2(ω−ω₀)/Γ)²].
- Far from the peak the BWF tends to I₀/q², so its true integral is infinite.
  The area is therefore the area of the same line without the asymmetry, which does
  not depend on the fit range.
- 1/q < 0 gives the low-frequency tail of metallic tubes (typically −0.1 … −0.5),
  and 1/q = 0 is a Lorentzian.
- The BWF maximum lies at ω₀ + Γ/(2q). The results table lists it as *Maximum*,
  next to ω₀.

Every area is a fit parameter, so its error comes straight from the fit. Errors
are 1σ from the Jacobian, scaled by the reduced χ². Derived values (total Voigt
FWHM, BWF maximum, A(G⁻)/A(G⁺)) are propagated with the full covariance, so
correlated parameters are accounted for. Peaks with the same label are summed
for the ratio.

## Code

```
gmode_fit/io.py          loading, unit detection, nm → cm⁻¹
gmode_fit/lineshapes.py  line shapes (area-normalised), Voigt FWHM
gmode_fit/fitting.py     model, auto-guess, fit, errors, ratio, summary (no Qt)
gmode_fit/gui.py         PySide6 window
tests/                   pytest (synthetic spectra + real spectra in tests/testdata,
                         which is not in the repository; those tests are skipped without it)
```

Run the tests with `python -m pytest tests`.
