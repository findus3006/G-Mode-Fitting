"""Composite peak model, initial guesses and the least-squares fit (no Qt).

A model is a list of :class:`Peak` (line shape + label + :class:`Param` per
parameter, each with optional bounds and a *fixed* flag) plus a polynomial
baseline that is always fitted together with the peaks. :func:`fit` returns a
:class:`FitResult` with fitted values, 1σ uncertainties (from the Jacobian,
scaled by the reduced χ²), derived quantities (total FWHM, BWF maximum,
height) and the G⁻/G⁺ area ratio with error propagation that includes the
parameter correlations.

Example
-------
>>> from gmode_fit.io import load_spectrum
>>> from gmode_fit.fitting import preset, auto_guess, fit
>>> s = load_spectrum("tests/testdata/Probe1_633nm_G.txt")
>>> peaks = auto_guess(s.shift, s.y, preset("metallic"), "linear")
>>> result = fit(s.shift, s.y, peaks, "linear")
>>> result.ratio()   # (A(G⁻)/A(G⁺), error)
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares, lsq_linear
from scipy.signal import savgol_filter

from .lineshapes import (
    BASELINES,
    PEAK_KINDS,
    bwf_i0,
    bwf_maximum,
    polynomial_baseline,
    voigt_fwhm,
)

__all__ = [
    "Param",
    "Peak",
    "PRESETS",
    "preset",
    "normalize_label",
    "default_range",
    "evaluate",
    "auto_guess",
    "fit",
    "FitResult",
]

#: Default value and bounds per parameter name: (value, min, max).
_DEFAULTS: dict[str, tuple[float, float | None, float | None]] = {
    "area": (1000.0, 0.0, None),
    "center": (1590.0, None, None),
    "fwhm": (15.0, 0.5, 300.0),
    "fwhm_l": (12.0, 0.1, 300.0),
    "fwhm_g": (3.0, 0.01, 100.0),
    "inv_q": (-0.2, -2.0, 2.0),
}


@dataclass
class Param:
    """One fit parameter: start/fitted value, optional bounds, fixed flag."""

    value: float
    min: float | None = None
    max: float | None = None
    fixed: bool = False


@dataclass
class Peak:
    """One line of the model: type (key of ``PEAK_KINDS``), label and parameters."""

    kind: str
    label: str = ""
    params: dict[str, Param] = field(default_factory=dict)

    @classmethod
    def create(cls, kind: str, label: str = "", **values: float) -> Peak:
        """A peak with default parameters; ``values`` override start values."""
        params = {}
        for name in PEAK_KINDS[kind].params:
            value, lo, hi = _DEFAULTS[name]
            params[name] = Param(float(values.get(name, value)), lo, hi)
        return cls(kind, label, params)

    def converted(self, kind: str) -> Peak:
        """This peak as another line shape, keeping the values that carry over."""
        new = Peak.create(kind, self.label)
        old = {**self.params}
        # Width names differ between types: map single FWHM <-> Lorentzian FWHM.
        if "fwhm" in old and "fwhm_l" not in old:
            old["fwhm_l"] = old["fwhm"]
        if "fwhm_l" in old and "fwhm" not in old:
            old["fwhm"] = copy.copy(old["fwhm_l"])
            old["fwhm"].value = voigt_fwhm(old["fwhm_g"].value, old["fwhm_l"].value)
        for name in new.params:
            if name in old:
                new.params[name] = copy.copy(old[name])
        return new

    def values(self) -> dict[str, float]:
        return {name: p.value for name, p in self.params.items()}

    def curve(self, x: np.ndarray) -> np.ndarray:
        return PEAK_KINDS[self.kind].func(x, **self.values())


def normalize_label(label: str) -> str:
    """Map the spellings of G⁻/G⁺ (``G-``, ``G−``, ``G⁻``, ``Gminus`` …) onto ``G-``/``G+``."""
    text = label.strip().replace("−", "-").replace("⁻", "-").replace("⁺", "+")
    low = text.lower().replace(" ", "")
    if low in ("g-", "gminus", "g_minus"):
        return "G-"
    if low in ("g+", "gplus", "g_plus"):
        return "G+"
    return text


#: Ready-made models: key -> (display name, peak factory).
PRESETS: dict[str, tuple[str, Callable[[], list[Peak]]]] = {
    "semiconducting": ("Semiconducting: G⁻ Voigt + G⁺ Voigt", lambda: [
        Peak.create("Voigt", "G-", center=1570, fwhm_l=15),
        Peak.create("Voigt", "G+", center=1590, fwhm_l=12),
    ]),
    "metallic": ("Metallic: G⁻ BWF + G⁺ Voigt", lambda: [
        Peak.create("BWF", "G-", center=1550, fwhm=50, inv_q=-0.2),
        Peak.create("Voigt", "G+", center=1585, fwhm_l=15),
    ]),
    "single": ("Single Voigt", lambda: [Peak.create("Voigt", "G+", center=1590)]),
}


def preset(key: str) -> list[Peak]:
    """Fresh peak list of the preset ``key`` (see :data:`PRESETS`)."""
    return PRESETS[key][1]()


def default_range(x: np.ndarray, skip: int = 3) -> tuple[float, float]:
    """Full data range without the outermost points (detectors often spike there)."""
    x = np.sort(np.asarray(x, dtype=float))
    skip = min(skip, max((len(x) - 2) // 2, 0))
    return float(x[skip]), float(x[len(x) - 1 - skip])


def _window(x, y, x_range):
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x_range is None:
        mask = np.isfinite(x) & np.isfinite(y)
    else:
        lo, hi = sorted(x_range)
        mask = (x >= lo) & (x <= hi) & np.isfinite(y)
    return x[mask], y[mask]


def evaluate(x: np.ndarray, peaks: Sequence[Peak], baseline_coeffs: Sequence[float] = (),
             x_ref: float = 0.0) -> tuple[np.ndarray, list[np.ndarray], np.ndarray]:
    """``(total, [component curves], baseline curve)`` of the model at ``x``."""
    x = np.asarray(x, dtype=float)
    comps = [p.curve(x) for p in peaks]
    base = polynomial_baseline(x, baseline_coeffs, x_ref)
    total = base + (np.sum(comps, axis=0) if comps else 0.0)
    return total, comps, base


def start_model(x, y, peaks: Sequence[Peak], baseline: str = "linear",
                x_range: tuple[float, float] | None = None):
    """Curves of the model at its current (start) values inside ``x_range``.

    The baseline is a polynomial fitted to the data minus the peaks, as at the
    start of :func:`fit`. Returns ``(x, y, total, components, baseline, coeffs, x_ref)``.
    """
    xw, yw = _window(x, y, x_range)
    order = np.argsort(xw)
    xw, yw = xw[order], yw[order]
    x_ref = 0.5 * (xw[0] + xw[-1]) if len(xw) else 0.0
    degree = BASELINES[baseline]
    coeffs = np.zeros(0)
    if degree is not None and len(xw) > degree:
        peak_sum = sum((p.curve(xw) for p in peaks), np.zeros_like(xw))
        coeffs = np.polynomial.polynomial.polyfit(xw - x_ref, yw - peak_sum, degree)
    total, comps, base = evaluate(xw, peaks, coeffs, x_ref)
    return xw, yw, total, comps, base, coeffs, x_ref


def _edge_line(x, y):
    """Straight line through the medians of the first and last 5 % of the window."""
    n = max(3, len(x) // 20)
    x1, y1 = np.median(x[:n]), np.median(y[:n])
    x2, y2 = np.median(x[-n:]), np.median(y[-n:])
    slope = (y2 - y1) / (x2 - x1) if x2 != x1 else 0.0
    return y1 + slope * (x - x1)


def _smooth(y):
    window = min(len(y) // 2 * 2 - 1, 15)
    return savgol_filter(y, window, 2) if window >= 5 else y


def _half_max_width(x, y, i):
    """FWHM of the maximum at index ``i`` from the half-maximum crossings."""
    half = y[i] / 2
    left = i
    while left > 0 and y[left] > half:
        left -= 1
    right = i
    while right < len(y) - 1 and y[right] > half:
        right += 1
    return float(x[right] - x[left])


def _clip(value, param: Param):
    lo = -np.inf if param.min is None else param.min
    hi = np.inf if param.max is None else param.max
    return float(np.clip(value, lo, hi))


def _set(peak: Peak, name: str, value: float) -> None:
    """Set a start value unless the parameter is fixed (respecting its bounds)."""
    p = peak.params.get(name)
    if p is not None and not p.fixed:
        p.value = _clip(value, p)


def auto_guess(x, y, peaks: Sequence[Peak], baseline: str = "linear",
               x_range: tuple[float, float] | None = None) -> list[Peak]:
    """Start values from the data in ``x_range``; returns updated copies of ``peaks``.

    The G⁺ peak (label ``G+``, or the only peak) is put on the highest maximum
    with its width from the half-maximum crossings. G⁻ goes to the strongest
    remaining signal below G⁺. Other peaks keep their positions and widths.
    Then all non-fixed areas are solved linearly together with the baseline.
    Fixed parameters are never changed.
    """
    peaks = [copy.deepcopy(p) for p in peaks]
    xw, yw = _window(x, y, x_range)
    if len(xw) < 10 or not peaks:
        return peaks
    signal = _smooth(yw - _edge_line(xw, yw))
    labels = [normalize_label(p.label) for p in peaks]

    i_max = int(np.argmax(signal))
    x_max, height = float(xw[i_max]), float(signal[i_max])
    width = float(np.clip(_half_max_width(xw, signal, i_max), 3.0, 80.0))

    main = [p for p, lab in zip(peaks, labels) if lab == "G+"] or (peaks if len(peaks) == 1 else [])
    for p in main:
        _set(p, "center", x_max)
        if p.kind == "Voigt":
            fwhm_g = p.params["fwhm_g"].value
            _set(p, "fwhm_l", max(width - 0.5 * fwhm_g, 1.0))
        else:
            _set(p, "fwhm", width)
        _set(p, "area", height * width * np.pi / 2)

    remaining = signal - sum((p.curve(xw) for p in main), np.zeros_like(xw))
    below = xw < x_max - 5
    for p, lab in zip(peaks, labels):
        if lab != "G-" or not np.any(below):
            continue
        j = int(np.argmax(np.where(below, remaining, -np.inf)))
        center = float(xw[j])
        if p.kind == "BWF":
            # The BWF maximum lies at ω₀ + Γ/(2q); place ω₀ so the maximum lands here.
            fwhm, inv_q = p.params["fwhm"].value, p.params["inv_q"].value
            center -= 0.5 * fwhm * inv_q
        _set(p, "center", center)

    return _linear_areas(xw, yw, peaks, baseline)


def _linear_areas(x, y, peaks: list[Peak], baseline: str) -> list[Peak]:
    """Solve non-fixed areas (within their bounds) and the baseline linearly."""
    degree = BASELINES[baseline]
    x_ref = 0.5 * (x[0] + x[-1])
    columns, lo, hi, free = [], [], [], []
    target = y.copy()
    for p in peaks:
        a = p.params["area"]
        unit = PEAK_KINDS[p.kind].func(x, **{**p.values(), "area": 1.0})
        if a.fixed:
            target = target - a.value * unit
            continue
        columns.append(unit)
        lo.append(-np.inf if a.min is None else a.min)
        hi.append(np.inf if a.max is None else a.max)
        free.append(a)
    if degree is not None:
        for power in range(degree + 1):
            columns.append((x - x_ref) ** power)
            lo.append(-np.inf)
            hi.append(np.inf)
    if not columns:
        return peaks
    A = np.column_stack(columns)
    scale = np.max(np.abs(A), axis=0)
    scale[scale == 0] = 1.0
    sol = lsq_linear(A / scale, target, bounds=(np.array(lo) * scale, np.array(hi) * scale))
    coeffs = sol.x / scale
    for a, value in zip(free, coeffs):
        a.value = float(value)
    return peaks


@dataclass
class FitResult:
    """Outcome of :func:`fit`. ``peaks`` hold the fitted values."""

    peaks: list[Peak]
    errors: list[dict[str, float]]
    baseline: str
    baseline_coeffs: np.ndarray
    baseline_errors: np.ndarray
    x_ref: float
    x: np.ndarray
    y: np.ndarray
    best: np.ndarray
    components: list[np.ndarray]
    baseline_curve: np.ndarray
    success: bool
    message: str
    nfev: int
    chi2: float
    redchi: float
    r2: float
    n_free: int
    covariance: np.ndarray            # over the full parameter vector (fixed rows are 0)
    _index: dict[tuple[int, str], int] = field(repr=False, default_factory=dict)
    at_bounds: list[str] = field(default_factory=list)

    @property
    def residual(self) -> np.ndarray:
        return self.y - self.best

    @property
    def x_range(self) -> tuple[float, float]:
        return float(self.x[0]), float(self.x[-1])

    @property
    def bic(self) -> float:
        """Bayesian information criterion, n·ln(χ²/n) + k·ln(n) (k: free parameters incl. baseline).

        Only differences between fits of the *same* data points are meaningful:
        the model with the lower BIC is preferred; ΔBIC > 10 is strong evidence.
        """
        n = len(self.x)
        return n * np.log(self.chi2 / n) + self.n_free * np.log(n) if self.chi2 > 0 else np.nan

    def same_data(self, other: FitResult | None) -> bool:
        """``True`` when ``other`` was fitted to the identical data points (BIC comparable)."""
        return (other is not None and other.x.shape == self.x.shape
                and np.array_equal(other.x, self.x) and np.array_equal(other.y, self.y))

    # ---------------------------------------------------------- propagation
    def _vector(self) -> np.ndarray:
        vec = np.zeros(len(self._index))
        for (i, name), k in self._index.items():
            vec[k] = self.peaks[i].params[name].value
        return vec

    def propagate(self, func: Callable[[Callable[[int, str], float]], float]) -> tuple[float, float]:
        """Value and 1σ error of a derived quantity, including correlations.

        ``func(get)`` computes the quantity, where ``get(peak_index, name)``
        returns a parameter value.
        """
        vec = self._vector()

        def at(v):
            return float(func(lambda i, name: v[self._index[(i, name)]]))

        value = at(vec)
        grad = np.zeros_like(vec)
        for k in range(len(vec)):
            if self.covariance[k, k] <= 0:
                continue
            h = 1e-6 * max(abs(vec[k]), 1e-3)
            up, down = vec.copy(), vec.copy()
            up[k] += h
            down[k] -= h
            grad[k] = (at(up) - at(down)) / (2 * h)
        var = float(grad @ self.covariance @ grad)
        return value, float(np.sqrt(var)) if var > 0 else 0.0

    # ------------------------------------------------------- derived values
    def derived(self, i: int) -> dict[str, tuple[float, float]]:
        """Derived quantities of peak ``i``: total FWHM, maximum position, height (, I₀)."""
        peak = self.peaks[i]
        func = PEAK_KINDS[peak.kind].func
        out: dict[str, tuple[float, float]] = {}
        if peak.kind == "Voigt":
            out["fwhm_total"] = self.propagate(lambda g: voigt_fwhm(g(i, "fwhm_g"), g(i, "fwhm_l")))
        else:
            out["fwhm_total"] = self.propagate(lambda g: g(i, "fwhm"))
        if peak.kind == "BWF":
            out["position_max"] = self.propagate(
                lambda g: bwf_maximum(g(i, "center"), g(i, "fwhm"), g(i, "inv_q")))
            out["i0"] = self.propagate(lambda g: bwf_i0(g(i, "area"), g(i, "fwhm")))
        else:
            out["position_max"] = self.propagate(lambda g: g(i, "center"))

        def height(g):
            vals = {n: g(i, n) for n in peak.params}
            pos = (bwf_maximum(vals["center"], vals["fwhm"], vals["inv_q"])
                   if peak.kind == "BWF" else vals["center"])
            return func(np.array([pos]), **vals)[0]

        out["height"] = self.propagate(height)
        return out

    def label_indices(self, label: str) -> list[int]:
        return [i for i, p in enumerate(self.peaks) if normalize_label(p.label) == label]

    def area(self, label: str) -> tuple[float, float]:
        """Summed area (± error) of all peaks with this label (``"G-"``, ``"G+"`` …)."""
        idx = self.label_indices(label)
        if not idx:
            return np.nan, np.nan
        return self.propagate(lambda g: sum(g(i, "area") for i in idx))

    def ratio(self, num: str = "G-", den: str = "G+") -> tuple[float, float]:
        """Area ratio A(num)/A(den) ± error (NaN when a label is missing)."""
        i_num, i_den = self.label_indices(num), self.label_indices(den)
        if not i_num or not i_den:
            return np.nan, np.nan

        def r(g):
            d = sum(g(i, "area") for i in i_den)
            return sum(g(i, "area") for i in i_num) / d if d else np.nan

        return self.propagate(r)

    # --------------------------------------------------------------- export
    def table(self) -> list[dict]:
        """One row per peak with all parameters, errors and derived values."""
        rows = []
        for i, peak in enumerate(self.peaks):
            row = {"label": peak.label, "type": peak.kind}
            for name, p in peak.params.items():
                row[name] = p.value
                row[f"{name}_err"] = self.errors[i].get(name, np.nan)
                row[f"{name}_fixed"] = p.fixed
            for name, (v, e) in self.derived(i).items():
                row[name] = v
                row[f"{name}_err"] = e
            rows.append(row)
        return rows

    def summary(self) -> dict:
        """Fixed-column summary (G⁻, G⁺, ratio, quality) for the summary CSV."""
        out: dict = {}
        for lab, key in (("G-", "Gminus"), ("G+", "Gplus")):
            idx = self.label_indices(lab)
            single = len(idx) == 1
            out[f"{key}_type"] = "+".join(self.peaks[i].kind for i in idx)
            for name in ("position_max", "center", "fwhm_total"):
                if single:
                    i = idx[0]
                    if name == "center":
                        v, e = self.peaks[i].params["center"].value, self.errors[i]["center"]
                    else:
                        v, e = self.derived(i)[name]
                else:
                    v, e = np.nan, np.nan
                out[f"{key}_{name}"], out[f"{key}_{name}_err"] = v, e
            out[f"{key}_area"], out[f"{key}_area_err"] = self.area(lab)
            inv_q = [self.peaks[i].params["inv_q"].value for i in idx if "inv_q" in self.peaks[i].params]
            inv_q_err = [self.errors[i]["inv_q"] for i in idx if "inv_q" in self.peaks[i].params]
            out[f"{key}_inv_q"] = inv_q[0] if len(inv_q) == 1 else np.nan
            out[f"{key}_inv_q_err"] = inv_q_err[0] if len(inv_q_err) == 1 else np.nan
        out["ratio_Gminus_Gplus"], out["ratio_err"] = self.ratio()
        out["R2"] = self.r2
        out["chi2_red"] = self.redchi
        out["BIC"] = self.bic
        out["n_free"] = self.n_free
        out["n_points"] = len(self.x)
        out["converged"] = self.success
        return out


def _bounds(param: Param, name: str, x_lo: float, x_hi: float) -> tuple[float, float]:
    lo = -np.inf if param.min is None else param.min
    hi = np.inf if param.max is None else param.max
    if name == "center":
        # Open position bounds: keep the peak near the fit window.
        pad = 0.15 * (x_hi - x_lo)
        lo = max(lo, x_lo - pad)
        hi = min(hi, x_hi + pad)
    return lo, hi


def fit(x, y, peaks: Sequence[Peak], baseline: str = "linear",
        x_range: tuple[float, float] | None = None, *, max_nfev: int = 20000) -> FitResult:
    """Fit ``peaks`` plus a polynomial ``baseline`` to ``y(x)`` inside ``x_range``.

    The peaks' current values are the start values (see :func:`auto_guess`);
    the baseline starts from a polynomial fit to the data minus the peaks.
    Fixed parameters stay at their value. The returned peaks are copies.
    """
    if baseline not in BASELINES:
        raise ValueError(f"Unknown baseline {baseline!r}; use one of {list(BASELINES)}.")
    peaks = [copy.deepcopy(p) for p in peaks]
    xw, yw = _window(x, y, x_range)
    order = np.argsort(xw)
    xw, yw = xw[order], yw[order]
    degree = BASELINES[baseline]
    n_base = 0 if degree is None else degree + 1
    x_ref = 0.5 * (xw[0] + xw[-1]) if len(xw) else 0.0

    # Parameter bookkeeping: full vector = all peak params, then baseline coeffs.
    index: dict[tuple[int, str], int] = {}
    free_keys: list[tuple[int, str]] = []
    lo, hi, p0 = [], [], []
    for i, peak in enumerate(peaks):
        for name, p in peak.params.items():
            index[(i, name)] = len(index)
            if p.fixed:
                continue
            b = _bounds(p, name, xw[0], xw[-1])
            if b[0] >= b[1]:
                raise ValueError(f"Peak {i + 1} ({peak.label or peak.kind}): lower bound of "
                                 f"{name} is not below the upper bound.")
            free_keys.append((i, name))
            lo.append(b[0])
            hi.append(b[1])
            p0.append(float(np.clip(p.value, *b)))
    n_free = len(free_keys) + n_base
    if len(xw) <= n_free:
        raise ValueError(f"The fit range holds {len(xw)} points but the model has "
                         f"{n_free} free parameters; select a larger range.")

    def assign(v):
        for (i, name), value in zip(free_keys, v[:len(free_keys)]):
            peaks[i].params[name].value = value
        return v[len(free_keys):]

    if n_base:
        p0 += list(start_model(xw, yw, peaks, baseline)[5])
        lo += [-np.inf] * n_base
        hi += [np.inf] * n_base

    def residual(v):
        coeffs = assign(v)
        return evaluate(xw, peaks, coeffs, x_ref)[0] - yw

    sol = least_squares(residual, np.array(p0, dtype=float), bounds=(lo, hi), method="trf",
                        x_scale="jac", max_nfev=max_nfev)
    coeffs = np.array(assign(sol.x))
    best, comps, base = evaluate(xw, peaks, coeffs, x_ref)

    dof = max(len(xw) - n_free, 1)
    chi2 = float(np.sum((yw - best) ** 2))
    redchi = chi2 / dof
    ss_tot = float(np.sum((yw - yw.mean()) ** 2))
    r2 = 1.0 - chi2 / ss_tot if ss_tot > 0 else np.nan

    J = sol.jac
    try:
        cov_free = np.linalg.pinv(J.T @ J) * redchi
    except np.linalg.LinAlgError:
        cov_free = np.full((n_free, n_free), np.nan)
    errs_free = np.sqrt(np.clip(np.diag(cov_free), 0, None))

    n_peak_params = len(index)
    for k in range(n_base):
        index[(-1, f"c{k}")] = n_peak_params + k
    full = np.zeros((len(index), len(index)))
    free_full = [index[key] for key in free_keys] + [n_peak_params + k for k in range(n_base)]
    full[np.ix_(free_full, free_full)] = np.nan_to_num(cov_free)

    errors: list[dict[str, float]] = [{name: 0.0 for name in p.params} for p in peaks]
    at_bounds = []
    for (i, name), err, value, b_lo, b_hi in zip(free_keys, errs_free, sol.x, lo, hi):
        errors[i][name] = float(err)
        tol = 1e-6 * max(abs(value), 1.0)
        if abs(value - b_lo) < tol or abs(value - b_hi) < tol:
            at_bounds.append(f"{peaks[i].label or peaks[i].kind}: {name}")

    # Baseline coefficients are not peak parameters; keep the propagation index
    # to peak parameters only (c* entries are used for the covariance layout).
    peak_index = {key: k for key, k in index.items() if key[0] >= 0}
    return FitResult(
        peaks=peaks, errors=errors, baseline=baseline, baseline_coeffs=coeffs,
        baseline_errors=errs_free[len(free_keys):], x_ref=x_ref, x=xw, y=yw, best=best,
        components=comps, baseline_curve=base, success=bool(sol.success),
        message=str(sol.message), nfev=int(sol.nfev), chi2=chi2, redchi=redchi, r2=r2,
        n_free=n_free, covariance=full[:n_peak_params, :n_peak_params], _index=peak_index,
        at_bounds=at_bounds,
    )
