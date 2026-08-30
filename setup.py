from pathlib import Path
import shutil

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


class build_py(_build_py):
    """Bundle the auditable benchmark tree into installed wheels."""

    def run(self):
        super().run()
        source = Path(__file__).parent / "rounds"
        target = Path(self.build_lib) / "pattern0_bench" / "rounds"
        shutil.copytree(
            source, target, dirs_exist_ok=True,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".DS_Store", "out", ".codex_omlx",
                ".v4_baselines.json",
            ),
        )


setup(cmdclass={"build_py": build_py})
