"""Executable examples of the shared history model, not a reporting service."""

import copy
import hashlib
import json
from pathlib import Path
import re
import unittest
import uuid


VECTORS = Path(__file__).resolve().parents[1] / "test/history/sequences.json"
MAX_INDEX = 2**32 - 1


def index(value):
    if type(value) is not int or not 0 <= value <= MAX_INDEX:
        raise ValueError("invalid index")
    return value


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{32}", value):
        raise ValueError("invalid ID")
    if value == "0" * 32:
        raise ValueError("zero ID")
    return value


def part_value(part):
    if isinstance(part, dict) and set(part) == {"$braintrust_slice"}:
        section = part["$braintrust_slice"]
        if not isinstance(section, dict) or set(section) != {"id", "start", "end"}:
            raise ValueError("invalid slice")
        identifier(section["id"])
        if index(section["start"]) > index(section["end"]):
            raise ValueError("out-of-bounds slice")
        return "slice", section
    return "literal", part


def sequence_length(definition):
    if set(definition) != {"id", "parts"}:
        raise ValueError("invalid definition")
    identifier(definition["id"])
    if not isinstance(definition["parts"], list):
        raise ValueError("invalid parts")
    length = 0
    for part in definition["parts"]:
        kind, value = part_value(part)
        length = index(length + (value["end"] - value["start"] if kind == "slice" else 1))
    return length


def resolve(definitions):
    """Eager fixture evaluator; real storage need not expand ancestors."""
    by_id, resolved, visiting = {}, {}, set()
    for definition in definitions:
        sequence_length(definition)
        key = definition["id"]
        if key in by_id and by_id[key] != definition:
            raise ValueError("conflicting definition")
        by_id[key] = definition

    def visit(key):
        if key in visiting:
            raise ValueError("cycle")
        if key in resolved:
            return resolved[key]
        if key not in by_id:
            raise ValueError("missing sequence")
        visiting.add(key)
        result = []
        for part in by_id[key]["parts"]:
            kind, value = part_value(part)
            if kind == "literal":
                result.append(copy.deepcopy(value))
            else:
                source = visit(value["id"])
                if value["end"] > len(source):
                    raise ValueError("out-of-bounds slice")
                result.extend(copy.deepcopy(source[value["start"]:value["end"]]))
        visiting.remove(key)
        resolved[key] = result
        return result

    for key in by_id:
        visit(key)
    return resolved


def fingerprints(values):
    domain = b"braintrust.history.element.v1\0"
    return [hashlib.sha256(domain + json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")).digest() for value in values]


def match_parts(parent_id, parent_fingerprints, current, budget=10000):
    """Fixture encoder: no access to parent contents or a client history tree."""
    current_fingerprints = fingerprints(current)
    positions = {}
    for i, digest in enumerate(parent_fingerprints):
        positions.setdefault(digest, []).append(i)
    best = (0, 0, 0)
    for j, digest in enumerate(current_fingerprints):
        for i in positions.get(digest, []):
            k = 0
            while (budget > 0 and i + k < len(parent_fingerprints)
                   and j + k < len(current_fingerprints)):
                budget -= 1
                if parent_fingerprints[i + k] != current_fingerprints[j + k]:
                    break
                k += 1
            best = max(best, (k, -i, -j))
            if budget == 0:
                break
        if budget == 0:
            break
    length, old_start, new_start = best
    old_start, new_start = -old_start, -new_start
    if length == 0:
        return copy.deepcopy(current)
    parts = copy.deepcopy(current[:new_start])
    parts.append({"$braintrust_slice": {
        "id": parent_id, "start": old_start, "end": old_start + length,
    }})
    parts.extend(copy.deepcopy(current[new_start + length:]))
    literal = copy.deepcopy(current)
    return parts if len(json.dumps(parts)) < len(json.dumps(literal)) else literal


class ExampleCache:
    """Reference cache plus ordinary row-field projection; not a span sink."""

    def __init__(self):
        self.definitions = {}
        self.arrays = {}
        self.rows = {}

    def stage(self, definitions):
        staged = copy.deepcopy(self.definitions)
        for definition in definitions:
            key = definition["id"]
            if key in staged and staged[key] != definition:
                raise ValueError("conflicting definition")
            staged[key] = copy.deepcopy(definition)
        return staged, resolve(list(staged.values()))

    def apply(self, sequence):
        self.definitions, self.arrays = self.stage([sequence])
        return sequence["id"]

    def read(self, key):
        if key not in self.arrays:
            raise ValueError("missing sequence")
        return copy.deepcopy(self.arrays[key])

    def snapshot(self, key):
        values = self.read(key)
        return {"id": uuid.uuid4().hex, "parts": copy.deepcopy(values)}

    def apply_op(self, operation):
        materialized = copy.deepcopy(operation)
        payload = operation.get("input")
        definitions = []
        if isinstance(payload, dict) and set(payload) == {"$braintrust_history"}:
            sequence = payload["$braintrust_history"]
            if not isinstance(sequence, dict) or set(sequence) != {"id", "parts"}:
                raise ValueError("invalid sequenced input")
            definitions.append(sequence)
        staged, arrays = self.stage(definitions)
        if definitions:
            materialized["input"] = copy.deepcopy(arrays[definitions[0]["id"]])
        self.definitions, self.arrays = staged, arrays
        row = copy.deepcopy(self.rows.get(operation["id"], {}))
        row.update(materialized)
        self.rows[operation["id"]] = row
        return copy.deepcopy(row)


def compact(sequence):
    return {"$braintrust_history": sequence}


def read_sequence(key, load, start=0, end=None):
    """Range traversal over validated stored definitions, without ancestor expansion."""
    result, active, descriptors = [], set(), {}
    stack = [("node", key, start, end)]
    while stack:
        kind, value, lo, hi = stack.pop()
        if kind == "exit":
            active.remove(value)
            continue
        if kind == "literal":
            result.extend(copy.deepcopy(value[lo:hi]))
            continue
        if value in active:
            raise ValueError("cycle")
        if value not in descriptors:
            try:
                descriptors[value] = load(value)
            except KeyError as exc:
                raise ValueError("missing sequence") from exc
        definition = descriptors[value]
        if identifier(definition["id"]) != value:
            raise ValueError("wrong sequence identity")
        length = sequence_length(definition)
        lo, hi = index(lo), length if hi is None else index(hi)
        if not lo <= hi <= length:
            raise ValueError("out-of-bounds slice")
        active.add(value)
        tasks, offset = [], 0
        for part in definition["parts"]:
            part_kind, data = part_value(part)
            if part_kind == "literal":
                size = 1
                task_kind, source, source_start = "literal", [data], 0
            else:
                source_start = data["start"]
                size = data["end"] - source_start
                task_kind, source = "node", data["id"]
            overlap_start, overlap_end = max(lo, offset), min(hi, offset + size)
            if overlap_start < overlap_end:
                tasks.append((task_kind, source, source_start + overlap_start - offset,
                              source_start + overlap_end - offset))
            offset = index(offset + size)
        stack.append(("exit", value, None, None))
        stack.extend(reversed(tasks))
    return result


class HistorySequenceExamples(unittest.TestCase):
    def test_conformance_vectors(self):
        vectors = json.loads(VECTORS.read_text())
        self.assertEqual(vectors["version"], 1)
        for case in vectors["valid"]:
            with self.subTest(case=case["name"]):
                definitions = case["definitions"]
                original = copy.deepcopy(definitions)
                self.assertEqual(resolve(definitions), case["expected"])
                self.assertEqual(definitions, original)
                self.assertEqual(resolve(list(reversed(definitions))), case["expected"])
        for case in vectors["invalid"]:
            with self.subTest(case=case["name"]):
                with self.assertRaisesRegex(ValueError, case["error"]):
                    resolve(case["definitions"])

    def test_matching_from_fingerprints_without_parent_contents(self):
        parent_id, new_id = f"{1:032x}", f"{2:032x}"
        messages = [{"role": "user", "content": label * 200}
                    for label in "ABCDE"]
        a, b, c, d, e = messages
        summary = {"role": "system", "content": "Summary"}
        cases = [
            ([a, b], [a, b, c], (0, 2)),
            ([a, b, c, d], [summary, c, d, e], (2, 4)),
            ([a, b, b, c], [b, b], (1, 3)),
            ([a, b, c], [a], (0, 1)),
        ]
        for parent, current, expected_range in cases:
            with self.subTest(expected_range=expected_range):
                cache = fingerprints(parent)
                parts = match_parts(parent_id, cache, current)
                slices = [part["$braintrust_slice"] for part in parts
                          if isinstance(part, dict) and set(part) == {"$braintrust_slice"}]
                self.assertEqual([(s["start"], s["end"]) for s in slices],
                                 [expected_range])
                result = resolve([
                    {'id': parent_id, 'parts': copy.deepcopy(parent)},
                    {'id': new_id, 'parts': parts},
                ])
                self.assertEqual(result[new_id], current)

    def test_matching_fallbacks(self):
        parent_id = f"{1:032x}"
        repeated = [{"content": "same" * 200}] * 100
        self.assertEqual(match_parts(parent_id, fingerprints(repeated),
                                     repeated, budget=0), copy.deepcopy(repeated))
        self.assertEqual(match_parts(parent_id, fingerprints([1]), [2]),
                         [2])
        self.assertEqual(match_parts(parent_id, fingerprints([1]), []), [])
        # A reference is larger than this tiny matching value.
        self.assertEqual(match_parts(parent_id, fingerprints([1]), [1]),
                         [1])

    def test_mutation_of_application_objects_does_not_reuse_old_value(self):
        parent = [{"content": "old" * 200}]
        cache = fingerprints(parent)
        parent[0]["content"] = "changed" * 200
        self.assertEqual(match_parts(f"{1:032x}", cache, parent),
                         copy.deepcopy(parent))

    def test_matching_encoding_changes_only_reduce_reuse(self):
        parent = [{"role": "user", "content": "same" * 200}]
        reordered = [{"content": "same" * 200, "role": "user"}]
        self.assertEqual(parent, reordered)
        self.assertNotEqual(fingerprints(parent), fingerprints(reordered))
        self.assertEqual(match_parts(f"{1:032x}", fingerprints(parent), reordered),
                         copy.deepcopy(reordered))


    def test_document_spanops_replay_over_network_or_storage(self):
        spec = VECTORS.parents[2] / (
            "skills/instrumentation-spec/references/features/history-sequences.md"
        )
        operations = [json.loads(block) for block in re.findall(
            r"```json\n(.*?)\n```", spec.read_text(), flags=re.DOTALL
        )]
        live, restored = ExampleCache(), ExampleCache()
        self.assertEqual(len(operations), 2)
        for operation in operations:
            expected = live.apply_op(operation)
            self.assertEqual(restored.apply_op(json.loads(json.dumps(operation))), expected)
        self.assertEqual(restored.rows["span-row-2"]["input"], [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Tell me more"},
        ])

    def test_snapshot_operation_restores_compacted_history(self):
        case = json.loads(VECTORS.read_text())["valid"][0]
        root = case["definitions"][2]["id"]
        cache = ExampleCache()
        for definition in case["definitions"]:
            cache.apply(definition)
        snapshot = cache.snapshot(root)
        self.assertNotEqual(snapshot["id"], root)
        restored = ExampleCache()
        row = restored.apply_op(json.loads(json.dumps({
            "id": "restored", "input": compact(snapshot),
        })))
        self.assertEqual(row["input"], case["expected"][root])
        self.assertEqual(len(restored.definitions), 1)

    def test_reapplication_and_conflict_are_sequence_operations(self):
        definition = {'id': f'{1:032x}', 'parts': ['original']}
        cache = ExampleCache()
        key = cache.apply(definition)
        self.assertEqual(cache.apply(definition), key)
        changed = dict(definition, parts=["changed"])
        with self.assertRaisesRegex(ValueError, "conflicting definition"):
            cache.apply(changed)
        self.assertEqual(cache.read(key), ["original"])

    def test_missing_history_does_not_expose_partial_operation(self):
        definition = {'id': f'{1:032x}', 'parts': [{'$braintrust_slice': {'id': f'{2:032x}', 'start': 0, 'end': 1}}]}
        cache = ExampleCache()
        with self.assertRaisesRegex(ValueError, "missing sequence"):
            cache.apply_op({"id": "row", "input": compact(definition)})
        self.assertEqual(cache.definitions, {})
        self.assertEqual(cache.rows, {})

    def test_legacy_and_compact_updates_share_one_logical_field(self):
        cache = ExampleCache()
        cache.apply_op({"id": "row", "input": ["legacy"], "output": ["output"]})
        definition = {'id': f'{1:032x}', 'parts': ['compact']}
        row = cache.apply_op({"id": "row", "input": compact(definition)})
        self.assertEqual(row["input"], ["compact"])
        self.assertEqual(row["output"], ["output"])
        self.assertEqual(cache.apply_op({"id": "row", "input": None})["input"], None)
        row = cache.apply_op({"id": "row", "input": compact(definition)})
        self.assertEqual(row["input"], ["compact"])
        with self.assertRaisesRegex(ValueError, "invalid sequenced input"):
            cache.apply_op({"id": "row", "input": {"$braintrust_history": {"parts": []}}})
        self.assertEqual(cache.rows["row"]["input"], ["compact"])

    def test_response_joins_history_only_in_the_next_captured_input(self):
        cache = ExampleCache()
        user = {"role": "user", "content": "Question"}
        response = {"role": "assistant", "content": "Answer"}
        next_user = {"role": "user", "content": "Follow-up"}
        definition = {'id': f'{1:032x}', 'parts': [user]}
        first = cache.apply_op({"id": "first", "input": compact(definition),
                                "output": [response]})
        self.assertEqual(first["input"], [user])
        self.assertEqual(first["output"], [response])
        self.assertEqual(cache.read(definition["id"]), [user])
        next_input = {'id': f'{2:032x}', 'parts': [{'$braintrust_slice': {'id': definition['id'], 'start': 0, 'end': 1}}, response, next_user]}
        row = cache.apply_op({"id": "second", "input": compact(next_input)})
        self.assertEqual(row["input"], [user, response, next_user])
        self.assertNotIn("output", row)

    def test_output_keeps_its_existing_payload_format(self):
        definition = {'id': f'{1:032x}', 'parts': []}
        for output in (None, "response", {"content": "response"}, ["response"]):
            with self.subTest(output=output):
                row = ExampleCache().apply_op({"id": "row", "input": compact(definition),
                                              "output": output})
                self.assertEqual(row["input"], [])
                self.assertEqual(row["output"], output)

    def test_direct_parts_preserve_literal_arrays_and_nested_objects(self):
        values = [{"role": "user", "content": "message"}, ["nested", "array"], None,
                  {"content": {"$braintrust_slice": "nested data"}},
                  {"$braintrust_slice": "ordinary data", "other": True}]
        definition = {"id": f"{1:032x}", "parts": copy.deepcopy(values)}
        self.assertNotIn("length", definition)
        self.assertEqual(sequence_length(definition), len(values))
        cache = ExampleCache()
        key = cache.apply(definition)
        self.assertEqual(cache.read(key), values)
        self.assertEqual(read_sequence(key, {key: definition}.__getitem__), values)
        restored = ExampleCache()
        self.assertEqual(restored.read(restored.apply(cache.snapshot(key))), values)

    def test_length_is_derived_without_loading_sources_and_checks_overflow(self):
        definition = {"id": f"{1:032x}", "parts": [
            {"role": "user", "content": "message"},
            {"$braintrust_slice": {"id": f"{2:032x}", "start": 2, "end": 7}},
        ]}
        self.assertEqual(sequence_length(definition), 6)
        definition["parts"][1]["$braintrust_slice"]["end"] = 2**32 - 1
        definition["parts"][1]["$braintrust_slice"]["start"] = 0
        with self.assertRaisesRegex(ValueError, "invalid index"):
            sequence_length(definition)

    def test_tag_recognition_is_limited_to_the_reserved_position(self):
        ordinary_inputs = [
            {"content": {"$braintrust_history": "nested data"}},
            {"$braintrust_history": "ordinary data", "other": True},
            {"$braintrust_slice": "ordinary at the input root"},
        ]
        for payload in ordinary_inputs:
            with self.subTest(payload=payload):
                row = ExampleCache().apply_op({"id": "row", "input": payload})
                self.assertEqual(row["input"], payload)

    def test_nested_slice_indexes_materialized_items_across_parts(self):
        cases = json.loads(VECTORS.read_text())["valid"]
        case = next(c for c in cases if c["name"] == "nested-slice-crosses-part-boundaries")
        stored = {d["id"]: d for d in case["definitions"]}
        root = case["definitions"][2]["id"]
        self.assertEqual(read_sequence(root, stored.__getitem__), ["b", "c", "y"])

    def test_readback_loads_retained_ranges_not_discarded_ancestors(self):
        case = json.loads(VECTORS.read_text())["valid"][0]
        stored = {d["id"]: json.dumps(d) for d in case["definitions"]}
        root = case["definitions"][2]["id"]
        loaded = []

        def load(key):
            loaded.append(key)
            return json.loads(stored[key])

        restored = read_sequence(root, load)
        self.assertEqual(restored, case["expected"][root])
        self.assertEqual(loaded, [root, case["definitions"][1]["id"]])
        self.assertEqual(fingerprints(restored), fingerprints(case["expected"][root]))
        self.assertEqual(read_sequence(root, lambda key: json.loads(stored[key]), 1, 3),
                         case["expected"][root][1:3])

    def test_readback_uses_a_stack_for_long_chains(self):
        definitions = {f"{1:032x}": {'id': f'{1:032x}', 'parts': ['message']}}
        for i in range(2, 1501):
            definitions[f"{i:032x}"] = {'id': f'{i:032x}', 'parts': [{'$braintrust_slice': {'id': f'{i - 1:032x}', 'start': 0, 'end': 1}}]}
        self.assertEqual(read_sequence(f"{1500:032x}", definitions.__getitem__), ["message"])

    def test_readback_reports_missing_state_and_cycles(self):
        key = f"{1:032x}"
        with self.assertRaisesRegex(ValueError, "missing sequence"):
            read_sequence(key, {}.__getitem__)
        cyclic = {'id': key, 'parts': [{'$braintrust_slice': {'id': key, 'start': 0, 'end': 1}}]}
        with self.assertRaisesRegex(ValueError, "cycle"):
            read_sequence(key, lambda _: cyclic)

    def test_literal_reference_shaped_data_and_uint32(self):
        data = {"array": "application data", "nested": [None, []]}
        row = ExampleCache().apply_op({"id": "row", "input": data})
        self.assertEqual(row["input"], data)
        self.assertEqual(index(2**32 - 1), 2**32 - 1)
        with self.assertRaisesRegex(ValueError, "invalid index"):
            index(2**32)


if __name__ == "__main__":
    unittest.main()
