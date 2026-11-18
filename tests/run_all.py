"""Single-command test runner for IncuBrix Engineering Assessment 2.

Runs unit, integration, worked example, hard cases, level verification,
and the complete 45-scenario test suite with zero external API keys needed.
"""

from __future__ import annotations
import sys
import time
import unittest


def run_all_tests():
    start_time = time.time()
    print("=" * 70)
    print(" INCUBRIX PROMPT-BASED VIDEO EDITING ENGINE - TEST SUITE RUNNER")
    print(" Mode: Offline / Self-Contained / Zero API Keys Required")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Discover and add all test modules
    test_modules = [
        "tests.test_must_haves",
        "tests.test_worked_example",
        "tests.test_hard_cases",
        "tests.test_levels",
        "tests.test_integration",
        "tests.test_scenarios_suite"
    ]

    for mod in test_modules:
        try:
            suite.addTests(loader.loadTestsFromName(mod))
            print(f" Loaded test suite: {mod}")
        except Exception as e:
            print(f" Error loading {mod}: {e}", file=sys.stderr)

    print("-" * 70)
    print(f"Executing {suite.countTestCases()} automated test cases across 6 suites...")
    print("-" * 70)

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    elapsed = time.time() - start_time

    print("=" * 70)
    print(" TEST EXECUTION SUMMARY")
    print(f" Total Tests Run : {result.testsRun}")
    print(f" Passed          : {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f" Failures        : {len(result.failures)}")
    print(f" Errors          : {len(result.errors)}")
    print(f" Total Time      : {elapsed:.2f} seconds")
    print("=" * 70)

    if result.wasSuccessful():
        print(" ALL INCUBRIX TESTS PASSED (100% SUCCESS RATE)")
        return 0
    else:
        print(" SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())

