"""Snapshot/delta semantics for completed requests; not a production span sink."""

import copy
import json
from pathlib import Path
import re
import unittest


CONVERSATION = "gen_ai.conversation.id"
MISSING = object()
SPEC = Path(__file__).resolve().parents[1] / (
    "skills/instrumentation-spec/references/features/history-sequences.md"
)


def same_json(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_json(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_json(a, b) for a, b in zip(left, right))
    return left == right


class Reporter:
    """Reference policy. Real queueing, persistence, and cache budgets are external."""

    def __init__(self, deltas=False):
        self.deltas = deltas
        self.previous = {}

    def encode(self, key, items, output=MISSING, conversation=None, linear=True):
        row = {"id": key, "input": copy.deepcopy(items)}
        if output is not MISSING:
            row["output"] = copy.deepcopy(output)
        if conversation is not None:
            row["metadata"] = {CONVERSATION: conversation}
        eligible = self.deltas and linear and bool(conversation) and isinstance(items, list)
        previous = self.previous.get(conversation) if eligible else None
        if previous is not None:
            prefix = previous[0] + previous[1]
            if len(items) >= len(prefix) and same_json(items[:len(prefix)], prefix):
                del row["input"]
                row["input_delta"] = copy.deepcopy(items[len(prefix):])
        if not self.deltas:
            self.previous.clear()
        elif eligible and isinstance(output, list):
            self.previous[conversation] = (copy.deepcopy(items), copy.deepcopy(output))
        else:
            self.previous.pop(conversation, None)
        return row


class Replay:
    """Reference readback over ordered completed requests; retain frozen versions."""

    def __init__(self):
        self.contexts, self.rows, self.records = {}, {}, {}

    def apply(self, record):
        key = record["id"]
        if key in self.records:
            if not same_json(record, self.records[key]):
                raise ValueError("conflicting completed request")
            return copy.deepcopy(self.rows[key])
        if "input" in record and "input_delta" in record:
            raise ValueError("both full and delta inputs")
        conversation = record.get("metadata", {}).get(CONVERSATION)
        row = copy.deepcopy(record)
        if "input" in record:
            items = copy.deepcopy(record["input"])
        elif "input_delta" in record:
            if not isinstance(record["input_delta"], list):
                raise ValueError("invalid delta")
            previous = self.contexts.get(conversation)
            if previous is None or not isinstance(previous[1], list):
                raise ValueError("unresolved history")
            items = copy.deepcopy(previous[0] + previous[1] + record["input_delta"])
            del row["input_delta"]
            row["input"] = items
        else:
            raise ValueError("missing input")
        if conversation:
            if isinstance(items, list):
                self.contexts[conversation] = (copy.deepcopy(items), copy.deepcopy(record.get("output")))
            else:
                self.contexts.pop(conversation, None)
        self.records[key], self.rows[key] = copy.deepcopy(record), copy.deepcopy(row)
        return row


class HistorySnapshotDeltaTests(unittest.TestCase):
    def setUp(self):
        self.system = {"role": "system", "content": "Be helpful"}
        self.user = {"role": "user", "content": "Question"}
        self.answer = {"role": "assistant", "content": "Answer"}
        self.followup = {"role": "user", "content": "Follow-up"}
        self.initial = [self.system, self.user]
        self.next = self.initial + [self.answer, self.followup]

    def start(self, reporter):
        return reporter.encode("first", self.initial, [self.answer], "A")

    def test_full_mode_retains_no_comparison_history(self):
        reporter = Reporter()
        for output in (None, "response", {"content": "response"}, [self.answer]):
            row = reporter.encode("request", self.initial, output, "A")
            self.assertEqual(row["input"], self.initial)
            self.assertEqual(row["output"], output)
            self.assertNotIn("input_delta", row)
        self.assertEqual(reporter.previous, {})

    def test_document_examples_reconstruct_the_complete_input(self):
        records = [json.loads(block) for block in re.findall(
            r"```json\n(.*?)\n```", SPEC.read_text(), flags=re.DOTALL
        )]
        replay = Replay()
        self.assertEqual(len(records), 2)
        for record in records:
            row = replay.apply(json.loads(json.dumps(record)))
        self.assertEqual(row["input"], [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hello!"},
            {"role": "user", "content": "Tell me more"},
        ])

    def test_append_and_empty_delta_reuse_predecessor_output(self):
        for tail in ([], [self.followup]):
            with self.subTest(tail=tail):
                reporter, replay = Reporter(True), Replay()
                first = self.start(reporter)
                current = self.initial + [self.answer] + tail
                second = reporter.encode("second", current, [], "A")
                self.assertEqual(second["input_delta"], tail)
                replay.apply(first)
                self.assertEqual(replay.apply(second)["input"], current)

    def test_non_append_changes_are_independent_snapshots(self):
        cases = [
            [{"role": "system", "content": "Summary"}, self.followup],
            [self.system],  # Truncation.
            self.initial,  # Regeneration omits the preceding response.
            [{"role": "system", "content": "Changed"}, self.user, self.answer],
            self.initial + [{"role": "assistant", "content": "Alternative"}, self.followup],
        ]
        for current in cases:
            with self.subTest(current=current):
                reporter = Reporter(True)
                self.start(reporter)
                row = reporter.encode("changed", current, [], "A")
                self.assertEqual(row["input"], current)
                self.assertNotIn("input_delta", row)
                self.assertEqual(Replay().apply(row)["input"], current)

    def test_eviction_and_mode_changes_restart_with_a_checkpoint(self):
        reporter = Reporter(True)
        self.start(reporter)
        reporter.previous.clear()
        self.assertIn("input", reporter.encode("resumed", self.next, [], "A"))
        reporter.deltas = False
        self.assertIn("input", reporter.encode("full", self.next, [], "A"))
        self.assertEqual(reporter.previous, {})
        reporter.deltas = True
        self.assertIn("input", reporter.encode("enabled", self.next, [], "A"))

    def test_fork_has_a_new_id_and_initial_snapshot_then_independent_deltas(self):
        reporter, replay = Reporter(True), Replay()
        records = [self.start(reporter)]
        records.append(reporter.encode("fork-first", self.next, [self.answer], "B"))
        self.assertIn("input", records[-1])
        records.append(reporter.encode("parent-next", self.next, [], "A"))
        self.assertEqual(records[-1]["input_delta"], [self.followup])
        fork_next = self.next + [self.answer, self.followup]
        records.append(reporter.encode("fork-next", fork_next, [], "B"))
        self.assertEqual(records[-1]["input_delta"], [self.followup])
        for record in records:
            row = replay.apply(record)
        self.assertEqual(row["input"], fork_next)
        self.assertEqual(replay.rows["parent-next"]["input"], self.next)

    def test_unknown_identity_or_ambiguous_stream_uses_full_reporting(self):
        for conversation, linear in ((None, True), ("A", False)):
            reporter = Reporter(True)
            self.start(reporter)
            row = reporter.encode("ambiguous", self.next, [], conversation, linear)
            self.assertIn("input", row)
            self.assertNotIn("input_delta", row)

    def test_unavailable_output_requires_a_snapshot(self):
        reporter = Reporter(True)
        reporter.encode("first", self.initial, conversation="A")
        row = reporter.encode("second", self.next, [], "A")
        self.assertEqual(row["input"], self.next)

    def test_missing_checkpoint_or_output_is_unresolved(self):
        delta = {"id": "second", "metadata": {CONVERSATION: "A"}, "input_delta": []}
        replay = Replay()
        with self.assertRaisesRegex(ValueError, "unresolved history"):
            replay.apply(delta)
        replay.apply({"id": "first", "metadata": {CONVERSATION: "A"}, "input": self.initial})
        with self.assertRaisesRegex(ValueError, "unresolved history"):
            replay.apply(delta)
        self.assertNotIn("second", replay.rows)

    def test_duplicate_delta_is_not_appended_again(self):
        reporter, replay = Reporter(True), Replay()
        replay.apply(self.start(reporter))
        second = reporter.encode("second", self.next, [], "A")
        self.assertEqual(replay.apply(second), replay.apply(copy.deepcopy(second)))
        self.assertEqual(replay.rows["second"]["input"], self.next)

    def test_capture_is_frozen_and_comparison_preserves_json_types(self):
        reporter = Reporter(True)
        items = [{"role": "user", "content": {"value": True}}]
        reporter.encode("first", items, [], "A")
        items[0]["content"]["value"] = 1
        row = reporter.encode("changed", items, [], "A")
        self.assertIn("input", row)
        self.assertEqual(reporter.previous["A"][0], items)
        self.assertFalse(same_json({"value": True}, {"value": 1}))

    def test_full_and_delta_are_mutually_exclusive(self):
        with self.assertRaisesRegex(ValueError, "both full and delta"):
            Replay().apply({"id": "invalid", "input": [], "input_delta": []})


if __name__ == "__main__":
    unittest.main()
