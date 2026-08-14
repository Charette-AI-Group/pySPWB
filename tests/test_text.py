"""Text/CSV IO: the office-friendly schema, and the LabVIEW fallbacks.

Two things are being pinned here. First, that a file written by this module
survives a round trip *exactly* - which is the whole reason the ``#``
metadata block exists, since re-deriving dt and units from a rounded time
column cannot do it. Second, that files written by the LabVIEW original
still read, through the same heuristics its VIs used.

The Excel-facing details (BOM, locale separators, the row limit) get tests
of their own because they are the difference between a file that opens on
a double-click and one that lands in a single text column.
"""
import numpy as np
import pytest

from spwb import Signal
from spwb.processing.io import (
    EXCEL_MAX_ROWS,
    read_text,
    read_text_frf,
    split_name_unit,
    text_contents,
    write_text,
)
from spwb.processing.io.text import find_data_start, infer_timing

FS = 8192.0
DT = 1.0 / FS
N = 64


def signals(n=N):
    t = np.arange(n) * DT
    return [
        Signal("Accel X", 9.81 * np.sin(2 * np.pi * 100 * t), DT,
               y_unit="m/s^2"),
        Signal("Mic", 0.5 * np.cos(2 * np.pi * 200 * t), DT, y_unit="Pa"),
    ]


@pytest.fixture
def csv_path(tmp_path):
    return write_text(tmp_path / "run.csv", signals())


# -- the round trip that justifies the schema -----------------------------
def test_round_trip_is_exact(csv_path):
    original = signals()

    restored = read_text(csv_path)

    assert len(restored) == 2
    for before, after in zip(original, restored, strict=True):
        assert after.name == before.name
        assert after.y_unit == before.y_unit
        assert after.x_unit == before.x_unit
        assert after.dt == before.dt          # exactly, not approximately
        assert after.t0 == before.t0
        np.testing.assert_array_equal(after.y, before.y)


def test_shortest_representation_round_trips_but_nine_digits_does_not(tmp_path):
    """SPWB wrote 9 significant digits, which loses a float64."""
    awkward = Signal("odd", np.array([0.1, 1 / 3, 1e-17, 12345.6789012345]),
                     DT)

    exact = read_text(write_text(tmp_path / "exact.csv", [awkward]))[0]
    lossy = read_text(write_text(tmp_path / "lossy.csv", [awkward],
                                 precision=9))[0]

    np.testing.assert_array_equal(exact.y, awkward.y)
    assert not np.array_equal(lossy.y, awkward.y)
    np.testing.assert_allclose(lossy.y, awkward.y, rtol=1e-8)


def test_per_signal_t0_survives_the_metadata_block(tmp_path):
    """One time column cannot express two different t0 values; the block can."""
    a, b = signals()
    b = b.with_(t0=0.25)

    path = write_text(tmp_path / "offset.csv", [a, b])
    first, second = read_text(path)

    assert first.t0 == 0.0
    assert second.t0 == 0.25


def test_attributes_ride_along(tmp_path):
    sig = signals()[0].with_(attributes={"Calibration": "94",
                                         "Physical Quantity": "acceleration"})

    restored, = read_text(write_text(tmp_path / "attrs.csv", [sig]))

    assert restored.attributes["Calibration"] == "94"
    assert restored.attributes["Physical Quantity"] == "acceleration"


def test_unrepresentable_attributes_are_dropped_not_stringified(tmp_path):
    """A lambda must not be stored as its memory address."""
    sig = signals()[0].with_(attributes={"good": 1, "bad": lambda x: x})

    path = write_text(tmp_path / "odd_attrs.csv", [sig])
    restored, = read_text(path)

    assert restored.attributes["good"] == 1
    assert "bad" not in restored.attributes
    assert "0x" not in path.read_text(encoding="utf-8-sig")


# -- what Excel and LibreOffice actually need -----------------------------
def test_the_file_starts_with_a_bom_so_excel_keeps_the_units(tmp_path):
    """Without the BOM, 'µm/s²' arrives in Excel as mojibake."""
    sig = Signal("Vib", np.zeros(8), DT, y_unit="µm/s²")

    path = write_text(tmp_path / "unicode.csv", [sig])

    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert "µm/s²" in path.read_text(encoding="utf-8-sig")
    assert read_text(path)[0].y_unit == "µm/s²"


def test_french_locale_uses_semicolons_and_decimal_commas(tmp_path):
    path = write_text(tmp_path / "fr.csv", signals(), locale="fr")

    text = path.read_text(encoding="utf-8-sig")
    header = text.splitlines()[3]
    assert ";" in header and "," not in header
    assert "0,0" in text.splitlines()[4]      # decimal comma

    restored = read_text(path)                # and it sniffs back correctly
    np.testing.assert_array_equal(restored[0].y, signals()[0].y)


def test_a_delimiter_that_is_also_the_decimal_point_is_refused(tmp_path):
    with pytest.raises(ValueError, match="cannot be parsed back"):
        write_text(tmp_path / "bad.csv", signals(), delimiter=",", decimal=",")


def test_exceeding_the_spreadsheet_row_limit_is_refused(tmp_path):
    big = Signal("long", np.zeros(EXCEL_MAX_ROWS + 10), DT)

    with pytest.raises(ValueError, match=str(EXCEL_MAX_ROWS)):
        write_text(tmp_path / "huge.csv", [big])

    # ...unless the file is explicitly not for a spreadsheet
    path = write_text(tmp_path / "huge.csv", [big], check_excel_limit=False,
                      metadata="none", time_column=False)
    assert path.exists()


def test_names_containing_the_delimiter_are_quoted(tmp_path):
    sig = Signal("Left, Right", np.zeros(8), DT, y_unit="Pa")

    path = write_text(tmp_path / "comma.csv", [sig])

    assert '"Left, Right [Pa]"' in path.read_text(encoding="utf-8-sig")
    assert read_text(path)[0].name == "Left, Right"


def test_signals_that_cannot_share_one_table_are_refused(tmp_path):
    a = Signal("a", np.zeros(10), DT)
    b = Signal("b", np.zeros(20), DT)
    c = Signal("c", np.zeros(10), DT * 2)

    with pytest.raises(ValueError, match="one column length"):
        write_text(tmp_path / "ragged.csv", [a, b])
    with pytest.raises(ValueError, match="sampling"):
        write_text(tmp_path / "mixed.csv", [a, c])


# -- options ---------------------------------------------------------------
def test_metadata_none_writes_a_bare_table(tmp_path):
    path = write_text(tmp_path / "bare.csv", signals(), metadata="none")

    lines = path.read_text(encoding="utf-8-sig").splitlines()
    assert not lines[0].startswith("#")
    assert lines[0] == "Time [s],Accel X [m/s^2],Mic [Pa]"

    restored = read_text(path)                # heuristics still recover it
    assert [s.name for s in restored] == ["Accel X", "Mic"]
    assert [s.y_unit for s in restored] == ["m/s^2", "Pa"]
    assert restored[0].dt == pytest.approx(DT)


def test_time_column_can_be_omitted(tmp_path):
    path = write_text(tmp_path / "notime.csv", signals(), time_column=False)

    assert path.read_text(encoding="utf-8-sig").splitlines()[3] == \
        "Accel X [m/s^2],Mic [Pa]"
    restored = read_text(path)
    assert [s.name for s in restored] == ["Accel X", "Mic"]
    assert restored[0].dt == pytest.approx(DT)   # recovered from the block


def test_contents_lists_columns_without_importing(csv_path):
    info = text_contents(csv_path)

    assert [c.channel for c in info] == ["Accel X", "Mic"]
    assert [c.y_unit for c in info] == ["m/s^2", "Pa"]
    assert [c.n_samples for c in info] == [N, N]
    assert info[0].dt == pytest.approx(DT)
    assert info[0].duration == pytest.approx(N * DT)
    assert info[0].is_waveform
    assert "Accel X" in repr(info[0])


def test_contents_of_a_plain_file_still_finds_the_columns(tmp_path):
    path = write_text(tmp_path / "bare.csv", signals(), metadata="none")

    info = text_contents(path)

    assert [c.channel for c in info] == ["Accel X", "Mic"]
    assert info[0].dt == pytest.approx(DT)   # derived from the time column


def test_selection_by_name_and_index(csv_path):
    assert [s.name for s in read_text(csv_path, select=["Mic"])] == ["Mic"]
    assert [s.name for s in read_text(csv_path, select=[1])] == ["Accel X"]

    with pytest.raises(KeyError, match="Tacho"):
        read_text(csv_path, select=["Tacho"])


# -- the LabVIEW conventions ----------------------------------------------
def test_reads_a_file_written_by_the_labview_application(tmp_path):
    """One header row of 'Name (Unit)', a time column, 9 digits, no block."""
    path = tmp_path / "labview.csv"
    rows = ["Time (sec),Accel X (m/s^2),Mic (Pa)"]
    for i in range(32):
        rows.append(f"{i * DT:.9g},{i * 0.5:.9g},{-i * 0.25:.9g}")
    path.write_text("\r\n".join(rows) + "\r\n", encoding="utf-8")

    accel, mic = read_text(path)

    assert (accel.name, accel.y_unit) == ("Accel X", "m/s^2")
    assert (mic.name, mic.y_unit) == ("Mic", "Pa")
    assert accel.x_unit == "sec"
    assert accel.dt == pytest.approx(DT)
    np.testing.assert_allclose(accel.y, np.arange(32) * 0.5)


@pytest.mark.parametrize("cell,expected", [
    ("Accel X (m/s^2)", ("Accel X", "m/s^2")),
    ("Accel X [m/s^2]", ("Accel X", "m/s^2")),
    ("Accel X - m/s^2", ("Accel X", "m/s^2")),
    ("Time (sec)", ("Time", "sec")),
    ("NoUnit", ("NoUnit", "")),
    ("", ("", "")),
    # SPWB's own example: the dashes are part of the name, so the bracket
    # has to win - which is what the VI's "Last Item" mode does
    ("Ref Mic - Exp2010 - Gen I (N1)", ("Ref Mic - Exp2010 - Gen I", "N1")),
])
def test_split_name_unit(cell, expected):
    assert split_name_unit(cell) == expected


def test_row_wise_files_are_transposed(tmp_path):
    """'There will always be many more samples than signals' - CSV to fWform."""
    path = tmp_path / "rowwise.csv"
    times = ",".join(f"{i * DT:.9g}" for i in range(40))
    values = ",".join(str(float(i)) for i in range(40))
    path.write_text(f"Time (s),{times}\r\nAccel (g),{values}\r\n",
                    encoding="utf-8")

    accel, = read_text(path)

    assert accel.name == "Accel"
    assert accel.y_unit == "g"
    np.testing.assert_allclose(accel.y, np.arange(40, dtype=float))


def test_find_data_start_skips_header_rows_but_not_trailing_junk():
    nan = float("nan")
    column = np.array([nan, nan, 1.0, 2.0, 3.0])
    assert find_data_start(column) == (2, 3)

    # a NaN past row 100 is trailing junk: the signal keeps its length
    long = np.concatenate([np.arange(150.0), [nan], np.arange(10.0)])
    start, length = find_data_start(long)
    assert (start, length) == (0, 150)


def test_infer_timing_reports_non_uniform_abscissas():
    even = np.arange(100) * DT
    t0, dt, uniform = infer_timing(even)
    assert (t0, uniform) == (0.0, True)
    assert dt == pytest.approx(DT)

    ragged = np.array([0.0, 1.0, 5.0, 20.0, 100.0])
    assert infer_timing(ragged)[2] is False


def test_an_evenly_spaced_first_column_is_taken_as_the_abscissa(tmp_path):
    """Surprising but deliberate, and what CSV File to fWform.vi does."""
    path = tmp_path / "looks_like_time.csv"
    path.write_text("A,B\r\n1,2\r\n3,4\r\n5,6\r\n", encoding="utf-8")

    b, = read_text(path)

    assert b.name == "B"
    assert b.dt == pytest.approx(2.0)      # taken from column A
    assert b.t0 == pytest.approx(1.0)
    np.testing.assert_allclose(b.y, [2.0, 4.0, 6.0])

    # ...and it can be overridden when the first column really is data
    a, b = read_text(path, time_column=False, dt=0.01)
    np.testing.assert_allclose(a.y, [1.0, 3.0, 5.0])
    assert a.dt == 0.01


def test_a_file_with_no_timing_says_what_to_do(tmp_path):
    path = tmp_path / "bare.csv"
    path.write_text("A,B\r\n5,2\r\n1,4\r\n9,6\r\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Pass dt="):
        read_text(path)

    a, b = read_text(path, dt=0.01)
    assert a.dt == 0.01
    np.testing.assert_allclose(a.y, [5.0, 1.0, 9.0])
    np.testing.assert_allclose(b.y, [2.0, 4.0, 6.0])


def test_an_empty_file_says_so(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="no data rows"):
        read_text(path)


# -- FRF text files --------------------------------------------------------
def test_frf_reads_complex_tokens(tmp_path):
    path = tmp_path / "frf.csv"
    path.write_text(
        "Frequency (Hz),H1 (m/s^2/N),H2 (m/s^2/N)\r\n"
        "10,1.5+2.5i,0-1i\r\n"
        "20,-3.5-0.5i,2+0i\r\n"
        "30,4i,1\r\n",
        encoding="utf-8")

    h1, h2 = read_text_frf(path)

    assert h1.name == "H1"
    assert h1.unit == "m/s^2/N"
    assert h1.x_unit == "Hz"
    np.testing.assert_allclose(h1.abscissa, [10, 20, 30])
    np.testing.assert_allclose(h1.values, [1.5 + 2.5j, -3.5 - 0.5j, 4j])
    np.testing.assert_allclose(h2.values, [-1j, 2 + 0j, 1 + 0j])


def test_frf_accepts_j_for_the_imaginary_unit(tmp_path):
    path = tmp_path / "frf_j.csv"
    path.write_text("Freq (Hz),H (1)\r\n10,1.5+2.5j\r\n", encoding="utf-8")

    h, = read_text_frf(path)

    assert h.values[0] == pytest.approx(1.5 + 2.5j)


def test_frf_reads_real_imaginary_column_pairs(tmp_path):
    path = tmp_path / "ri.csv"
    path.write_text(
        "Frequency (Hz),H1 real,H1 imag\r\n10,1.5,2.5\r\n20,-3.5,-0.5\r\n",
        encoding="utf-8")

    h1, = read_text_frf(path, pairs="real-imag")

    np.testing.assert_allclose(h1.values, [1.5 + 2.5j, -3.5 - 0.5j])


def test_frf_reads_magnitude_phase_column_pairs(tmp_path):
    path = tmp_path / "mp.csv"
    path.write_text(
        "Frequency (Hz),H1 mag,H1 phase\r\n10,2,0\r\n20,4,90\r\n30,8,180\r\n",
        encoding="utf-8")

    h1, = read_text_frf(path, pairs="mag-phase")

    assert h1.values[0] == pytest.approx(2 + 0j)
    assert h1.values[1] == pytest.approx(4j)
    assert h1.values[2] == pytest.approx(-8 + 0j, abs=1e-12)
    np.testing.assert_allclose(h1.magnitude, [2, 4, 8])
    assert h1.phase[1] == pytest.approx(np.pi / 2)


def test_frf_pairs_needs_an_even_number_of_data_columns(tmp_path):
    path = tmp_path / "odd.csv"
    path.write_text("Freq,A,B,C\r\n10,1,2,3\r\n", encoding="utf-8")

    with pytest.raises(ValueError, match="two columns per curve"):
        read_text_frf(path, pairs="real-imag")


def test_frf_reports_its_shape():
    from spwb.processing.io import TextFRF

    frf = TextFRF(name="H1", abscissa=np.arange(3.0),
                  values=np.ones(3, complex))
    assert frf.n_samples == 3
    assert "H1" in repr(frf)
