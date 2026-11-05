"""Executable examples for the draft protocol, not a reporting implementation."""

import copy
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
