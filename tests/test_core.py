import numpy as np
import pytest
from scipy.integrate import quad

from gmode_fit.fitting import Peak, auto_guess, default_range, fit, normalize_label, preset
from gmode_fit.io import detect_unit, laser_from_filename, load_spectrum, to_raman_shift
from gmode_fit.lineshapes import bwf, bwf_maximum, gauss, lorentz, voigt, voigt_fwhm

from conftest import DATA, needs_data

FILES = sorted(DATA.glob("*.txt"))


# ------------------------------------------------------------------ lineshapes
@pytest.mark.parametrize("func,args", [
    (gauss, (5.0,)), (lorentz, (5.0,)), (voigt, (3.0, 6.0)),
])
def test_area_parameter_is_integral(func, args):
    # Split at the centre so quad sees the narrow peak; infinite limits cover the tails.
    f = lambda x: func(x, 123.0, 1590.0, *args)  # noqa: E731
    integral = sum(quad(f, a, b, limit=500)[0] for a, b in
                   ((-np.inf, 1500), (1500, 1590), (1590, 1680), (1680, np.inf)))
    assert integral == pytest.approx(123.0, rel=1e-6)


def test_bwf_reduces_to_lorentzian_and_maximum():
    x = np.linspace(1400, 1700, 3001)
    assert np.allclose(bwf(x, 50.0, 1550.0, 40.0, 0.0), lorentz(x, 50.0, 1550.0, 40.0))
    y = bwf(x, 50.0, 1550.0, 40.0, -0.3)
    assert x[np.argmax(y)] == pytest.approx(bwf_maximum(1550.0, 40.0, -0.3), abs=0.15)


def test_voigt_fwhm_matches_numeric():
    x = np.linspace(1500, 1680, 200001)
    y = voigt(x, 1.0, 1590.0, 4.0, 8.0)
    above = x[y >= y.max() / 2]
    assert above[-1] - above[0] == pytest.approx(voigt_fwhm(4.0, 8.0), rel=1e-3)


# -------------------------------------------------------------------------- io
def test_laser_from_filename():
    assert laser_from_filename("Probe1_532nm_G.txt") == 532.0
    assert laser_from_filename("x_632.8 nm.txt") == 632.8
    assert laser_from_filename("Probe1_G.txt") is None


@needs_data
def test_unit_detection_on_real_files():
    units = {f.name: load_spectrum(f).unit for f in FILES}
    assert units == {"Probe1_532nm_G.txt": "nm", "Probe1_633nm_G.txt": "cm-1",
                     "Probe2_532nm_G.txt": "nm", "Probe2_633nm_G.txt": "nm"}
    assert detect_unit(np.array([1500.0, 1700.0]), None) == "cm-1"


@needs_data
def test_conversion_and_offset():
    shift = to_raman_shift(np.array([578.10193]), 532.0)
    assert shift[0] == pytest.approx(1e7 / 532 - 1e7 / 578.10193)
    f = DATA / "Probe1_532nm_G.txt"
    a, b = load_spectrum(f), load_spectrum(f, offset=-15.0)
    assert np.allclose(b.shift, a.shift - 15.0)
    assert np.all(np.diff(a.shift) > 0)


def test_decimal_comma(tmp_path):
    p = tmp_path / "s_633nm.txt"
    p.write_text("header\n" + "\n".join(f"{1500 + i},5\t{100 + i}" for i in range(20)))
    s = load_spectrum(p)
    assert s.unit == "cm-1" and s.shift[0] == 1500.5


# --------------------------------------------------------------------- fitting
def _synthetic(seed=0):
    rng = np.random.default_rng(seed)
    x = np.linspace(1480, 1680, 1200)
    truth = [Peak.create("BWF", "G-", area=3000, center=1552, fwhm=45, inv_q=-0.25),
             Peak.create("Voigt", "G+", area=2000, center=1592, fwhm_g=4, fwhm_l=10)]
    y = 900 + 0.3 * (x - 1580) + sum(p.curve(x) for p in truth)
    return x, y + rng.normal(0, 1.0, x.size), truth


def test_fit_recovers_synthetic_metallic_spectrum():
    x, y, truth = _synthetic()
    model = preset("metallic")
    model[1].params["fwhm_g"].value = 4.0
    model[1].params["fwhm_g"].fixed = True          # known instrument function
    start = auto_guess(x, y, model, "linear", default_range(x))
    r = fit(x, y, start, "linear", default_range(x))
    assert r.success and r.r2 > 0.998
    g_minus, g_plus = r.peaks
    assert g_minus.params["inv_q"].value == pytest.approx(-0.25, abs=0.02)
    assert g_minus.params["area"].value == pytest.approx(3000, rel=0.03)
    assert g_plus.params["area"].value == pytest.approx(2000, rel=0.02)
    assert g_plus.params["fwhm_g"].value == 4.0 and r.errors[1]["fwhm_g"] == 0.0
    ratio, err = r.ratio()
    assert ratio == pytest.approx(1.5, rel=0.04)
    assert 0 < err < 0.1
    assert r.redchi == pytest.approx(1.0, rel=0.15)   # noise σ = 1


def test_error_propagation_matches_scatter():
    """The ratio error from the covariance agrees with the scatter over noise draws."""
    ratios, errs = [], []
    for seed in range(15):
        x, y, _ = _synthetic(seed)
        start = auto_guess(x, y, preset("metallic"), "linear", default_range(x))
        r = fit(x, y, start, "linear", default_range(x))
        ratios.append(r.ratio()[0])
        errs.append(r.ratio()[1])
    assert np.std(ratios) == pytest.approx(np.mean(errs), rel=0.5)


def test_fixed_and_bounds_respected():
    x, y, _ = _synthetic()
    model = preset("semiconducting")
    model[0].params["center"].min, model[0].params["center"].max = 1540, 1560
    model[1].params["center"].value, model[1].params["center"].fixed = 1600.0, True
    r = fit(x, y, auto_guess(x, y, model, "linear"), "linear")
    assert 1540 <= r.peaks[0].params["center"].value <= 1560
    assert r.peaks[1].params["center"].value == 1600.0


def test_converted_keeps_values():
    p = Peak.create("Voigt", "G-", area=10, center=1570, fwhm_g=2, fwhm_l=8)
    b = p.converted("BWF")
    assert b.kind == "BWF" and b.params["center"].value == 1570
    assert b.params["fwhm"].value == pytest.approx(voigt_fwhm(2, 8))
    assert b.converted("Voigt").params["fwhm_l"].value == pytest.approx(voigt_fwhm(2, 8))


def test_labels():
    assert {normalize_label(t) for t in ("G-", "G−", "G⁻", " g- ")} == {"G-"}
    assert normalize_label("G⁺") == "G+"


def test_too_few_points():
    x, y, _ = _synthetic()
    with pytest.raises(ValueError, match="free parameters"):
        fit(x, y, preset("metallic"), "linear", (1590, 1591))


@needs_data
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
@pytest.mark.parametrize("key", ["semiconducting", "metallic"])
def test_real_files_fit(path, key):
    s = load_spectrum(path)
    rng = default_range(s.shift)
    r = fit(s.shift, s.y, auto_guess(s.shift, s.y, preset(key), "linear", rng), "linear", rng)
    assert r.success and r.r2 > 0.9
    summary = r.summary()
    assert np.isfinite(summary["ratio_Gminus_Gplus"])
    assert len(r.table()) == 2
