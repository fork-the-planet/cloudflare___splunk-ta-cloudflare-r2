# Copyright (c) 2026 Cloudflare, Inc.
# Licensed under the Apache 2.0 license.

"""
Unit tests for the checkpoint-related helpers in
package/bin/cloudflare_r2_helper.py: _assert_typed and _load_processed.

These exercise the two guards/queries that sit between the KV Store and the
actual poll loop, using tests/_fake_kvstore.py (an in-memory stand-in that
faithfully replicates the real KV Store client's documented API quirks -
particularly the query()-takes-a-dict vs delete()-needs-a-string asymmetry -
so a passing test here means something, not just "the mock agreed with
itself").

No real Splunk, no network. See tests/_splunk_stubs.py for why a stub step
is needed just to *import* cloudflare_r2_helper.py at all.

Run:  python3 tests/test_helper_checkpoint.py        (from the repo root)
  or  python3 -m unittest discover -s tests -v
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "package", "bin"))

from _splunk_stubs import install_stubs  # noqa: E402

install_stubs()

from cloudflare_r2_helper import (  # noqa: E402
    _CHECKPOINT_COLLECTION,
    _PAGE,
    _assert_typed,
    _load_processed,
)
from _fake_kvstore import FakeKVCollection  # noqa: E402


class TestAssertTyped(unittest.TestCase):

    def test_typed_collection_passes(self):
        collection = FakeKVCollection(field_ts_type="number")
        _assert_typed(collection)  # must not raise

    def test_untyped_collection_raises(self):
        collection = FakeKVCollection(field_ts_type="string")
        with self.assertRaises(RuntimeError) as ctx:
            _assert_typed(collection)
        self.assertIn("not typed", str(ctx.exception))

    def test_missing_field_type_raises(self):
        # field.ts absent entirely (e.g. collections.conf never applied) -
        # collection.content.get("field.ts") returns None, must still raise,
        # not silently treat None as "fine".
        collection = FakeKVCollection(field_ts_type=None)
        with self.assertRaises(RuntimeError):
            _assert_typed(collection)

    def test_error_message_names_the_collection(self):
        collection = FakeKVCollection(field_ts_type="string")
        with self.assertRaises(RuntimeError) as ctx:
            _assert_typed(collection)
        self.assertIn(_CHECKPOINT_COLLECTION, str(ctx.exception))

    def test_calls_refresh_before_checking_content(self):
        # The guard is only meaningful if it re-fetches metadata rather than
        # trusting whatever .content happened to hold from a stale earlier
        # fetch - assert refresh() is actually invoked.
        collection = FakeKVCollection(field_ts_type="number")
        self.assertEqual(collection.refresh_calls, 0)
        _assert_typed(collection)
        self.assertEqual(collection.refresh_calls, 1)


class TestLoadProcessed(unittest.TestCase):

    def test_empty_collection_returns_empty_set(self):
        collection = FakeKVCollection()
        result = _load_processed(collection.data, "my_input", "my_input|")
        self.assertEqual(result, set())

    def test_returns_matching_keys_within_window(self):
        collection = FakeKVCollection()
        collection.data.seed(
            {"_key": "my_input|20260701", "input": "my_input", "ts": 1},
            {"_key": "my_input|20260702", "input": "my_input", "ts": 2},
        )
        result = _load_processed(collection.data, "my_input", "my_input|20260701")
        self.assertEqual(result, {"my_input|20260701", "my_input|20260702"})

    def test_gte_boundary_is_inclusive(self):
        # _key exactly equal to lo must be included ($gte, not $gt).
        collection = FakeKVCollection()
        collection.data.seed({"_key": "my_input|20260701", "input": "my_input", "ts": 1})
        result = _load_processed(collection.data, "my_input", "my_input|20260701")
        self.assertEqual(result, {"my_input|20260701"})

    def test_excludes_rows_below_window_floor(self):
        collection = FakeKVCollection()
        collection.data.seed(
            {"_key": "my_input|20260630", "input": "my_input", "ts": 1},  # below lo
            {"_key": "my_input|20260702", "input": "my_input", "ts": 2},  # at/above lo
        )
        result = _load_processed(collection.data, "my_input", "my_input|20260701")
        self.assertEqual(result, {"my_input|20260702"})

    def test_excludes_rows_for_a_different_input(self):
        # Per-input isolation: a row for another input, even with a _key
        # that would otherwise sort inside this input's window, must never
        # leak into this input's processed set.
        collection = FakeKVCollection()
        collection.data.seed(
            {"_key": "my_input|20260702", "input": "my_input", "ts": 2},
            {"_key": "other_input|20260702", "input": "other_input", "ts": 2},
        )
        result = _load_processed(collection.data, "my_input", "my_input|20260701")
        self.assertEqual(result, {"my_input|20260702"})

    def test_pagination_exact_page_boundary(self):
        # Exactly _PAGE matching rows: the first query returns _PAGE rows
        # (== _PAGE, not < _PAGE), so the loop must advance and issue a
        # second query (which finds 0 remaining) rather than stopping early
        # and silently dropping nothing here - but this is the precise
        # boundary where an off-by-one would first become invisible with a
        # smaller seed.
        collection = FakeKVCollection()
        collection.data.seed(*(
            {"_key": "my_input|k{:06d}".format(i), "input": "my_input", "ts": i}
            for i in range(_PAGE)
        ))
        result = _load_processed(collection.data, "my_input", "my_input|")
        self.assertEqual(len(result), _PAGE)

    def test_pagination_one_over_page_boundary(self):
        # The critical "not silently truncated on a busy bucket" invariant:
        # _PAGE + 1 matching rows must all come back, requiring a second
        # page to actually be fetched and merged.
        collection = FakeKVCollection()
        collection.data.seed(*(
            {"_key": "my_input|k{:06d}".format(i), "input": "my_input", "ts": i}
            for i in range(_PAGE + 1)
        ))
        result = _load_processed(collection.data, "my_input", "my_input|")
        self.assertEqual(len(result), _PAGE + 1)

    def test_pagination_multiple_full_pages_plus_partial(self):
        total = 2 * _PAGE + 137
        collection = FakeKVCollection()
        collection.data.seed(*(
            {"_key": "my_input|k{:06d}".format(i), "input": "my_input", "ts": i}
            for i in range(total)
        ))
        result = _load_processed(collection.data, "my_input", "my_input|")
        self.assertEqual(len(result), total)

    def test_return_value_is_a_set_of_bare_key_strings(self):
        collection = FakeKVCollection()
        collection.data.seed(
            {"_key": "my_input|20260701", "input": "my_input", "ts": 1},
        )
        result = _load_processed(collection.data, "my_input", "my_input|")
        self.assertIsInstance(result, set)
        self.assertEqual(result, {"my_input|20260701"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
