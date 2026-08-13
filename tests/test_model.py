"""Signal / SignalStore semantics."""
import numpy as np
import pytest

from spwb import Signal, SignalStore


def make(name="s", n=8):
    return Signal(name, np.arange(n, dtype=float), 0.5, y_unit="V")


def test_basic_properties():
    s = make(n=10)
    assert s.fs == pytest.approx(2.0)
    assert s.n_samples == 10
    assert s.duration == pytest.approx(5.0)
    np.testing.assert_allclose(s.t, np.arange(10) * 0.5)


def test_t0_offsets_the_time_vector():
    s = Signal("s", np.zeros(4), 0.25, t0=1.5)
    np.testing.assert_allclose(s.t, [1.5, 1.75, 2.0, 2.25])


@pytest.mark.parametrize("kwargs, message", [
    (dict(y=np.zeros((2, 2)), dt=1.0), "1-D"),
    (dict(y=np.zeros(4), dt=0.0), "positive"),
    (dict(y=np.zeros(4), dt=-1.0), "positive"),
])
def test_invalid_signals_rejected(kwargs, message):
    with pytest.raises(ValueError, match=message):
        Signal("bad", **kwargs)


def test_with_keeps_identity_for_store_update():
    """with_() is a revision: same sid, so SignalStore.update accepts it."""
    store = SignalStore()
    s = store.add(make("orig"))
    revised = s.with_(name="renamed")
    assert revised.sid == s.sid
    store.update(revised)                      # would KeyError on a new sid
    assert [x.name for x in store] == ["renamed"]
    assert len(store) == 1


def test_copy_creates_independent_identity():
    """copy() is a new signal: what window import / duplicate produces."""
    s = make("orig")
    c = s.copy()
    assert c.sid != s.sid
    assert c.name == s.name
    np.testing.assert_array_equal(c.y, s.y)
    c.y[0] = 999.0
    assert s.y[0] == 0.0                       # buffers are not shared


def test_copy_and_with_accept_field_changes():
    s = make("orig")
    assert s.copy(name="c").name == "c"
    assert s.with_(y_unit="Pa").y_unit == "Pa"


def test_attributes_are_shallow_merged_not_replaced():
    s = make()
    s.attributes["keep"] = 1
    out = s.with_(attributes={"add": 2})
    assert out.attributes == {"keep": 1, "add": 2}
    out.attributes["add"] = 3
    assert "add" not in s.attributes           # the original is untouched


def test_store_rejects_duplicate_and_missing_ids():
    store = SignalStore()
    s = store.add(make())
    with pytest.raises(KeyError, match="already in store"):
        store.add(s)
    with pytest.raises(KeyError, match="not in store"):
        store.update(make())
    assert s.sid in store and 999 not in store


def test_store_find_and_iteration_order():
    store = SignalStore()
    for name in ("a", "b", "a"):
        store.add(make(name))
    assert [s.name for s in store] == ["a", "b", "a"]
    assert len(store.find("a")) == 2
    assert store.find("nope") == []


def test_store_iteration_is_safe_while_removing():
    store = SignalStore()
    for name in ("a", "b", "c"):
        store.add(make(name))
    for sig in store:                          # snapshot, not a live view
        if sig.name != "b":
            store.remove(sig.sid)
    assert [s.name for s in store] == ["b"]
