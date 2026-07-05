# Copyright (c) 2026 Cloudflare, Inc.
# Licensed under the Apache 2.0 license.

"""
In-memory fake of a Splunk KV Store collection, for testing
cloudflare_r2_helper.py's checkpoint/dedupe/prune logic without a real
Splunk instance.

Faithfully replicates the exact client-API quirks documented in
cloudflare_r2_helper.py's module docstring (get these wrong and a test gives
false confidence rather than real coverage):

  - query(query={dict}, ...)  -- accepts a query dict directly.
  - delete(query=<STRING>)    -- requires a pre-JSON-encoded string, NOT a
    dict. This fake raises TypeError if you pass a dict, so a test written
    the wrong way fails loudly instead of silently matching everything.
  - batch_save(*documents)    -- upserts by "_key" (insert-or-overwrite).

Supported query operators: $and, $or, $gte, $gt, $lte, $lt, plus bare
equality ({"field": value}). This is exactly the operator set
cloudflare_r2_helper.py actually uses -- it is not a general MongoDB-style
query engine.
"""

import json


def _cond_matches(value, cond):
    if isinstance(cond, dict):
        for op, target in cond.items():
            if op == "$gte":
                ok = value >= target
            elif op == "$gt":
                ok = value > target
            elif op == "$lte":
                ok = value <= target
            elif op == "$lt":
                ok = value < target
            else:
                raise NotImplementedError(
                    "FakeKVData: unsupported operator {!r}".format(op)
                )
            if not ok:
                return False
        return True
    return value == cond


def _row_matches(row, query):
    if not query:
        return True
    if "$and" in query:
        return all(_row_matches(row, clause) for clause in query["$and"])
    if "$or" in query:
        return any(_row_matches(row, clause) for clause in query["$or"])
    for field, cond in query.items():
        if field not in row or not _cond_matches(row[field], cond):
            return False
    return True


class FakeKVData:
    """Stand-in for the `.data` accessor on a Splunk KV Store collection."""

    def __init__(self, rows=None):
        self._rows = {}
        for row in rows or ():
            self._rows[row["_key"]] = dict(row)

    # -- test-only seeding helpers (not part of the real KV Store API) ------

    def seed(self, *rows):
        for row in rows:
            self._rows[row["_key"]] = dict(row)

    def all_rows(self):
        return [dict(r) for r in self._rows.values()]

    def __len__(self):
        return len(self._rows)

    # -- real KV Store API surface, matching what cloudflare_r2_helper.py uses --

    def query(self, query=None, fields=None, sort=None, limit=None, skip=0):
        matched = [r for r in self._rows.values() if _row_matches(r, query or {})]
        if sort:
            reverse = sort.startswith("-")
            key = sort[1:] if reverse else sort
            matched.sort(key=lambda r: r.get(key), reverse=reverse)
        if skip:
            matched = matched[skip:]
        if limit is not None:
            matched = matched[:limit]
        if fields:
            wanted = [f.strip() for f in fields.split(",")]
            matched = [{f: r[f] for f in wanted if f in r} for r in matched]
        else:
            matched = [dict(r) for r in matched]
        return matched

    def batch_save(self, *documents):
        for doc in documents:
            if "_key" not in doc:
                raise ValueError("FakeKVData.batch_save: document missing _key")
            self._rows[doc["_key"]] = dict(doc)
        return list(documents)

    def delete(self, query=None):
        if query is None:
            count = len(self._rows)
            self._rows.clear()
            return count
        if not isinstance(query, str):
            # This is the load-bearing check: the real KV Store client's
            # delete() does NOT auto-encode a dict the way query() does. A
            # caller (or a test) that passes a raw dict here is exercising a
            # bug that would silently misbehave against the real API -- fail
            # loudly instead.
            raise TypeError(
                "FakeKVData.delete(query=...) requires a JSON-encoded string "
                "(matching the real KV Store client's asymmetry with "
                "query()), got {}".format(type(query).__name__)
            )
        parsed = json.loads(query)
        to_delete = [k for k, r in self._rows.items() if _row_matches(r, parsed)]
        for k in to_delete:
            del self._rows[k]
        return len(to_delete)


class FakeKVCollection:
    """Stand-in for the collection entity _kv_collection() returns: exposes
    .content (for the _assert_typed type-guard) and .data (a FakeKVData)."""

    def __init__(self, field_ts_type="number", rows=None):
        self.content = {"field.ts": field_ts_type}
        self.data = FakeKVData(rows)
        self.refresh_calls = 0

    def refresh(self):
        # The real collection.refresh() re-fetches metadata from the server.
        # Our .content is already authoritative, so this is a no-op that just
        # records the call, letting a test assert _assert_typed actually
        # calls refresh() before trusting .content (i.e. it can't pass by
        # accident against stale local state).
        self.refresh_calls += 1
