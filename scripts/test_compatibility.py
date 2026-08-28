import os
import tempfile
import unittest

import compatibility as compat


SDKS = [compat.Sdk(key="go", title="Go"), compat.Sdk(key="python", title="Python")]


def support_table() -> str:
    return """# Example

# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| example | Example capability | unknown | yes |
"""


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

    def test_load_catalog_returns_validated_repository_representation(self):
        root = self.make_repo({"example.md": support_table()})

        catalog = compat.load_catalog(root)

        self.assertEqual(["go", "python"], [sdk.key for sdk in catalog.sdks])
        self.assertEqual(["example"], [feature.id for feature in catalog.features])
        self.assertEqual("yes", catalog.features[0].rows[0].cells["python"].status)

    def test_load_catalog_rejects_duplicate_sdk_keys(self):
        root = self.make_repo(
            {"example.md": support_table()},
            '{"sdks":[{"key":"go","title":"Go"},{"key":"go","title":"Other Go"}]}',
        )

        with self.assertRaisesRegex(compat.CompatibilityError, "duplicate sdk key"):
            compat.load_catalog(root)

    def test_load_catalog_rejects_duplicate_sdk_titles(self):
        root = self.make_repo(
            {"example.md": support_table()},
            '{"sdks":[{"key":"go","title":"SDK"},{"key":"python","title":"SDK"}]}',
        )

        with self.assertRaisesRegex(compat.CompatibilityError, "duplicate sdk title"):
            compat.load_catalog(root)

    def test_load_catalog_requires_every_spec_to_have_a_support_table(self):
        root = self.make_repo({"example.md": "# Example\n\nNo table.\n"})

        with self.assertRaisesRegex(compat.CompatibilityError, "missing `# SDK support`"):
            compat.load_catalog(root)


class MarkdownSupportTableTests(unittest.TestCase):
    def write_spec(self, content: str, name: str = "attachments.md") -> str:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = os.path.join(tmp.name, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        return path

    def test_parses_final_sdk_support_table(self):
        path = self.write_spec(
            """# Attachments

Feature details.

# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| external-file-refs | External file references | partial | yes |
| inline-base64 | Inline base64 payloads | no | unknown |
"""
        )

        feature = compat.load_feature(path, SDKS)

        self.assertEqual("attachments", feature.id)
        self.assertEqual("Attachments", feature.title)
        self.assertEqual({}, feature.metadata)
        self.assertEqual(["external-file-refs", "inline-base64"], [row.id for row in feature.rows])
        self.assertEqual("partial", feature.rows[0].cells["go"].status)
        self.assertEqual("yes", feature.rows[0].cells["python"].status)

    def test_parses_optional_json_metadata_after_table(self):
        path = self.write_spec(
            '''# Attachments

# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| external-file-refs | External file references | partial | yes |

```json
{
  "id": "media-attachments",
  "name": "Media attachments",
  "category": "Multimodal",
  "providers": ["openai", "anthropic"]
}
```
'''
        )

        feature = compat.load_feature(path, SDKS)

        self.assertEqual("media-attachments", feature.id)
        self.assertEqual("Media attachments", feature.title)
        self.assertEqual("Multimodal", feature.metadata["category"])
        self.assertEqual(["openai", "anthropic"], feature.metadata["providers"])

    def test_returns_none_when_spec_has_no_support_section(self):
        path = self.write_spec("# Attachments\n\nFeature details.\n")

        self.assertIsNone(compat.load_feature(path, SDKS))

    def test_rejects_sdk_columns_that_do_not_match_canonical_list(self):
        path = self.write_spec(
            """# Attachments

# SDK support

| ID | Capability | Python | Go |
| --- | --- | --- | --- |
| external-file-refs | External file references | yes | yes |
"""
        )

        with self.assertRaisesRegex(compat.CompatibilityError, "SDK columns"):
            compat.load_feature(path, SDKS)

    def test_rejects_invalid_status(self):
        path = self.write_spec(
            """# Attachments

# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| external-file-refs | External file references | maybe | yes |
"""
        )

        with self.assertRaisesRegex(compat.CompatibilityError, "bad status"):
            compat.load_feature(path, SDKS)

    def test_rejects_content_after_support_table(self):
        path = self.write_spec(
            """# Attachments

# SDK support

| ID | Capability | Go | Python |
| --- | --- | --- | --- |
| external-file-refs | External file references | yes | yes |

More prose.
"""
        )

        with self.assertRaisesRegex(compat.CompatibilityError, "final section"):
            compat.load_feature(path, SDKS)


if __name__ == "__main__":
    unittest.main()
