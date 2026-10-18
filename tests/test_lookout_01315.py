"""0.13.15: a retry recognizes a typed /command already in the transcript.

A retry whose `working` event was lost reads the transcript (deliver.count_in_transcript). Claude Code does not keep a
typed /command as typed: it keeps a block of tags, `<command-name>/x</command-name>` plus `<command-args>…</command-args>`
(absent when the command had no arguments) and often `<command-message>x</command-message>`. Measured 2026-10-17 over
the transcripts in ~/.claude/projects (about 5100 files; the counts move as sessions are written and removed): both tag
orders occur (name first with indented lines, and message first), the args can be empty or missing and can span lines. So a relief typed with --goalspec
(`/goalspec:goalspec <trigger>`) whose event was lost was typed a second time.
Run: python3 -m unittest tests/test_lookout_01315.py
"""
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_lookout_f2 as f2  # noqa: E402

import deliver  # noqa: E402
import relevo  # noqa: E402

ARGS = relevo.TRIGGER.format(id="p-1")
TYPED = "/goalspec:goalspec " + ARGS


def message_first(name, args=None):
    """The shape of the real /goalspec:goalspec line (24bb9a7a-….jsonl, 2026-10)."""
    out = "<command-message>%s</command-message>\n<command-name>/%s</command-name>" % (name, name)
    return out if args is None else out + "\n<command-args>%s</command-args>" % args


def name_first(name, args=None):
    """The shape of /rename and /reload-plugins lines (name first, the others indented)."""
    out = "<command-name>/%s</command-name>\n            <command-message>%s</command-message>" % (name, name)
    return out if args is None else out + "\n            <command-args>%s</command-args>" % args


class RetryTest(f2.StubCase):
    """Real deliver.deliver against the herdr stub: the first attempt gets no UserPromptSubmit (no event at all), then
    the transcript carries the block; the retry must not type it again."""
    def retry(self, *lines):
        code, msg = deliver.deliver(self.pid, self.entry, "k1", TYPED, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 6, msg)
        with open(self.events) as fh:
            self.assertEqual(fh.read(), "")  # the transcript is the only source the retry can read
        self.transcript(*lines)
        return deliver.deliver(self.pid, self.entry, "k1", TYPED, 0.2, projects_dir=self.projects)

    def test_the_block_message_first_is_the_delivered_command(self):
        code, msg = self.retry("hola", message_first("goalspec:goalspec", ARGS))
        self.assertEqual(code, 0, msg)
        self.assertIn("sí llegó", msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_the_block_name_first_is_the_delivered_command(self):
        code, msg = self.retry(name_first("goalspec:goalspec", ARGS))
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 1)

    def test_another_command_with_the_same_args_is_typed_again(self):
        code, msg = self.retry(message_first("goalspec:interview", ARGS))
        self.assertNotEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 2)

    def test_the_same_command_with_other_args_is_typed_again(self):
        code, msg = self.retry(message_first("goalspec:goalspec", "otra tarea"))
        self.assertNotEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 2)

    def test_the_same_command_typed_before_this_delivery_is_not_this_one(self):
        # codex r1: `previas` was recorded only for «! cmd», so an identical earlier /command confirmed the retry
        self.transcript(message_first("goalspec:goalspec", ARGS))
        code, msg = deliver.deliver(self.pid, self.entry, "k1", TYPED, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 6, msg)
        code, msg = deliver.deliver(self.pid, self.entry, "k1", TYPED, 0.2, projects_dir=self.projects)
        self.assertNotEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 2)
        self.transcript(message_first("goalspec:goalspec", ARGS), message_first("goalspec:goalspec", ARGS))
        code, msg = deliver.deliver(self.pid, self.entry, "k1", TYPED, 0.2, projects_dir=self.projects)
        self.assertEqual(code, 0, msg)
        self.assertEqual(len(self.calls(["agent", "prompt"])), 2)


class CountTest(f2.StubCase):
    def count(self, text, *lines):
        self.transcript(*lines)
        return deliver.count_in_transcript(self.sid, text, self.projects)

    def test_args_over_several_lines(self):
        self.assertEqual(self.count("/x uno\ndos", message_first("x", "uno\ndos")), 1)

    def test_a_command_without_args_both_ways(self):
        self.assertEqual(self.count("/checkpoint-3t", message_first("checkpoint-3t"),
                                    name_first("checkpoint-3t", "")), 2)

    def test_tags_inside_an_ordinary_message_are_not_the_command(self):
        pasted = "mira esto:\n" + message_first("goalspec:goalspec", ARGS)
        self.assertEqual(self.count(TYPED, pasted), 0)

    def test_args_that_contain_the_closing_tag(self):
        # codex r1: Claude Code does not escape the args; <command-args> is last in every real block that has it
        args = "di </command-args> y sigue"
        self.assertEqual(self.count("/x " + args, message_first("x", args), name_first("x", args)), 2)

    def test_a_malformed_block_is_read_in_linear_time(self):
        # codex r1: 31 KB of repeated name tags and an unclosed args tag took more than 2 s with the first pattern
        bad = "<command-name>/x</command-name>" * 1000 + "<command-args>x"
        start = time.monotonic()
        self.assertEqual(deliver.as_typed(bad), bad)
        self.assertEqual(deliver.as_typed("<command-name>" * 1000 + "x"), "<command-name>" * 1000 + "x")
        self.assertLess(time.monotonic() - start, 0.5)

    def test_a_plain_text_still_counts_as_before(self):
        self.assertEqual(self.count(ARGS, ARGS, message_first("goalspec:goalspec", ARGS)), 1)


if __name__ == "__main__":
    unittest.main()
