"""RPC-III reading: header keywords, group de-interleaving, scaling.

There is no RPC-III writer in ``spwb`` - the port is read-only - so these
tests build the bytes themselves. That is the point: the fixture spells out
the layout the reader claims (128-byte records, 512-byte header blocks,
little-endian int16 demultiplexed by group), so a reader that drifts from
the format fails here rather than silently reading a real file wrong.
"""
import numpy as np
import pytest

from spwb.processing.io import (
    RPCHeader,
    read_rpc,
    read_rpc_header,
    rpc_contents,
)
from spwb.processing.io.rpc import BLOCK_SIZE, RECORD_SIZE

DT = 1.0 / 1024.0
FRAME = 64          # PTS_PER_FRAME
GROUP = 128         # PTS_PER_GROUP -> 2 frames per group
FRAMES = 6          # -> 3 groups exactly


def make_record(keyword: str, value: str) -> bytes:
    """One 128-byte header record: 32-byte keyword + 96-byte value."""
    return (keyword.encode("latin-1").ljust(32, b"\x00")
            + str(value).encode("latin-1").ljust(RECORD_SIZE - 32, b"\x00"))


def build_rpc(path, channels, *, dt=DT, frames=FRAMES, half_frames=0,
              group=GROUP, frame=FRAME, extra=()):
    """Write a minimal but valid RPC-III file.

    ``channels`` is a list of ``(name, unit, scale, raw_int16_array)``.
    Raw samples are stored as written, so a test can assert on
    ``raw * scale`` exactly.
    """
    n_channels = len(channels)
    n_groups = -(-((frames + half_frames) * frame) // group)

    records = [
        make_record("FORMAT", "BINARY"),
        make_record("NUM_HEADER_BLOCKS", "0"),   # patched below
        make_record("NUM_PARAMS", "0"),          # patched below
        make_record("CHANNELS", n_channels),
        make_record("DELTA_T", f"{dt:.10E}"),
        make_record("PTS_PER_FRAME", frame),
        make_record("PTS_PER_GROUP", group),
        make_record("FRAMES", frames),
        make_record("HALF_FRAMES", half_frames),
        make_record("DATA_TYPE", "SHORT_INTEGER"),
        make_record("INT_FULL_SCALE", 32752),
    ]
    records += [make_record(k, v) for k, v in extra]
    for i, (name, unit, scale, _raw) in enumerate(channels, start=1):
        records += [
            make_record(f"DESC.CHAN_{i}", name),
            make_record(f"UNITS.CHAN_{i}", unit),
            make_record(f"SCALE.CHAN_{i}", f"{scale:.10E}"),
        ]

    n_blocks = -(-len(records) // (BLOCK_SIZE // RECORD_SIZE))
    records[1] = make_record("NUM_HEADER_BLOCKS", n_blocks)
    records[2] = make_record("NUM_PARAMS", len(records))

    header = b"".join(records).ljust(n_blocks * BLOCK_SIZE, b"\x00")

    # data: group by group, and inside a group channel by channel
    body = bytearray()
    for g in range(n_groups):
        for _name, _unit, _scale, raw in channels:
            block = np.zeros(group, dtype="<i2")
            chunk = raw[g * group:(g + 1) * group]
            block[:len(chunk)] = chunk
            body += block.tobytes()

    path.write_bytes(header + bytes(body))
    return path


@pytest.fixture
def rpc_path(tmp_path):
    n = FRAMES * FRAME  # 384 samples = 3 whole groups
    accel = (np.arange(n) % 1000).astype("<i2")
    mic = (-(np.arange(n) % 500)).astype("<i2")
    return build_rpc(tmp_path / "run.rsp", [
        ("Accel  X", "m/s^2", 0.001, accel),
        ("Mic", "Pa", 0.25, mic),
    ])


def test_header_reports_the_derived_geometry(rpc_path):
    header = read_rpc_header(rpc_path)

    assert header.n_channels == 2
    assert header.dt == pytest.approx(DT)
    assert header.group_size == GROUP
    assert header.frame_size == FRAME
    assert header.n_frames == FRAMES
    assert header.n_groups == 3
    assert header.n_samples == 3 * GROUP
    assert header.data_offset == header.n_blocks * BLOCK_SIZE


def test_keyword_lookup_is_by_prefix():
    """SPWB asks for ``DELTA`` and must find ``DELTA_T`` (Extract value...)."""
    header = RPCHeader([("DELTA_T", "0.001"),
                        ("NUM_HEADER_BLOCKS", "2"),
                        ("HALF_FRAMES", "1")], n_blocks=2)

    assert header.get("DELTA") == "0.001"
    assert header.get_float("DELTA") == pytest.approx(0.001)
    assert header.get_int("NUM_HEADER") == 2
    # a prefix must not match a keyword that merely contains it
    assert "FRAMES" not in header
    assert header.get("FRAMES", "missing") == "missing"


def test_missing_keyword_names_the_file_contents():
    header = RPCHeader([("CHANNELS", "2")], n_blocks=1)
    with pytest.raises(KeyError, match="NOT_THERE"):
        header.get("NOT_THERE")


def test_contents_lists_channels_without_reading_data(rpc_path):
    info = rpc_contents(rpc_path)

    assert [c.index for c in info] == [1, 2]
    assert [c.name for c in info] == ["Accel X", "Mic"]  # double space cleaned
    assert [c.y_unit for c in info] == ["m/s^2", "Pa"]
    assert info[0].scale == pytest.approx(0.001)
    assert info[0].n_samples == 3 * GROUP
    assert info[0].duration == pytest.approx(3 * GROUP * DT)


def test_reads_scaled_data_in_the_right_order(rpc_path):
    """The de-interleaving is the part that goes wrong silently."""
    accel, mic = read_rpc(rpc_path)

    n = FRAMES * FRAME
    assert accel.n_samples == n
    np.testing.assert_allclose(accel.y, (np.arange(n) % 1000) * 0.001)
    np.testing.assert_allclose(mic.y, -(np.arange(n) % 500) * 0.25)


def test_signal_metadata_follows_the_spwb_conventions(rpc_path):
    accel, _mic = read_rpc(rpc_path)

    assert accel.name == "Accel X"
    assert accel.y_unit == "m/s^2"
    assert accel.x_unit == "s"
    assert accel.dt == pytest.approx(DT)
    assert accel.t0 == 0.0
    assert accel.attributes["Channel Name"] == "Accel X"
    assert accel.attributes["Channel Unit"] == "m/s^2"
    assert accel.attributes["RPC Channel"] == 1
    assert accel.attributes["Data Source"].endswith("run.rsp")
    assert accel.attributes["RPC"]["DATA_TYPE"] == "SHORT_INTEGER"


def test_select_accepts_names_and_indices(rpc_path):
    by_name = read_rpc(rpc_path, select=["Mic"])
    by_index = read_rpc(rpc_path, select=[2])

    assert [s.name for s in by_name] == ["Mic"]
    np.testing.assert_array_equal(by_name[0].y, by_index[0].y)
    assert read_rpc(rpc_path, select=[]) == []


def test_select_rejects_an_unknown_channel(rpc_path):
    with pytest.raises(KeyError, match="Torque"):
        read_rpc(rpc_path, select=["Torque"])


def test_decorate_names_appends_the_source_file(rpc_path):
    accel, _mic = read_rpc(rpc_path, decorate_names=True)
    assert accel.name == "Accel X (run.rsp)"


def test_partial_last_group_is_padded_like_labview(tmp_path):
    """5 frames of 64 in groups of 128 -> 2.5 groups, stored as 3."""
    n = 5 * FRAME
    raw = np.ones(n, dtype="<i2")
    path = build_rpc(tmp_path / "half.rsp",
                     [("Ch", "N", 1.0, raw)], frames=5)

    header = read_rpc_header(path)
    assert header.n_groups == 3
    assert header.n_samples == 3 * GROUP

    padded, = read_rpc(path)
    assert padded.n_samples == 3 * GROUP        # LabVIEW keeps the padding
    assert padded.y[-1] == 0.0

    trimmed, = read_rpc(path, trim_padding=True)
    assert trimmed.n_samples == n
    np.testing.assert_array_equal(trimmed.y, np.ones(n))


def test_a_truncated_file_says_so(tmp_path, rpc_path):
    short = tmp_path / "short.rsp"
    short.write_bytes(rpc_path.read_bytes()[:-256])

    with pytest.raises(ValueError, match="truncated"):
        read_rpc(short)


def test_a_file_that_is_not_rpc_says_so(tmp_path):
    junk = tmp_path / "notes.rsp"
    junk.write_bytes(b"just some text" + b"\x00" * BLOCK_SIZE)

    with pytest.raises(ValueError, match="NUM_HEADER_BLOCKS"):
        read_rpc_header(junk)


def test_a_file_shorter_than_one_block_says_so(tmp_path):
    tiny = tmp_path / "tiny.rsp"
    tiny.write_bytes(b"\x00" * 16)

    with pytest.raises(ValueError, match="16 bytes"):
        read_rpc_header(tiny)


def test_there_is_no_rpc_writer():
    """The port is read-only for RPC-III; keep it that way."""
    from spwb.processing.io import rpc

    assert not [n for n in dir(rpc) if n.startswith("write")]
