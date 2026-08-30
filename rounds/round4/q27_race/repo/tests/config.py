"""Knobs the test runner flips before importing the test modules."""

# When true, interleaving-sensitive tests use the deterministic tracepoint
# gates instead of the "run it and hope" stress loop.  See run_tests.py --help.
BARRIER_MODE = False

# How aggressive the stress variants are.
STRESS_JOBS = 60
STRESS_KEYS = 4
STRESS_SPIN = 120
STRESS_YIELDS = 1
STRESS_SLOW_EVERY = 6
STRESS_INVALIDATE_GAP = 0.0002
STRESS_SAMPLE_GAP = 0.0002
