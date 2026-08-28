from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import assess_compatibility as assess
from compatibility import load_catalog


SPEC = """# Example

Spec text with unknown in prose must not change.

# SDK support

```yaml
id: example
name: Example
category: Instrumentation
support:
  first:
    go: "unknown" # pending unknown assessment
    python: "yes" # known support
  second:
    go: "unknown"
    python: "no"
```
"""


class AssessmentTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        assess.write_json(self.root / "capabilities/sdks.json", {
            "sdks": [{"key": "go", "title": "Go"}, {"key": "python", "title": "Python"}],
        })
        self.spec = self.root / "skills/instrumentation-spec/references/features/example.md"
        self.spec.parent.mkdir(parents=True)
        self.spec.write_text(SPEC)
        self.expected = assess.non_yes_cells(str(self.root))["go"]
        self.request = {
            "sdk": "go", "repository": assess.SDK_REPOSITORIES["go"],
            "revision": "a" * 40, "ref": "v1.0.0", "ref_kind": "release",
            "capabilities": self.expected,
        }
        self.result = {"assessments": [
            {"feature": "example", "capability": "first", "status": "partial",
             "rationale": "Implementation supports only part of the contract.",
             "evidence": [{"path": "sdk.go", "start_line": 1, "end_line": 2}]},
            {"feature": "example", "capability": "second", "status": "unknown",
             "rationale": "No conclusive evidence available.", "evidence": []},
        ]}
        self.results = self.root / "results"
        self.report = self.root / "capabilities/assessment.json"

    def store_result(self):
        assess.write_json(self.results / "assessment-go/request.json", self.request)
        assess.write_json(self.results / "assessment-go/result.json", self.result)
        # Other SDKs must also return every eligible cell, even when inconclusive.
        python_cells = assess.non_yes_cells(str(self.root))["python"]
        assess.write_json(self.results / "assessment-python/request.json", {
            **self.request, "sdk": "python", "repository": assess.SDK_REPOSITORIES["python"],
            "capabilities": python_cells,
        })
        assess.write_json(self.results / "assessment-python/result.json", {
            "assessments": [
                {"feature": cell["feature"], "capability": cell["capability"],
                 "status": "unknown", "rationale": "No conclusive evidence.", "evidence": []}
                for cell in python_cells
            ],
        })

    def test_apply_preserves_yes_and_inconclusive_cells(self):
        self.store_result()
        self.assertEqual(1, assess.apply(self.results, self.report, str(self.root)))
        rows = load_catalog(str(self.root)).features[0].rows
        self.assertEqual([("partial", "yes"), ("unknown", "no")], [
            (row.cells["go"].status, row.cells["python"].status) for row in rows
        ])
        self.assertEqual(
            SPEC.replace('"unknown" # pending unknown assessment',
                         '"partial" # pending unknown assessment'),
            self.spec.read_text(),
        )
        report = json.loads(self.report.read_text())
        evidence = report["sdks"][0]["assessments"][0]["evidence"][0]
        self.assertEqual(
            f"https://github.com/braintrustdata/braintrust-sdk-go/blob/{'a' * 40}/sdk.go#L1-L2",
            evidence["url"],
        )

    def test_missing_duplicate_and_unrequested_decisions_are_rejected_before_writes(self):
        original = deepcopy(self.result)
        invalid = [
            [original["assessments"][0]],
            original["assessments"] + [original["assessments"][0]],
            original["assessments"] + [{**original["assessments"][0], "capability": "invented"}],
        ]
        for decisions in invalid:
            with self.subTest(decisions=decisions):
                self.result = {"assessments": decisions}
                self.store_result()
                with self.assertRaises(ValueError):
                    assess.apply(self.results, self.report, str(self.root))
                self.assertEqual(SPEC, self.spec.read_text())
                self.assertFalse(self.report.exists())

    def test_stale_assessment_cannot_overwrite_changed_non_yes_status(self):
        self.store_result()
        current = SPEC.replace('"unknown" # pending unknown assessment',
                               '"no" # pending unknown assessment')
        self.spec.write_text(current)
        with self.assertRaises(ValueError):
            assess.apply(self.results, self.report, str(self.root))
        self.assertEqual(current, self.spec.read_text())

    def test_inconclusive_run_creates_no_changes_or_report(self):
        self.result["assessments"][0]["status"] = "unknown"
        self.store_result()
        self.assertEqual(0, assess.apply(self.results, self.report, str(self.root)))
        self.assertEqual(SPEC, self.spec.read_text())
        self.assertFalse(self.report.exists())

    def test_missing_sdk_results_cannot_publish_partial_run(self):
        self.store_result()
        (self.results / "assessment-python/request.json").unlink()
        before = self.spec.read_text()
        with self.assertRaises(ValueError):
            assess.apply(self.results, self.report, str(self.root))
        self.assertEqual(before, self.spec.read_text())

    def test_known_decision_requires_evidence(self):
        self.result["assessments"][0]["evidence"] = []
        with self.assertRaises(ValueError):
            assess.validate(self.request, self.result, self.expected)

    def test_citations_must_resolve_within_pinned_source(self):
        source = self.root / "source"
        source.mkdir()
        subprocess.run(["git", "init", "-q", str(source)], check=True)
        (source / "sdk.go").write_text("// Implementation\npackage sdk\n")
        subprocess.run(["git", "-C", str(source), "add", "sdk.go"], check=True)
        subprocess.run([
            "git", "-C", str(source), "-c", "user.name=Test", "-c", "user.email=test@example.com",
            "-c", "commit.gpgsign=false", "commit", "-qm", "Fixture",
        ], check=True)
        self.request["revision"] = assess.command("git", "-C", str(source), "rev-parse", "HEAD")
        assess.validate(self.request, self.result, self.expected, source)
        # A later working-tree addition must not make a fabricated citation valid.
        (source / "sdk.go").write_text("// Implementation\npackage sdk\n// Not committed\n")
        evidence = self.result["assessments"][0]["evidence"][0]
        evidence["end_line"] = 3
        with self.assertRaises(ValueError):
            assess.validate(self.request, self.result, self.expected, source)
        evidence.update(path="../outside.go", end_line=2)
        with self.assertRaises(ValueError):
            assess.validate(self.request, self.result, self.expected, source)

    def test_selects_all_non_yes_states_with_their_starting_values(self):
        self.spec.write_text(SPEC.replace(
            '    go: "unknown"\n    python: "no"',
            '    go: "partial"\n    python: "no"\n'
            '  third:\n    go: "n/a"\n    python: "yes"',
        ))
        cells = assess.non_yes_cells(str(self.root))
        self.assertEqual({
            ("go", "first", "unknown"), ("go", "second", "partial"),
            ("go", "third", "n/a"), ("python", "second", "no"),
        }, {
            (sdk, cell["capability"], cell["current_status"])
            for sdk, capabilities in cells.items() for cell in capabilities
        })

    def test_applies_changes_to_previously_assessed_states(self):
        current = SPEC.replace(
            '"unknown" # pending unknown assessment', '"no" # pending unknown assessment',
        ).replace('    go: "unknown"', '    go: "partial"').replace(
            '    python: "no"', '    python: "n/a"',
        )
        self.spec.write_text(current)
        self.request["capabilities"] = assess.non_yes_cells(str(self.root))["go"]
        self.result["assessments"][1].update(
            status="yes", rationale="Remaining behavior is now implemented.",
            evidence=[{"path": "sdk.go", "start_line": 1, "end_line": 2}],
        )
        self.store_result()
        assess.write_json(self.results / "assessment-python/result.json", {
            "assessments": [{
                "feature": "example", "capability": "second", "status": "no",
                "rationale": "The capability applies but is not implemented.",
                "evidence": [{"path": "sdk.py", "start_line": 1, "end_line": 2}],
            }],
        })
        self.assertEqual(3, assess.apply(self.results, self.report, str(self.root)))
        rows = load_catalog(str(self.root)).features[0].rows
        self.assertEqual([("partial", "yes"), ("yes", "no")], [
            (row.cells["go"].status, row.cells["python"].status) for row in rows
        ])

    def test_unchanged_known_results_create_no_changes_or_report(self):
        current = SPEC.replace('"unknown" # pending unknown assessment',
                               '"partial" # pending unknown assessment')
        self.spec.write_text(current)
        self.request["capabilities"] = assess.non_yes_cells(str(self.root))["go"]
        self.store_result()
        self.assertEqual(0, assess.apply(self.results, self.report, str(self.root)))
        self.assertEqual(current, self.spec.read_text())
        self.assertFalse(self.report.exists())

    def test_fortnightly_schedule_survives_iso_week_53_and_year_boundary(self):
        days = [date(2026, 12, 21) + timedelta(weeks=i) for i in range(4)]
        self.assertEqual([True, False, True, False], [assess.scheduled_week(day) for day in days])
        self.assertTrue(assess.scheduled_week(assess.SCHEDULE_ANCHOR))


if __name__ == "__main__":
    unittest.main()
