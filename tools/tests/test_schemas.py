from __future__ import annotations

import json
import unittest
from pathlib import Path


SCHEMA_DIRECTORY = Path(__file__).parents[1] / "schemas"


class SchemaTests(unittest.TestCase):
    def test_every_schema_is_valid_json_with_v1_identifier(self) -> None:
        schema_paths = sorted(SCHEMA_DIRECTORY.glob("*.schema.json"))
        self.assertGreaterEqual(len(schema_paths), 3)
        for path in schema_paths:
            with self.subTest(path=path.name):
                schema = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertIn("/evidence/v1/", schema["$id"])
                self.assertEqual(schema["type"], "object")
                self.assertIn("schema_version", schema["required"])
                self.assertEqual(
                    schema["properties"]["schema_version"]["const"],
                    "vibescreen.evidence/v1",
                )


if __name__ == "__main__":
    unittest.main()
