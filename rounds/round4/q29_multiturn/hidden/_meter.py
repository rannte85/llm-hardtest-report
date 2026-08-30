"""Grader-owned storage instrumentation for the Q29 cost budget.

GRADER ONLY.

Why this exists
----------------
The T5 budget used to be read off the *repo's own* counters
(``Storage.read_ops`` / ``Storage.write_ops``), with the reading taken after the
call under test.  That was fixed once already (see git history / SOLUTION.md
for S1/S2/S3), by measuring on a grader-owned store instead.  That first fix
still charged by *method name* though: a fixed list of known Storage method
names (``get``/``keys``/``put``/...) was individually wrapped, unknown public
methods were charged by inspecting the *shape* of their return value (is it a
list of dicts? a dict of dicts?), and the private containers (``_records`` /
``_insertion``) were exposed through per-attribute properties installed
*after* the store already existed in one of the injection fallbacks.  Three
more bypass families fell out of that shape, all measured at public 21/21,
hidden 41/41, turn5 8/8 before this rewrite:

  return-type dodges   a bulk accessor that returns (id, record) tuples, a
                        bare generator, or {customer: [record, ...]} instead
                        of a list/dict of records defeats a check that only
                        recognises specific return shapes as "contains
                        records" (c1_pairs_tuple, c2_iterator,
                        c8_dict_of_lists) -- and combining that with a bulk
                        method that hides its own internal reads behind a
                        "we already charged the outer call" suppression makes
                        an out-parameter accessor (returns ``None``, so there
                        is nothing left to inspect) free even though it
                        walked and fetched every record in the store
                        (c3_bulk_get, c5_bulk_keys).
  delegation escapes    the private-container proxy only defined the dict
                        methods it happened to enumerate (``get``, ``values``,
                        ``items``, ...); anything else (``setdefault``,
                        ``popitem``, ...) fell through ``__getattr__`` straight
                        to the raw dict, completely uncounted
                        (c9_setdefault_escape, c10_getattr_escape).
  constructor capture   a store built through the "wrap the instance after
                        construction" fallback can have its private
                        containers read and cached by ``OrderAPI.__init__``
                        *before* that fallback ever runs, so the cached
                        reference stays raw forever no matter what happens to
                        ``store._records`` afterwards (c7_capture_containers).

So the design changed shape, not just its blocklist:

  * counting happens at the RAW CONTAINER, not at a list of known method
    names.  Every ``dict``/``list`` a ``Storage`` instance owns (not just
    ``_records``/``_insertion`` by name -- any of them, including ones a
    submission's own extended ``storage.py`` adds) is wrapped in a counting
    proxy the moment it is assigned to an attribute, via ``__setattr__`` on
    the counting subclass.  A method built on top of the container --
    ``get``, ``keys``, a hand-rolled bulk accessor, a submission-invented
    index method, whatever -- costs exactly what it touches, because the
    charge fires where the data actually lives, not at the method boundary.
    There is no "unknown method" case to special-case by return shape any
    more, so tuple pairs, generators, dict-of-lists and out-parameters are
    not routes around anything -- they are just different ways of describing
    the same underlying container touches, which were already charged.
  * charging is by RECORDS ACTUALLY MATERIALIZED, not by the type of the
    value some method happened to return.  ``values()``/``items()`` hand back
    a lazily-charging iterator: consuming it costs one op per record actually
    produced, whether that happens eagerly (``list(...)``), lazily (a
    generator wrapping it), never (an unconsumed iterator, correctly free),
    or from inside a completely unrelated helper method.  ID-only accesses
    (``keys()``, iterating the id list, ``raw_ids()``) stay a flat one op
    regardless of size, matching the documented cost model.
  * every dict method the fallback ``__getattr__`` cannot price precisely
    (``popitem``, ``setdefault`` and anything else neither Python's dict API
    nor this module happened to enumerate) is charged the FULL SIZE of the
    container by default rather than left free -- the model inverts from
    "only named methods cost anything" to "everything costs something unless
    explicitly marked free", so a method nobody thought to name in an
    allowlist can never be cheaper than the accessors that are priced
    precisely.
  * the counting class is installed on ``orderservice.storage.Storage``
    BEFORE ``orderservice.api`` (or the package ``__init__``) is ever
    imported for a measured run, not patched in afterwards.  A ``Storage()``
    call resolved at CALL time picks up the counting class automatically
    (import-time name binding), and so does a ``Storage`` captured as a
    mutable DEFAULT ARGUMENT (``def __init__(self, _S=Storage)``), because
    that default is evaluated when the class body executes -- which now
    happens after the swap.  That closes off the window where an
    ``OrderAPI.__init__`` could read and cache a store's private containers
    while they were still raw: by the time any submission code can run at
    all, the very first ``Storage`` instance it can construct already has its
    containers wrapped.  The old "wrap an already-built instance in place"
    path still exists as a last resort for a genuinely foreign store that
    never goes through ``orderservice.storage.Storage`` at all, but it is
    no longer how ordinary submissions get measured.

The store is injected through ``OrderAPI(storage=...)`` when the submission
still accepts it; two fallbacks cover submissions that do not, and the path
that was actually used is recorded in :data:`MEASUREMENT_PATHS` and printed by
the runner so a grader can see how the number was obtained.
"""

import importlib
import os
import sys
import types

# path name -> number of instrumented APIs built that way
MEASUREMENT_PATHS = {}

_RESERVED_PREFIX = "_g_"


class Meter:
    """Read/write accounting the code under test cannot reach."""

    def __init__(self):
        self.reads = 0
        self.writes = 0
        self.resets = 0

    def read(self, n=1):
        if n:
            self.reads += n

    def write(self, n=1):
        if n:
            self.writes += n


# --------------------------------------------------------------------------- #
# _ChargingIter -- makes "consuming N records" cost N regardless of what
# container shape (list, tuple, generator, dict-of-lists, ...) the caller
# wraps the results in afterwards.  The charge fires from *this* iterator's
# __next__, at the moment a record is actually produced -- not when whatever
# calls .values()/.items() decides to return something.
# --------------------------------------------------------------------------- #
class _ChargingIter:
    __slots__ = ("_it", "_m")

    def __init__(self, it, meter):
        self._it = it
        self._m = meter

    def __iter__(self):
        return self

    def __next__(self):
        value = next(self._it)  # StopIteration propagates uncharged
        self._m.read(1)
        return value


# --------------------------------------------------------------------------- #
# _RecordsProxy -- wraps a dict Storage owns.  Every access that can hand a
# record's contents to the caller is charged; the few operations that never
# expose a record (existence checks, length) are free.  Anything reached only
# through __getattr__ (a dict method this module did not name) is charged
# conservatively for the full size of the container, so it is never a cheaper
# way to read data than the accessors below -- "charge unless explicitly
# exempted", not "charge only what was explicitly named".
# --------------------------------------------------------------------------- #
class _RecordsProxy:
    _FREE_ATTRS = frozenset(
        (
            "__class__",
            "__len__",
            "__bool__",
            "__repr__",
            "__str__",
            "__sizeof__",
            "__contains__",
            "__hash__",
        )
    )

    def __init__(self, target, meter):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_m", meter)

    # -- point accesses: one record touched -> one op ----------------------- #
    def __getitem__(self, key):
        self._m.read(1)
        return self._t[key]

    def get(self, key, default=None):
        self._m.read(1)
        return self._t.get(key, default)

    def pop(self, *a):
        had = (len(a) == 0) or (a[0] in self._t)
        if had:
            self._m.read(1)
        return self._t.pop(*a)

    def setdefault(self, key, default=None):
        if key in self._t:
            self._m.read(1)
        else:
            self._m.write(1)
        return self._t.setdefault(key, default)

    def popitem(self):
        self._m.read(1)
        self._m.write(1)
        return self._t.popitem()

    # -- bulk access: charged per record as it is actually produced --------- #
    def values(self):
        return _ChargingIter(iter(self._t.values()), self._m)

    def items(self):
        return _ChargingIter(iter(self._t.items()), self._m)

    def copy(self):
        self._m.read(len(self._t))
        return dict(self._t)

    def update(self, *a, **kw):
        # records go IN here, none are handed out -- a write, not a read.
        self._m.write(1)
        self._t.update(*a, **kw)

    def clear(self):
        if self._t:
            self._m.write(len(self._t))
        self._t.clear()

    # -- ids only: no record crosses the boundary -> flat, size-independent - #
    def keys(self):
        self._m.read(1)
        return list(self._t.keys())

    def __iter__(self):
        self._m.read(1)
        return iter(self._t)

    # -- free: no record data crosses the boundary --------------------------- #
    def __setitem__(self, key, value):
        self._m.write(1)
        self._t[key] = value

    def __delitem__(self, key):
        self._m.write(1)
        del self._t[key]

    def __contains__(self, key):
        return key in self._t

    def __len__(self):
        return len(self._t)

    def __bool__(self):
        return bool(self._t)

    def __repr__(self):
        return repr(self._t)

    # -- default-deny: anything not named above is charged the full size of
    # the store, so no dict method left un-enumerated can ever be a cheaper
    # way to read data than the accessors above. ---------------------------- #
    def __getattr__(self, name):
        target = object.__getattribute__(self, "_t")
        raw = getattr(target, name)
        if name in _RecordsProxy._FREE_ATTRS or not callable(raw):
            return raw
        meter = object.__getattribute__(self, "_m")

        def _unknown(*a, **kw):
            meter.read(len(target) or 1)
            return raw(*a, **kw)

        _unknown.__name__ = name
        return _unknown


# --------------------------------------------------------------------------- #
# _IdsProxy -- wraps a list Storage owns for order ids.  Ids are cheap by
# design (NOTES.md: keys() costs one read op no matter how many ids come
# back), so a whole traversal is a flat op and structural mutations
# (append/insert/remove/...) that never expose a record are free.
# --------------------------------------------------------------------------- #
class _IdsProxy:
    _FREE_ATTRS = frozenset(("__class__", "__len__", "__bool__", "__repr__", "__str__", "__contains__"))

    def __init__(self, target, meter):
        object.__setattr__(self, "_t", target)
        object.__setattr__(self, "_m", meter)

    def __iter__(self):
        self._m.read(1)
        return iter(self._t)

    def __reversed__(self):
        self._m.read(1)
        return reversed(self._t)

    def __getitem__(self, idx):
        self._m.read(1)
        return self._t[idx]

    def copy(self):
        self._m.read(1)
        return list(self._t)

    # -- free: ids only, never a record --------------------------------------- #
    def __len__(self):
        return len(self._t)

    def __bool__(self):
        return bool(self._t)

    def __contains__(self, value):
        return value in self._t

    def append(self, value):
        self._t.append(value)

    def insert(self, idx, value):
        self._t.insert(idx, value)

    def remove(self, value):
        self._t.remove(value)

    def extend(self, values):
        self._t.extend(values)

    def pop(self, *a):
        return self._t.pop(*a)

    def __repr__(self):
        return repr(self._t)

    def __getattr__(self, name):
        target = object.__getattribute__(self, "_t")
        raw = getattr(target, name)
        if name in _IdsProxy._FREE_ATTRS or not callable(raw):
            return raw
        meter = object.__getattribute__(self, "_m")

        def _unknown(*a, **kw):
            meter.read(1)  # ids only, flat -- see class docstring
            return raw(*a, **kw)

        _unknown.__name__ = name
        return _unknown


_PROXY_FOR = {dict: _RecordsProxy, list: _IdsProxy}
_PROXY_TYPES = (_RecordsProxy, _IdsProxy)

_CLASS_CACHE = {}


def counting_storage_class(base):
    """Build (once per base class) a counting subclass of the shipped Storage.

    No method name is special-cased here at all: every ``dict``/``list``
    attribute the instance owns is wrapped the moment it is assigned, via
    ``__setattr__``.  A method built on top of a wrapped container -- named
    ``get``, ``keys``, ``put``, or something a submission's own extended
    ``storage.py`` invented -- costs whatever it actually touches, because
    the container is the only place the charge can come from.
    """
    cached = _CLASS_CACHE.get(base)
    if cached is not None:
        return cached

    def __init__(self, *a, **kw):
        self.__dict__["_g_meter"] = Meter()
        base.__init__(self, *a, **kw)

    def __setattr__(self, name, value):
        if name.startswith(_RESERVED_PREFIX):
            object.__setattr__(self, name, value)
            return
        meter = self.__dict__.get("_g_meter")
        if meter is not None and not isinstance(value, _PROXY_TYPES):
            proxy_cls = _PROXY_FOR.get(type(value))
            if proxy_cls is None:
                # allow dict/list SUBCLASSES too (e.g. OrderedDict)
                if isinstance(value, dict):
                    proxy_cls = _RecordsProxy
                elif isinstance(value, list):
                    proxy_cls = _IdsProxy
            if proxy_cls is not None:
                value = proxy_cls(value, meter)
        object.__setattr__(self, name, value)

    def reset_counters(self, *a, **kw):
        # No longer load-bearing for the budget (the grader meter never reads
        # this counter), but still worth flagging: a callee that resets mid-
        # measurement is reported by Measured.call() below.
        self._g_meter.resets += 1
        original = getattr(base, "reset_counters", None)
        if original is not None:
            return original(self, *a, **kw)
        return None

    reset_counters.__name__ = "reset_counters"

    namespace = {
        "__doc__": "Grader-owned counting subclass of the submission's Storage.",
        "_g_counting": True,
        "__init__": __init__,
        "__setattr__": __setattr__,
        "reset_counters": reset_counters,
    }
    cls = type("CountingStorage", (base,), namespace)
    _CLASS_CACHE[base] = cls
    return cls


# --------------------------------------------------------------------------- #
# fallback: instrument an already-built, still-plain store instance in place.
# Last resort only -- see _fresh_import_with_patch below for why this is no
# longer how ordinary submissions get measured.  Anything an OrderAPI cached
# from this instance BEFORE this function runs stays uninstrumented; that is
# exactly the residual risk this path exists to minimise exposure to, not
# eliminate (see README_v4.md threat-model section).
# --------------------------------------------------------------------------- #
def _wrap_instance(store):
    meter = Meter()
    try:
        store._g_meter = meter
    except Exception:  # noqa: BLE001 - exotic Storage, give up on this path
        return None

    for attr, value in list(vars(store).items()):
        if attr.startswith(_RESERVED_PREFIX) or isinstance(value, _PROXY_TYPES):
            continue
        proxy_cls = None
        if isinstance(value, dict):
            proxy_cls = _RecordsProxy
        elif isinstance(value, list):
            proxy_cls = _IdsProxy
        if proxy_cls is not None:
            try:
                setattr(store, attr, proxy_cls(value, meter))
            except Exception:  # noqa: BLE001
                pass

    original_reset = getattr(store, "reset_counters", None)
    if callable(original_reset):

        def reset_counters(*a, **kw):
            meter.resets += 1
            return original_reset(*a, **kw)

        try:
            store.reset_counters = reset_counters
        except Exception:  # noqa: BLE001
            pass

    return meter


# --------------------------------------------------------------------------- #
# Import the submission's package fresh, with Storage swapped for the
# counting subclass BEFORE any of the package's own code runs -- see the
# "constructor capture" paragraph in the module docstring for why this has to
# happen before import rather than after construction.
# --------------------------------------------------------------------------- #
def _fresh_import_with_patch(repo_path):
    pkg_name = "orderservice"
    for name in list(sys.modules):
        if name == pkg_name or name.startswith(pkg_name + "."):
            del sys.modules[name]

    sys.path.insert(0, repo_path)
    try:
        # A placeholder package module, registered under the real name with a
        # real __path__, lets us import the "orderservice.storage" submodule
        # directly without running "orderservice/__init__.py" first -- that
        # init imports .api (which imports .storage) before we would ever get
        # a chance to patch anything.
        placeholder = types.ModuleType(pkg_name)
        placeholder.__path__ = [os.path.join(repo_path, pkg_name)]
        placeholder.__package__ = pkg_name
        sys.modules[pkg_name] = placeholder

        storage_mod = importlib.import_module(pkg_name + ".storage")
        base = storage_mod.Storage
        cls = counting_storage_class(base)
        storage_mod.Storage = cls

        # Now let the real package __init__ run (importing .api and .errors
        # for the first time); .storage is already cached and already
        # patched, so every `from .storage import Storage` anywhere in the
        # package -- including one baked into a class body's default
        # argument -- resolves to the counting class from the very start.
        del sys.modules[pkg_name]
        pkg = importlib.import_module(pkg_name)
        api_mod = sys.modules.get(pkg_name + ".api")
    finally:
        sys.path.remove(repo_path)

    return pkg, storage_mod, api_mod, cls, base


def _store_of(api):
    for attr in ("storage", "_store"):
        store = getattr(api, attr, None)
        if store is not None:
            return store
    return None


def _record(measured):
    MEASUREMENT_PATHS[measured.path] = MEASUREMENT_PATHS.get(measured.path, 0) + 1
    return measured


def meter_of(store):
    meter = getattr(store, "_g_meter", None)
    if not isinstance(meter, Meter):
        return None
    return meter


class Measured:
    """An OrderAPI whose storage the grader instrumented, plus the measurement.

    ``path`` records how the instrumented store got in:

      ``constructor``  -- ``OrderAPI(storage=...)`` (the submission still takes it)
      ``class-patch``  -- Storage was already the counting class before the
                          submission's own code (including a default-argument
                          binding) ever ran, so a no-argument build already
                          used it
      ``instance-wrap``-- last resort: an already-built, still-plain store the
                          pre-import patch could not reach was wrapped in place
    """

    def __init__(self, api, store, path):
        self.api = api
        self.store = store
        self.path = path
        self.meter = meter_of(store)
        assert self.meter is not None, "instrumented store lost its meter"

    # -- raw counters ------------------------------------------------------- #
    @property
    def reads(self):
        return self.meter.reads

    @property
    def writes(self):
        return self.meter.writes

    @staticmethod
    def _repo_reads(store):
        value = getattr(store, "read_ops", None)
        return value if isinstance(value, int) else None

    def call(self, fn, *a, **kw):
        """Run ``fn`` and return ``(result, read_ops, write_ops)``.

        The op counts are before/after deltas on the grader's own meter, so a
        ``reset_counters()`` inside the callee cannot move them -- the meter
        does not read the repo's counters at all any more, so tampering with
        them (deleting the increments, resetting them mid-call, gutting
        ``storage.py``) has no effect on the number reported here.  Two extra
        guards report the attempt rather than silently ignoring it: the
        repo's own read counter must not go backwards across the call, and
        the callee must not reset the counters at all.
        """
        meter = self.meter
        r0, w0, resets0 = meter.reads, meter.writes, meter.resets
        repo0 = self._repo_reads(self.store)
        result = fn(*a, **kw)
        repo1 = self._repo_reads(self.store)
        dr, dw = meter.reads - r0, meter.writes - w0
        assert dr >= 0 and dw >= 0, "grader meter went backwards (%d, %d)" % (dr, dw)
        if meter.resets > resets0:
            raise AssertionError(
                "the call under test reset the storage counters %d time(s) mid-call -- "
                "the cost signal may not be zeroed by the code being measured"
                % (meter.resets - resets0)
            )
        if repo0 is not None and repo1 is not None and repo1 < repo0:
            raise AssertionError(
                "storage.read_ops decreased across the call (%d -> %d): read ops must "
                "increase monotonically while a call is in flight" % (repo0, repo1)
            )
        return result, dr, dw

    def list_orders(self, *a, **kw):
        """``(rows, read_ops)`` for one ``list_orders`` call."""
        rows, reads, _writes = self.call(self.api.list_orders, *a, **kw)
        return rows, reads

    def assert_live(self):
        """The instrument must have seen the fixture being written.

        A meter that recorded nothing while the fixture was built is not
        evidence of a cheap ``list_orders`` -- it means the traffic is bypassing
        the instrumented store (records kept outside Storage, or captured
        before instrumentation existed).  Fail loudly instead of handing out a
        free budget pass.
        """
        assert self.writes > 0 or self.reads > 0, (
            "the grader's storage instrumentation recorded no traffic while the "
            "fixture was built (path=%s): orders are not going through the "
            "instrumented Storage, so the read-op budget cannot be measured" % self.path
        )


def measured_api(ctx, **kwargs):
    """Build an ``OrderAPI`` on top of a store the grader can measure.

    ``ctx`` is only used for its ``repo_path``; the classes/modules used here
    come from a fresh, separately-patched import (see
    ``_fresh_import_with_patch``), never from ``ctx.OrderAPI``/``ctx.Storage``
    -- reusing those would mean the package (and any class-body default
    argument in it) was already imported, unpatched, before this function
    ever got a chance to swap ``Storage``.
    """
    pkg, _storage_mod, _api_mod, cls, base = _fresh_import_with_patch(ctx.repo_path)
    OrderAPI = pkg.OrderAPI

    # 1) the shipped constructor still accepts an injected store.  The store
    #    is `cls()`, so it is wrapped from the very first line of its own
    #    __init__ -- nothing OrderAPI.__init__ does with it can observe a raw
    #    container.
    try:
        store = cls()
        api = OrderAPI(storage=store, **kwargs)
    except Exception:  # noqa: BLE001
        api = None
    else:
        if _store_of(api) is store:
            return _record(Measured(api, store, "constructor"))

    # 2) `orderservice.storage.Storage` was already `cls` before `api.py` (or
    #    the package __init__) was ever imported, so a no-argument build --
    #    including one behind a mutable default argument baked in at class-
    #    definition time -- already used the counting class from birth.
    api = OrderAPI(**kwargs)
    store = _store_of(api)
    if isinstance(store, cls):
        return _record(Measured(api, store, "class-patch"))

    # 3) last resort: a genuinely foreign store the pre-import patch could
    #    not reach (never referenced as `orderservice.storage.Storage`
    #    anywhere the package could see).  Wrapping it now is best-effort --
    #    see the README_v4.md threat-model note on this path's limits.
    assert isinstance(store, base), (
        "OrderAPI is not backed by the shipped Storage (%r): the cost budget "
        "cannot be measured on this submission" % (type(store).__name__,)
    )
    meter = _wrap_instance(store)
    if meter is not None:
        return _record(Measured(api, store, "instance-wrap"))

    raise AssertionError(
        "could not attach grader-owned storage instrumentation to OrderAPI: the "
        "cost budget cannot be measured on this submission (tried constructor "
        "injection, pre-import Storage patching and instance wrapping)"
    )
