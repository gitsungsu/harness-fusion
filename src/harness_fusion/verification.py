"""Default Python test runner. Zero discovered or wholly skipped tests fail."""
import sys
import unittest


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    directory = args[0] if args else "tests"
    try:
        suite = unittest.defaultTestLoader.discover(directory, pattern="test*.py")
    except (ImportError, OSError) as exc:
        print(f"Test discovery failed: {exc}", file=sys.stderr)
        return 2
    if suite.countTestCases() == 0:
        print("No tests discovered. Completion is blocked.", file=sys.stderr)
        return 2
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun <= len(result.skipped):
        print("No non-skipped tests executed.", file=sys.stderr)
        return 2
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
