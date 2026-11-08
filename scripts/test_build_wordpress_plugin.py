"""Packaging contract: deterministic bytes, canonical assets, installable layout."""
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from build_wordpress_plugin import FILES, build


class PluginBuildTest(unittest.TestCase):
    def test_reproducible_and_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / name for name in ("one.zip", "two.zip"))
            build(first)
            build(second)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with ZipFile(first) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {"woo-rag-assistant/" + name for name in FILES})
                for name, source in FILES.items():
                    self.assertEqual(archive.read("woo-rag-assistant/" + name), source.read_bytes())


if __name__ == "__main__":
    unittest.main()
