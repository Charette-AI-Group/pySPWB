"""Nastran punch reading: block detection and the three output flavours.

The three flavours differ only in how many lines a frequency point costs and
how those numbers combine into a complex value - which is exactly the part
that fails silently, so each one is pinned against a value computed by hand.
"""
import numpy as np
import pytest

from spwb.processing.io import FRF, pch_contents, read_pch

FREQS = (10.0, 20.0, 30.0)


def data_line(first, values):
    """``   1.0E+01       G   v1   v2   v3``."""
    head = f"{first:>15.6E}" if isinstance(first, float) else f"{first:>15d}"
    return head + "       G" + "".join(f"{v:>15.6E}" for v in values)


def cont_line(values):
    return "-CONT-         " + "        " + "".join(f"{v:>15.6E}"
                                                    for v in values)


def block(output_type, rows, *, title="MY MODEL", subtitle="RUN 3",
          label="ACCEL", subcase=1, point=1001, unit="$DISPLACEMENTS"):
    lines = [
        f"$TITLE   = {title}",
        f"$SUBTITLE= {subtitle}",
        f"$LABEL   = {label}",
        f"$SUBCASE ID = {subcase:>11d}",
        unit,
        output_type,
    ]
    if point is not None:
        lines.insert(4, f"$POINT ID = {point:>11d}")
    return lines + rows


def write(tmp_path, lines, name="run.pch"):
    path = tmp_path / name
    path.write_text("\n".join(lines) + "\n", encoding="latin-1")
    return path


# -- $REAL OUTPUT: 2 lines per frequency, imaginary part is zero -----------
def real_rows():
    rows = []
    for i, f in enumerate(FREQS):
        rows.append(data_line(f, [1.0 + i, 2.0 + i, 3.0 + i]))
        rows.append(cont_line([4.0 + i, 5.0 + i, 6.0 + i]))
    return rows


def test_real_output_has_no_imaginary_part(tmp_path):
    path = write(tmp_path, block("$REAL OUTPUT", real_rows()))

    frf, = read_pch(path)

    assert frf.output_type == "$REAL OUTPUT"
    np.testing.assert_allclose(frf.abscissa, FREQS)
    np.testing.assert_allclose(frf.x, [1.0, 2.0, 3.0])
    np.testing.assert_allclose(frf.z, [3.0, 4.0, 5.0])
    np.testing.assert_allclose(frf.w, [6.0, 7.0, 8.0])
    assert np.all(frf.x.imag == 0)


# -- $REAL-IMAGINARY OUTPUT: 4 lines, real pair then imaginary pair --------
def test_real_imaginary_pairs_lines_1_2_with_3_4(tmp_path):
    rows = [
        data_line(10.0, [1.0, 2.0, 3.0]),
        cont_line([4.0, 5.0, 6.0]),
        cont_line([-1.0, -2.0, -3.0]),
        cont_line([-4.0, -5.0, -6.0]),
    ]
    path = write(tmp_path, block("$REAL-IMAGINARY OUTPUT", rows))

    frf, = read_pch(path)

    assert frf.n_samples == 1
    assert frf.x[0] == pytest.approx(1.0 - 1.0j)
    assert frf.z[0] == pytest.approx(3.0 - 3.0j)
    assert frf.u[0] == pytest.approx(4.0 - 4.0j)
    assert frf.w[0] == pytest.approx(6.0 - 6.0j)


# -- $MAGNITUDE-PHASE OUTPUT: 4 lines, phase in degrees -------------------
def test_magnitude_phase_converts_degrees_to_a_complex_value(tmp_path):
    rows = [
        data_line(10.0, [2.0, 4.0, 8.0]),
        cont_line([1.0, 1.0, 1.0]),
        cont_line([0.0, 90.0, 180.0]),
        cont_line([45.0, -90.0, 270.0]),
    ]
    path = write(tmp_path, block("$MAGNITUDE-PHASE OUTPUT", rows))

    frf, = read_pch(path)

    assert frf.x[0] == pytest.approx(2.0 + 0j)
    assert frf.y[0] == pytest.approx(4.0j)
    assert frf.z[0] == pytest.approx(-8.0 + 0j, abs=1e-12)
    assert frf.u[0] == pytest.approx(np.sqrt(0.5) * (1 + 1j))
    assert frf.v[0] == pytest.approx(-1.0j)


def test_an_unknown_output_type_is_read_as_magnitude_phase(tmp_path):
    """The LabVIEW case structure makes magnitude-phase its default frame."""
    rows = [
        data_line(10.0, [2.0, 2.0, 2.0]),
        cont_line([2.0, 2.0, 2.0]),
        cont_line([0.0, 0.0, 0.0]),
        cont_line([0.0, 0.0, 0.0]),
    ]
    path = write(tmp_path, block("$SOMETHING ELSE", rows))

    frf, = read_pch(path)

    assert frf.output_type == "$MAGNITUDE-PHASE OUTPUT"
    assert frf.x[0] == pytest.approx(2.0 + 0j)


# -- header parsing --------------------------------------------------------
def test_header_fields_and_sort2_naming(tmp_path):
    path = write(tmp_path, block("$REAL OUTPUT", real_rows()))

    frf, = read_pch(path)

    assert frf.title == "MY MODEL"
    assert frf.sub_title == "RUN 3"
    assert frf.storage_type == "Sort2"
    assert frf.point_id == 1001
    assert frf.subcase_id == 1
    assert frf.name == "ACCEL (PID 1001)"
    assert frf.unit_type == "displacement"
    assert frf.unit == "mm"
    assert frf.source.endswith("run.pch")


def test_without_a_point_id_the_block_is_sort1(tmp_path):
    path = write(tmp_path, block("$REAL OUTPUT", real_rows(), point=None))

    frf, = read_pch(path)

    assert frf.storage_type == "Sort1"
    assert frf.point_id == 0
    assert frf.name == "ACCEL"


@pytest.mark.parametrize("keyword,expected", [
    ("$DISPLACEMENTS", ("displacement", "mm")),
    ("$VELOCITY", ("velocity", "mm/s")),
    ("$ACCELERATION", ("acceleration", "m/s^2")),
    ("$SPCFORCES", ("displacement", "mm")),  # unknown -> the default frame
])
def test_unit_type_comes_from_the_header_keyword(tmp_path, keyword, expected):
    path = write(tmp_path,
                 block("$REAL OUTPUT", real_rows(), unit=keyword))

    frf, = read_pch(path)

    assert (frf.unit_type, frf.unit) == expected


def test_header_order_does_not_matter(tmp_path):
    """Nastran versions disagree on where $SUBCASE ID / $POINT ID go."""
    lines = [
        "$TITLE   = MY MODEL",
        "$SUBTITLE= RUN 3",
        "$LABEL   = ACCEL",
        "$DISPLACEMENTS",
        "$REAL OUTPUT",
        "$SUBCASE ID =           7",
        "$POINT ID =          1001",
        *real_rows(),
    ]
    path = write(tmp_path, lines)

    frf, = read_pch(path)

    assert frf.subcase_id == 7
    assert frf.point_id == 1001
    assert frf.output_type == "$REAL OUTPUT"
    np.testing.assert_allclose(frf.abscissa, FREQS)


# -- multiple blocks, and the failure messages ----------------------------
def test_every_block_in_the_file_is_returned(tmp_path):
    lines = (block("$REAL OUTPUT", real_rows(), point=1001)
             + block("$REAL OUTPUT", real_rows(), point=1002, label="MIC"))
    path = write(tmp_path, lines)

    info = pch_contents(path)
    frfs = read_pch(path)

    assert len(info) == len(frfs) == 2
    assert [f.point_id for f in frfs] == [1001, 1002]
    assert [f.name for f in frfs] == ["ACCEL (PID 1001)", "MIC (PID 1002)"]
    assert info[1].header_start > info[0].data_start
    assert info[0].data_length == 6


def test_trailing_blank_lines_are_not_data(tmp_path):
    path = write(tmp_path, [*block("$REAL OUTPUT", real_rows()), "", "  "])

    frf, = read_pch(path)

    assert frf.n_samples == 3


def test_a_file_with_no_title_block_says_so(tmp_path):
    path = write(tmp_path, ["nothing to see", "1.0 2.0 3.0"])

    with pytest.raises(ValueError, match=r"\$TITLE"):
        read_pch(path)


def test_a_block_with_a_ragged_line_count_says_so(tmp_path):
    rows = real_rows()[:-1]  # drop one continuation line
    path = write(tmp_path, block("$REAL OUTPUT", rows))

    with pytest.raises(ValueError, match="not a whole number"):
        read_pch(path)


def test_a_short_data_line_names_the_line(tmp_path):
    rows = [data_line(10.0, [1.0, 2.0]), cont_line([4.0, 5.0, 6.0])]
    path = write(tmp_path, block("$REAL OUTPUT", rows))

    with pytest.raises(ValueError, match="expected at least 4"):
        read_pch(path)


def test_fortran_d_exponents_are_read(tmp_path):
    rows = [
        "   1.000000E+01       G   1.000000D-03   2.000000D-03   3.000000D-03",
        "-CONT-                    4.000000D-03   5.000000D-03   6.000000D-03",
    ]
    path = write(tmp_path, block("$REAL OUTPUT", rows))

    frf, = read_pch(path)

    assert frf.x[0] == pytest.approx(1e-3)
    assert frf.w[0] == pytest.approx(6e-3)


def test_frf_reports_its_six_components():
    frf = FRF(name="ACCEL", abscissa=np.arange(3.0))
    assert list(frf.components) == ["x", "y", "z", "u", "v", "w"]
    assert frf.n_samples == 3
    assert "ACCEL" in repr(frf)


def test_there_is_no_pch_writer():
    """The port is read-only for punch files; keep it that way."""
    from spwb.processing.io import pch

    assert not [n for n in dir(pch) if n.startswith("write")]
