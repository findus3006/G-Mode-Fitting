# Fitting guide for the G band of carbon nanotubes

The aim is to get the positions, widths and areas of the G⁻ and G⁺ lines, and
the area ratio **A(G⁻)/A(G⁺)** with an honest uncertainty.

You can open this guide in the program with **Help → Fitting guide** (F1).

---

## 1  What you are fitting

The **G band** of single-walled carbon nanotubes lies between about 1500 and
1650 cm⁻¹. It comes from C–C stretching vibrations of the graphene lattice. In
a nanotube it splits into two main lines [2]:

- **G⁺** at about 1590 cm⁻¹. Its position hardly depends on the tube diameter [1].
- **G⁻** at a lower wavenumber, typically 1540–1580 cm⁻¹. It moves further down
  for thinner tubes. A rough guide is ω(G⁻) ≈ ω(G⁺) − C/d², with the diameter
  d in nm, C ≈ 48 cm⁻¹·nm² for semiconducting tubes and C ≈ 80 cm⁻¹·nm² for
  metallic tubes [1].

The **shape** of G⁻ tells you about the electronic type of the tubes [1, 3]:

| Tubes in resonance | G⁻ line | Model to use |
|---|---|---|
| Semiconducting | narrow, symmetric | Voigt (or Lorentz) |
| Metallic | broad, asymmetric, tail towards **low** wavenumbers | Breit-Wigner-Fano (BWF) |

In metallic tubes the vibration couples to the free electrons. This broadens
the line, shifts it down and makes it asymmetric (a *Fano* line shape) [3, 4].
The asymmetry parameter **1/q** is negative for this low-wavenumber tail [3].
With 1/q = 0 the BWF becomes an ordinary Lorentzian.

**Resonance matters.** Only tubes whose electronic transitions match the laser
energy give a strong signal [2]. A spectrum taken with another laser shows a
different set of tubes. **Only compare samples measured with the same laser.**

---

## 2  Before you fit: check the data

1. **Spikes.** Cosmic rays produce single, very narrow spikes that are often
   only one data point wide. The program does not remove them. Remove them with 
   another tool or ask whether the measurement can be repeated.
   The first and last points of many files are spikes. *Full range* therefore
   leaves out the outer 3 points.
2. **Saturation.** A flat-topped peak means the detector was saturated. Such
   areas are wrong, so measure again with a shorter exposure or less laser power.
3. **Calibration.** G⁺ of nanotubes should lie near 1590–1593 cm⁻¹ [1, 2]. If it is
   more than a few cm⁻¹ off, the spectrometer calibration is probably shifted.
   Check it with a reference, for example the silicon line at 520.7 cm⁻¹. Enter
   the correction as the **Shift offset**. The program remembers it for each
   laser wavelength. For the A(G⁻)/A(G⁺) term this is not required, so you
   dont need to calibrate
4. **Signal-to-noise.** A noisy spectrum cannot support a model with many free
   parameters. Keep the model simple, or measure longer.

---

## 3  The recipe, step by step

1. **Open the spectrum** with Ctrl+O or by dropping the file onto the window.
   Check that the laser wavelength and the x-axis unit were recognised correctly.
2. **Select the fit range** by left-dragging on the plot.
   - A typical range is about 1450–1700 cm⁻¹.
   - Include some flat background on **both** sides of the band (30–50 cm⁻¹ or
     more), so that the baseline is defined.
   - A metallic BWF line has a long tail to low wavenumbers. Do not cut it off
     too close to the peak.
   - Use the **same range** for all spectra that you want to compare.
3. **Choose the baseline.** Start with **linear**. Use **quadratic** only when
   the residual clearly curves over the whole range and ΔBIC confirms it
   (see section 6).
4. **Choose the model.**
   - Use the *Semiconducting* preset when G⁻ is narrow and symmetric.
   - Use the *Metallic* preset when G⁻ is broad with a tail to the left.
   - If you are not sure, fit both and compare them with ΔBIC (section 6).
5. **Fix the Gaussian width** of the Voigt lines (FWHM Gauss) if the instrument
   resolution is known. Ask your supervisor, or measure the width of a narrow
   lamp emission line. Use the same value for all peaks and all spectra taken
   with this setup. If you leave it free, it trades off against the Lorentzian
   width, and both become uncertain. For now, you can leave it free.
6. **Auto-guess** the start values. Then look at the **dashed start model**: it
   should roughly follow the data. If it does not, type better start values
   (read the positions off the plot) and check again.
7. **Fit** (Ctrl+F).
8. **Check the fit** with the checklist in section 5. Press **Fit** a second
   time: the result should hardly change. If it does, the fit had not reached
   its minimum.
9. **Export** the results (CSV), and use *Append to summary CSV* to collect
   one row per spectrum.

**The results table stays until the next fit.** If you change the model, the
range, the baseline or the axis afterwards, a yellow note appears. It says that
the table no longer matches the settings and lists what changed. The plot then
shows the new start model as dashed lines. Press **Fit** to get matching
results. If you export while the note is shown, the program asks first. It
then saves the last fit together with the settings that were used for it.

---

## 4  Start values, bounds and fixed parameters

**Why start values matter.** A least-squares fit starts from your values and
moves downhill to the *nearest* minimum. Poor start values can lead to a wrong
minimum, for example two peaks on top of each other, or to no convergence at
all. After each fit the fitted values become the new start values. **Revert**
brings back the previous start values.

**Bounds (Min/Max).** Use bounds to keep parameters physically sensible:

| Parameter | Sensible bounds (rough guide) |
|---|---|
| Position ω₀ | within the fit range, G⁻ below G⁺ |
| FWHM | about 2–100 cm⁻¹ |
| 1/q (BWF) | −1 to 0 for metallic tubes |
| Area | ≥ 0 (this is the default) |

**"At bound" warning.** When a parameter ends exactly on a bound, the fit
wanted to go further. Its error is then meaningless. Either the bound is too
tight, so widen it, or the model does not fit the data, so rethink the model.
Do not report such a fit without saying so. Sometimes hitting a bound is unavoidable.

**Fixing a parameter** (the **Fix** box) keeps it at its value. Only fix a
parameter for a good reason, such as a known instrument width or a position
taken from a better measurement. A fixed parameter has no error, and the errors
of the other parameters then come out smaller. This would be required when the 
instrument width was known.

---

## 5  Is the fit good? A checklist

Work through this list for every fit.

- **Residuals (lower panel).** They should scatter randomly around zero and be
  about the same size everywhere. This is the most important check.
  - A wiggle at one peak position means the line shape is wrong or a peak is
    missing. Try BWF instead of Voigt for G⁻.
  - A slope or a smooth curve over the whole range points to the baseline.
    Try a quadratic baseline or a narrower range.
- **Converged.** A red "not converged" message means the result is not
  reliable.
- **No parameter at a bound** (orange note). Sometimes unavoidable.
- **Errors are reasonable.** An error as large as the value itself, such as
  area = 500 ± 600, means the data do not determine that parameter. Remove the
  peak, or fix one of the correlated parameters.
- **The values make physical sense.** G⁺ should be near 1590 cm⁻¹ and G⁻ below
  it [1]. A metallic BWF G⁻ is clearly broader than G⁺, with 1/q < 0 [3].
  If 1/q comes out positive, the BWF model is probably not appropriate.
- **The fit is stable.** A second **Fit**, or a fit from slightly different
  start values, should give the same result within the errors.

**About the numbers above the table:**

- **R²** is almost always above 0.99 for Raman spectra, even for a poor model.
  It barely tells models apart, so **do not choose a model by R²**.
- **χ²_red** here is the mean squared residual in counts². Its square root,
  √χ²_red, is the typical size of the residual in counts. Only compare χ²_red
  between fits of the same spectrum.
- **BIC** is used to compare models, see the next section.

---

## 6  Choosing between models: ΔBIC

A model with more peaks *always* fits a little better, even if the extra peak
is not real. The **Bayesian information criterion** [5]

  BIC = n · ln(χ²/n) + k · ln(n)    (n data points, k free parameters)

adds a penalty for every free parameter. A lower BIC is better.

After a second fit of the **same data** (same file, offset and range), the
program shows **ΔBIC = BIC(new) − BIC(previous)**:

| ΔBIC | Meaning |
|---|---|
| below −10 | the new model is clearly better |
| −10 … +10 | the data cannot tell the models apart: keep the simpler or the physically better motivated one |
| above +10 | the new model is clearly worse |

The limit of 10 is the level that Kass and Raftery call "very strong" evidence
[6]. They already call differences of 6–10 "strong", so the table above is on
the cautious side.

**Add a peak only if all three of these are true:**

1. the residual shows structure where the peak would sit,
2. ΔBIC < −10, and
3. there is a physical reason for the peak (for example several CNTs could be resonant at this wavelength).

*Example:* Fit the semiconducting preset, then the metallic preset on the same
range. If ΔBIC is −40, the BWF describes the G⁻ line clearly better, and you
have evidence for metallic tubes in resonance.

---

## 7  The area ratio A(G⁻)/A(G⁺)

- The ratio uses the **integrated areas**, not the peak heights.
- For a BWF line the true integral is infinite, because the tail never reaches
  zero. The program therefore uses the *Lorentzian-equivalent area* π·I₀·Γ/2,
  which does not depend on the fit range.
- The error of the ratio includes the correlation between the two areas.

**More than two peaks.** The labels decide what enters the ratio:

- all peaks labelled **G-** are summed in the numerator,
- all peaks labelled **G+** are summed in the denominator,
- peaks with other labels (**D'**, **other**) are **not** included.

Use several peaks with the same label only when the spectrum clearly needs it.
An example is a mixed sample with a narrow semiconducting G⁻ (Voigt) and a broad
metallic G⁻ (BWF), both labelled G-. Keep in mind:

- *Auto-guess* puts all G- peaks on the same position, and all G+ peaks on the
  same position. **Set their positions by hand before you fit**, for example a
  few cm⁻¹ apart, and use bounds to keep them in order.
- With two peaks under one label, the summary CSV gives only their summed area
  for that label. Positions and widths are left empty there and are found in
  the results export.

**Interpretation.** A larger ratio, together with a BWF-shaped G⁻, means more
metallic tubes **in resonance with this laser** [2]. The ratio is not the fraction
of metallic tubes in the sample. It depends on the laser, and also on the
model, range and baseline you chose. Keep all of these the same when you
compare samples.

---

## 8  What the ± means, and what it does not

The errors in the table are **1σ statistical uncertainties** from the fit. They
include the correlations between parameters. Roughly, the true value lies
within ±1σ in about two out of three cases, *if the model is right*.

They do **not** include **systematic** uncertainties, which are often larger:

- the choice of fit range,
- the choice of baseline,
- the choice of line shapes and number of peaks,
- the calibration.

**Rounding.** Give the error with 1–2 significant figures and round the value
to the same decimal place. The program already does this, so write
1591.3 ± 0.4, not 1591.2847 ± 0.4312.

---

## 9  Comparing samples

For a fair comparison, fit all spectra with:

- the same laser,
- the same fit range,
- the same baseline,
- the same model (line shapes and labels),
- the same fixed values, such as the Gaussian width.

*Append to summary CSV* writes one row per spectrum. The *model*, *baseline*
and range columns let you check afterwards that all rows were fitted the same
way.

---

## 10  What to put in your report

- Laser wavelength
- Fit range and baseline type
- The model: line shape and label of every peak
- A(G⁻)/A(G⁺) with its statistical and systematic uncertainty
- A figure with the data, the fit, the components and the residual
  (use *Save figure…* above the plot)

---

## 11  Troubleshooting

| Problem | Likely cause | What to do |
|---|---|---|
| Fit does not converge | poor start values, too many free parameters | Auto-guess, check the dashed model, fix the Gaussian width, use fewer peaks |
| Parameter "at bound" | bound too tight, or wrong model | Widen the bound, or change the model |
| Huge errors | parameters not determined by the data, or strongly correlated | Remove the peak, or fix one parameter |
| Two peaks end on the same position | start values too close | Separate the start positions, set bounds on the positions |
| Residual curves over the whole range | baseline | Quadratic baseline, or a narrower range |
| Residual has a wave at G⁻ | wrong line shape | Try BWF for G⁻ (metallic preset) |
| BWF gives 1/q > 0 | G⁻ is not metallic-like | Use the semiconducting model |
| G⁺ far from 1590 cm⁻¹ | calibration | Set the shift offset (section 2) |
| Result changes each time you press Fit | fit had not reached its minimum | Fit again until stable, then check the model |
| Yellow note above the table | settings changed after the fit | Press Fit to update the results |

---

## Glossary

- **Raman shift** (cm⁻¹): energy difference between the laser and the scattered
  light, in wavenumbers.
- **FWHM**: full width at half maximum of a line.
- **Lorentzian**: the line shape of a vibration with a finite lifetime.
- **Gaussian**: the line shape of the instrument resolution, or of a broad
  distribution of positions.
- **Voigt**: a Lorentzian convolved with a Gaussian, used for a real line
  measured with a real spectrometer.
- **BWF (Breit-Wigner-Fano)**: an asymmetric line from a vibration coupled to a
  continuum of electronic states. 1/q sets the asymmetry [3].
- **Baseline**: the smooth background under the peaks, for example from
  fluorescence. It is fitted together with the peaks.
- **Residual**: data minus fit.
- **χ²_red**: sum of the squared residuals divided by (points − free parameters).
- **BIC**: Bayesian information criterion, a goodness of fit with a penalty
  for each free parameter.
- **1σ error**: the standard uncertainty from the fit.

---

## References

1. A. Jorio, A. G. Souza Filho, G. Dresselhaus, M. S. Dresselhaus et al.,
   "G-band resonant Raman study of 62 isolated single-wall carbon nanotubes",
   *Phys. Rev. B* **65**, 155412 (2002).
   [doi:10.1103/PhysRevB.65.155412](https://doi.org/10.1103/PhysRevB.65.155412)
2. M. S. Dresselhaus, G. Dresselhaus, R. Saito, A. Jorio, "Raman spectroscopy
   of carbon nanotubes", *Phys. Rep.* **409**, 47–99 (2005). A good overview
   to start with.
   [doi:10.1016/j.physrep.2004.10.006](https://doi.org/10.1016/j.physrep.2004.10.006)
3. S. D. M. Brown, A. Jorio, P. Corio, M. S. Dresselhaus, G. Dresselhaus,
   R. Saito, K. Kneipp, "Origin of the Breit-Wigner-Fano lineshape of the
   tangential G-band feature of metallic carbon nanotubes", *Phys. Rev. B*
   **63**, 155414 (2001).
   [doi:10.1103/PhysRevB.63.155414](https://doi.org/10.1103/PhysRevB.63.155414)
4. S. Piscanec, M. Lazzeri, J. Robertson, A. C. Ferrari, F. Mauri, "Optical
   phonons in carbon nanotubes: Kohn anomalies, Peierls distortions, and
   dynamic effects", *Phys. Rev. B* **75**, 035427 (2007).
   [doi:10.1103/PhysRevB.75.035427](https://doi.org/10.1103/PhysRevB.75.035427)
5. G. Schwarz, "Estimating the dimension of a model", *Ann. Stat.* **6**,
   461–464 (1978).
   [doi:10.1214/aos/1176344136](https://doi.org/10.1214/aos/1176344136)
6. R. E. Kass, A. E. Raftery, "Bayes factors", *J. Am. Stat. Assoc.* **90**,
   773–795 (1995).
   [doi:10.1080/01621459.1995.10476572](https://doi.org/10.1080/01621459.1995.10476572)
