"""python -m services.sandbox

Part 6a: prints which fixture modules can be tested and which cannot, and why. Nothing is
executed. Running tests in the sandbox is part 6b.
"""

import sys
import tempfile
from pathlib import Path

from services.businessrule.run import pin_fixture
from services.evidence import SnapshotReader
from services.sandbox.testable import assess


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        pinned = pin_fixture(Path(tmp))
        found = assess(SnapshotReader.from_pinned(pinned), [f.path for f in pinned.tree.files])
    print(
        f"Testable functions: {len(found.targets)} "
        f"(skipped for their parameters or length: {found.skipped_functions})"
    )
    for t in found.targets:
        print(f"- {t.path}:{t.name}({', '.join(t.params)})")
    print(f"\nModules not tested: {len(found.untestable)}")
    for path, why in found.untestable:
        print(f"- {path}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
