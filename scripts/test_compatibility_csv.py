import csv
import io
import unittest

import compatibility as compat
import compatibility_csv


class CompatibilityCsvTests(unittest.TestCase):
    def test_renders_one_row_per_capability_with_sdk_columns(self):
        catalog = compat.Catalog(
            sdks=[compat.Sdk("go", "Go"), compat.Sdk("python", "Python")],
            features=[
                compat.Feature(
                    path="features/attachments.md",
                    id="attachments",
                    title="Attachments",
                    metadata={
                        "category": "Multimodal",
                        "providers": ["openai", "anthropic"],
                    },
                    rows=[
                        compat.Row(
                            id="external-file-refs",
                            title="External file references",
                            cells={
                                "go": compat.Cell("partial"),
                                "python": compat.Cell("yes"),
                            },
                        )
                    ],
                )
            ],
        )

        reader = csv.DictReader(io.StringIO(compatibility_csv.render_csv(catalog)))
        rows = list(reader)

        self.assertEqual(["Category", "Feature", "Feature ID"], reader.fieldnames[:3])
        self.assertEqual(1, len(rows))
        self.assertEqual("attachments", rows[0]["Feature ID"])
        self.assertEqual("Multimodal", rows[0]["Category"])
        self.assertEqual("openai, anthropic", rows[0]["Providers"])
        self.assertEqual("partial", rows[0]["Go"])
        self.assertEqual("yes", rows[0]["Python"])
        self.assertEqual("features/attachments.md", rows[0]["Source"])


if __name__ == "__main__":
    unittest.main()
