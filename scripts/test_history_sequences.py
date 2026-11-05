"""Executable examples for the draft protocol, not a reporting implementation."""

import copy
import hashlib
import json
from pathlib import Path
import re
import unittest


VECTORS = Path(__file__).resolve().parents[1] / "test/history/sequences.json"
MAX_INDEX = 2**53 - 1


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

    def test_wire_example_is_a_valid_literal_root(self):
        spec = VECTORS.parents[2] / (
            "skills/instrumentation-spec/references/features/history-sequences.md"
        )
        documents = [json.loads(block) for block in re.findall(
            r"```json\n(.*?)\n```", spec.read_text(), flags=re.DOTALL
        )]
        envelope = next(document for document in documents if "sequences" in document)
        states = resolve(envelope["sequences"])
        row = envelope["rows"][0]
        binding = row["bindings"][0]
        self.assertEqual(binding["path"], [])
        self.assertEqual(row["event"][binding["field"]], [])
        self.assertEqual(states[binding["id"]], [
            {"role": "system", "content": "Be helpful."},
            {"role": "user", "content": "Hello"},
        ])


if __name__ == "__main__":
    unittest.main()
