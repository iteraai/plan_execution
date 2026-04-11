from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import install


class InstallSkillTests(unittest.TestCase):
    def test_install_skill_copies_skill_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_dir = temp_path / "source"
            destination_dir = temp_path / "destination"
            (source_dir / "scripts").mkdir(parents=True)
            (source_dir / "SKILL.md").write_text("skill")
            (source_dir / "scripts" / "execute.py").write_text("print('ok')\n")

            installed_path = install.install_skill(
                source_dir=source_dir, destination_dir=destination_dir
            )

            self.assertEqual(installed_path, destination_dir)
            self.assertEqual((destination_dir / "SKILL.md").read_text(), "skill")
            self.assertEqual(
                (destination_dir / "scripts" / "execute.py").read_text(),
                "print('ok')\n",
            )


if __name__ == "__main__":
    unittest.main()
