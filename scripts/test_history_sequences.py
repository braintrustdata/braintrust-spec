"""Executable examples of the shared history model, not a reporting service."""

import copy
import hashlib
import json
from pathlib import Path
import re
import unittest


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


def resolve(definitions):
    """Small bounded fixture evaluator; production must use indexed storage."""
    by_id, resolved, visiting = {}, {}, set()
    for definition in definitions:
        if set(definition) != {"id", "length", "parts"}:
            raise ValueError("invalid definition")
        key = identifier(definition["id"])
        if key in by_id:
            raise ValueError("duplicate definition")
        index(definition["length"])
        if not isinstance(definition["parts"], list):
            raise ValueError("invalid parts")
        by_id[key] = definition

    def visit(key):
        identifier(key)
        if key in visiting:
            raise ValueError("cycle")
        if key in resolved:
            return resolved[key]
        if key not in by_id:
            raise ValueError("missing sequence")
        visiting.add(key)
        result = []
        for part in by_id[key]["parts"]:
            if not isinstance(part, dict):
                raise ValueError("invalid part")
            if set(part) == {"literal"} and isinstance(part["literal"], list):
                result.extend(copy.deepcopy(part["literal"]))
            elif set(part) == {"slice"} and isinstance(part["slice"], dict):
                section = part["slice"]
                if set(section) != {"id", "start", "end"}:
                    raise ValueError("invalid slice")
                source = visit(section["id"])
                start, end = index(section["start"]), index(section["end"])
                if not start <= end <= len(source):
                    raise ValueError("out-of-bounds slice")
                result.extend(copy.deepcopy(source[start:end]))
            else:
                raise ValueError("invalid part")
        if len(result) != by_id[key]["length"]:
            raise ValueError("length mismatch")
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
        return [{"literal": copy.deepcopy(current)}] if current else []
    parts = []
    if new_start:
        parts.append({"literal": copy.deepcopy(current[:new_start])})
    parts.append({"slice": {
        "id": parent_id, "start": old_start, "end": old_start + length,
    }})
    if new_start + length < len(current):
        parts.append({"literal": copy.deepcopy(current[new_start + length:])})
    literal = [{"literal": copy.deepcopy(current)}]
    return parts if len(json.dumps(parts)) < len(json.dumps(literal)) else literal


class ExampleCache:
    """Reference semantics only; storage and reporting are deliberately absent."""

    def __init__(self):
        self.definitions = {}
        self.arrays = {}

    @staticmethod
    def decode(value, arrays):
        if not isinstance(value, dict) or len(value) != 1:
            raise ValueError("invalid encoded value")
        if "literal" in value:
            return copy.deepcopy(value["literal"])
        if "array" in value:
            key = identifier(value["array"])
            if key not in arrays:
                raise ValueError("missing sequence")
            return copy.deepcopy(arrays[key])
        if "object" in value and isinstance(value["object"], dict):
            return {key: ExampleCache.decode(child, arrays)
                    for key, child in value["object"].items()}
        raise ValueError("invalid encoded value")

    def apply(self, frame):
        if set(frame) != {"sequences", "values"}:
            raise ValueError("invalid frame")
        staged = copy.deepcopy(self.definitions)
        seen = set()
        for definition in frame["sequences"]:
            key = definition["id"]
            if key in seen:
                raise ValueError("duplicate definition")
            seen.add(key)
            if key in staged and staged[key] != definition:
                raise ValueError("conflicting definition")
            staged[key] = copy.deepcopy(definition)
        arrays = resolve(list(staged.values()))
        for value in frame["values"]:
            self.decode(value, arrays)
        self.definitions, self.arrays = staged, arrays
        return copy.deepcopy(frame["values"])

    def read(self, value):
        return self.decode(value, self.arrays)

    def export(self, roots):
        needed = set()

        def sequence(key):
            if key in needed:
                return
            needed.add(key)
            for part in self.definitions[key]["parts"]:
                if "slice" in part:
                    sequence(part["slice"]["id"])

        def value(node):
            if "array" in node:
                sequence(node["array"])
            elif "object" in node:
                for child in node["object"].values():
                    value(child)

        for root in roots:
            value(root)
        return {"sequences": [copy.deepcopy(d) for key, d in self.definitions.items()
                              if key in needed], "values": copy.deepcopy(roots)}


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
                slices = [part["slice"] for part in parts if "slice" in part]
                self.assertEqual([(s["start"], s["end"]) for s in slices],
                                 [expected_range])
                result = resolve([
                    {"id": parent_id, "length": len(parent),
                     "parts": [{"literal": parent}]},
                    {"id": new_id, "length": len(current), "parts": parts},
                ])
                self.assertEqual(result[new_id], current)

    def test_matching_fallbacks(self):
        parent_id = f"{1:032x}"
        repeated = [{"content": "same" * 200}] * 100
        self.assertEqual(match_parts(parent_id, fingerprints(repeated),
                                     repeated, budget=0), [{"literal": repeated}])
        self.assertEqual(match_parts(parent_id, fingerprints([1]), [2]),
                         [{"literal": [2]}])
        self.assertEqual(match_parts(parent_id, fingerprints([1]), []), [])
        # A reference is larger than this tiny matching value.
        self.assertEqual(match_parts(parent_id, fingerprints([1]), [1]),
                         [{"literal": [1]}])

    def test_mutation_of_application_objects_does_not_reuse_old_value(self):
        parent = [{"content": "old" * 200}]
        cache = fingerprints(parent)
        parent[0]["content"] = "changed" * 200
        self.assertEqual(match_parts(f"{1:032x}", cache, parent),
                         [{"literal": parent}])

    def test_matching_encoding_changes_only_reduce_reuse(self):
        parent = [{"role": "user", "content": "same" * 200}]
        reordered = [{"content": "same" * 200, "role": "user"}]
        self.assertEqual(parent, reordered)
        self.assertNotEqual(fingerprints(parent), fingerprints(reordered))
        self.assertEqual(match_parts(f"{1:032x}", fingerprints(parent), reordered),
                         [{"literal": reordered}])


    def test_document_frames_replay_over_network_or_storage(self):
        spec = VECTORS.parents[2] / (
            "skills/instrumentation-spec/references/features/history-sequences.md"
        )
        frames = [json.loads(block) for block in re.findall(
            r"```json\n(.*?)\n```", spec.read_text(), flags=re.DOTALL
        )]
        sender_view, restored = ExampleCache(), ExampleCache()
        self.assertEqual(len(frames), 2)
        for frame in frames:
            values = sender_view.apply(frame)
            # The same serialized frame can cross a network or be read from storage.
            restored_values = restored.apply(json.loads(json.dumps(frame)))
            self.assertEqual([sender_view.read(v) for v in values],
                             [restored.read(v) for v in restored_values])
        self.assertEqual(restored.read(restored_values[0])["input"], [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Tell me more"},
        ])

    def test_self_contained_export_restores_compacted_history(self):
        case = json.loads(VECTORS.read_text())["valid"][0]
        root = {"array": case["definitions"][2]["id"]}
        cache = ExampleCache()
        cache.apply({"sequences": case["definitions"], "values": [root]})
        restored = ExampleCache()
        exported = json.loads(json.dumps(cache.export([root])))
        values = restored.apply(exported)
        self.assertEqual(restored.read(values[0]), case["expected"][root["array"]])
        self.assertEqual(len(exported["sequences"]), 3)  # Unrelated branch omitted.

    def test_reapplication_and_conflict_are_sequence_operations(self):
        definition = {"id": f"{1:032x}", "length": 1,
                      "parts": [{"literal": ["original"]}]}
        frame = {"sequences": [definition], "values": [{"array": definition["id"]}]}
        cache = ExampleCache()
        first = cache.apply(frame)
        self.assertEqual(cache.apply(frame), first)  # Values still emitted on replay.
        changed = copy.deepcopy(frame)
        changed["sequences"][0]["parts"] = [{"literal": ["changed"]}]
        with self.assertRaisesRegex(ValueError, "conflicting definition"):
            cache.apply(changed)
        self.assertEqual(cache.read(first[0]), ["original"])

    def test_invalid_value_does_not_expose_partial_frame(self):
        definition = {"id": f"{1:032x}", "length": 0, "parts": []}
        cache = ExampleCache()
        with self.assertRaisesRegex(ValueError, "missing sequence"):
            cache.apply({"sequences": [definition],
                         "values": [{"array": f"{2:032x}"}]})
        self.assertEqual(cache.definitions, {})

    def test_literal_reference_shaped_data_and_uint32(self):
        value = {"literal": {"array": "application data", "nested": [None, []]}}
        cache = ExampleCache()
        self.assertEqual(cache.read(cache.apply({"sequences": [], "values": [value]})[0]),
                         value["literal"])
        self.assertEqual(index(2**32 - 1), 2**32 - 1)
        with self.assertRaisesRegex(ValueError, "invalid index"):
            index(2**32)


if __name__ == "__main__":
    unittest.main()
