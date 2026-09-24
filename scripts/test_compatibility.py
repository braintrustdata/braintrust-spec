import os
import tempfile
import unittest

import compatibility as compat


SDKS = [compat.Sdk(key="go", title="Go"), compat.Sdk(key="python", title="Python")]
SUPPORT = '''support:
  example:
    go: "unknown"
    python: "yes"
'''


def spec(yaml_text=SUPPORT):
    return "# Example\n\n# SDK support\n\n```yaml\n" + yaml_text + "```\n"


class CatalogTests(unittest.TestCase):
    def make_repo(
        self,
        specs: dict[str, str],
        sdks: str = '{"sdks":[{"key":"go","title":"Go"},{"key":"python","title":"Python"}]}',
    ) -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.makedirs(os.path.join(tmp.name, "capabilities"))
        os.makedirs(os.path.join(tmp.name, "skills", "instrumentation-spec", "references", "features"))
        with open(os.path.join(tmp.name, "capabilities", "sdks.json"), "w") as handle:
            handle.write(sdks)
        for name, content in specs.items():
            path = os.path.join(tmp.name, "skills", "instrumentation-spec", "references", "features", name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(content)
        return tmp.name

    def test_catalog_returns_all_features_in_source_path_order(self):
        root = self.make_repo({"z-last.md": spec(), "a-first.md": spec()})
        catalog = compat.load_catalog(root)
        self.assertEqual(["go", "python"], [sdk.key for sdk in catalog.sdks])
        self.assertEqual(["a-first", "z-last"], [feature.id for feature in catalog.features])
        self.assertEqual("yes", catalog.features[0].rows[0].cells["python"].status)

    def test_rejects_duplicate_sdk_keys(self):
        root = self.make_repo(
            {"example.md": spec()},
            '{"sdks":[{"key":"go","title":"Go"},{"key":"go","title":"Other Go"}]}',
        )
        with self.assertRaises(compat.CompatibilityError):
            compat.load_catalog(root)

    def test_rejects_duplicate_sdk_titles(self):
        root = self.make_repo(
            {"example.md": spec()},
            '{"sdks":[{"key":"go","title":"SDK"},{"key":"python","title":"SDK"}]}',
        )
        with self.assertRaises(compat.CompatibilityError):
            compat.load_catalog(root)

    def test_requires_every_spec_to_have_support(self):
        root = self.make_repo({"example.md": "# Example\n\nNo support data.\n"})
        with self.assertRaises(compat.CompatibilityError):
            compat.load_catalog(root)

    def test_rejects_feature_id_collision_across_nested_specs(self):
        root = self.make_repo({"first/README.md": spec("id: shared\n" + SUPPORT),
                               "second/README.md": spec("id: shared\n" + SUPPORT)})
        with self.assertRaises(compat.CompatibilityError):
            compat.load_catalog(root)


class YamlSupportTests(unittest.TestCase):
    def parse(self, content):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, "attachments.md")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return compat.load_feature(path, SDKS)

    def test_reads_quoted_statuses_without_boolean_coercion(self):
        feature = self.parse(spec('''support:
  external-file-refs:
    go: "no"
    python: "yes"
  inline-base64:
    go: "partial"
    python: "n/a"
'''))
        self.assertEqual("attachments", feature.id)
        self.assertEqual("Attachments", feature.title)
        self.assertEqual(["external-file-refs", "inline-base64"], [row.id for row in feature.rows])
        self.assertEqual("External file refs", feature.rows[0].title)
        self.assertEqual([("no", "yes"), ("partial", "n/a")], [
            (row.cells["go"].status, row.cells["python"].status) for row in feature.rows
        ])

    def test_preserves_feature_metadata_separately_from_support(self):
        feature = self.parse(spec('''id: media-attachments
name: Media attachments
category: Multimodal
providers: [openai, anthropic]
custom:
  enabled: true
  details: null
''' + SUPPORT))
        self.assertEqual("media-attachments", feature.id)
        self.assertEqual("Media attachments", feature.title)
        self.assertEqual({"category": "Multimodal", "providers": ["openai", "anthropic"],
                          "custom": {"enabled": True, "details": None}}, feature.metadata)

    def test_returns_none_when_spec_has_no_support_section(self):
        self.assertIsNone(self.parse("# Attachments\n\nFeature details.\n"))

    def test_rejects_missing_extra_or_reordered_sdk_keys(self):
        entries = [
            '    go: "yes"\n',
            '    go: "yes"\n    python: "no"\n    ruby: "unknown"\n',
            '    python: "yes"\n    go: "no"\n',
        ]
        for entry in entries:
            with self.subTest(entry=entry), self.assertRaises(compat.CompatibilityError):
                self.parse(spec("support:\n  example:\n" + entry))

    def test_rejects_unquoted_boolean_status(self):
        with self.assertRaises(compat.CompatibilityError):
            self.parse(spec(SUPPORT.replace('"yes"', 'yes')))

    def test_rejects_unrecognized_status(self):
        with self.assertRaises(compat.CompatibilityError):
            self.parse(spec(SUPPORT.replace('"unknown"', '"maybe"')))

    def test_rejects_duplicate_keys_at_every_catalog_level(self):
        documents = [
            "id: first\nid: second\n" + SUPPORT,
            SUPPORT + '  example:\n    go: "no"\n    python: "no"\n',
            SUPPORT.replace('    go: "unknown"', '    go: "unknown"\n    go: "no"'),
        ]
        for document in documents:
            with self.subTest(document=document), self.assertRaises(compat.CompatibilityError):
                self.parse(spec(document))

    def test_rejects_invalid_yaml_and_nonmapping_catalog_shapes(self):
        for document in ('support: [\n', '- support\n', '!!set {support: null}\n',
                         'support: {}\n', 'support: [example]\n',
                         'support:\n  example: ["yes", "no"]\n'):
            with self.subTest(document=document), self.assertRaises(compat.CompatibilityError):
                self.parse(spec(document))

    def test_rejects_aliases_that_couple_independent_statuses(self):
        with self.assertRaises(compat.CompatibilityError):
            self.parse(spec('support:\n  example:\n    go: &state "unknown"\n    python: *state\n'))

    def test_rejects_python_object_construction(self):
        with self.assertRaises(compat.CompatibilityError):
            self.parse(spec('custom: !!python/object:builtins.object {}\n' + SUPPORT))

    def test_rejects_nonfinal_or_multiple_support_sections(self):
        for content in (spec() + "More prose.\n", spec() + spec(),
                        spec() + "```yaml\nother: value\n```\n", spec().removesuffix("```\n")):
            with self.subTest(content=content), self.assertRaises(compat.CompatibilityError):
                self.parse(content)

    def test_rejects_legacy_table_and_json_format(self):
        with self.assertRaises(compat.CompatibilityError):
            self.parse('''# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| example | Example | yes | no |

```json
{"id": "example"}
```
''')

    def test_updates_multiple_unknown_scalars_without_reformatting_yaml(self):
        text = '''# Café

Prose with unknown is not a status.

# SDK support

```yaml
name: "Metadata says unknown"
support:
  first: {go: 'unknown', python: "yes"} # preserve comment
  second:
    go: unknown
    python: "unknown" # pending
```
'''
        updated = compat.update_support_statuses(
            text, {("first", "go"): "partial", ("second", "python"): "no"}, "example.md",
        )
        self.assertEqual(text.replace("go: 'unknown'", 'go: "partial"')
                         .replace('python: "unknown"', 'python: "no"'), updated)
        feature = self.parse(updated)
        self.assertEqual([("partial", "yes"), ("unknown", "no")], [
            (row.cells["go"].status, row.cells["python"].status) for row in feature.rows
        ])

    def test_writer_rejects_yes_or_missing_cells_and_invalid_replacements(self):
        for changes in ({("example", "python"): "no"}, {("invented", "go"): "yes"},
                        {("example", "go"): "maybe"}):
            with self.subTest(changes=changes), self.assertRaises(compat.CompatibilityError):
                compat.update_support_statuses(spec(), changes, "example.md")


if __name__ == "__main__":
    unittest.main()
