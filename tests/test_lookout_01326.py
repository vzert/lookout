"""0.13.26: the two findings of round 3 of the adversarial review (codex break, Sonnet hold, 2026-10-18).

- `chrt` options that take a value (-T, -P, -D and their long forms) hid the command: `chrt -d -T 100000 -P 200000 0
  pkill -f claude` passed.
- `find … -exec sh -c "pkill -f claude" \\;` passed: the escaped (or quoted) `;` that ends -exec split the command before
  the find check could read it.
The user chose to fix these two and close the review here; nested quoted forms stay in p-4f3fe84d89.
Run: python3 -m unittest tests/test_lookout_01326.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_lookout_01318 import FrenoProcesosTest  # noqa: E402


class Ronda3Test(FrenoProcesosTest):
    def test_round_3_forms_are_denied(self):
        for cmd in ('chrt -d -T 100000 -P 200000 0 pkill -f claude', 'chrt --sched-runtime 1 -f 10 pkill claude',
                    'chrt -D 5 -d 0 pkill -f claude',
                    'find . -exec sh -c "pkill -f claude" \\;', "find . -exec sh -c 'pkill -f claude' ';'",
                    'find . -exec sh -c "pkill -f claude" ";"', 'find . -execdir pkill -f claude \\; -print'):
            self.assertEqual(self.handle(cmd)[0], "deny", cmd)

    def test_narrow_forms_still_pass(self):
        for cmd in ('chrt -d -T 100000 -P 200000 0 make', 'find . -name "*.pyc" -exec rm {} \\;',
                    "find . -exec sh -c 'echo {}' ';'", 'find . -type f -exec grep -l pkill {} +',
                    'echo "a;b"; ls'):
            self.assertEqual(self.handle(cmd)[0], None, cmd)


def load_tests(loader, tests, pattern):
    return unittest.TestSuite(Ronda3Test(n) for n in Ronda3Test.__dict__ if n.startswith("test_"))


if __name__ == "__main__":
    unittest.main()
