#!/usr/bin/env python3
"""Classify a Claude Code input box from `herdr agent read <pane> --source visible --format ansi`.

Pilot findings H3 and the grep/ugrep bug (docs/plan.md 5.1): text after the `❯` prompt can be
  - nothing                          -> "vacia"       (safe to deliver a prompt)
  - dim text (SGR 2, ESC[2m) only     -> "sugerencia"  (Claude Code's own suggestion; safe)
  - normal text                      -> "borrador"    (the user is typing: never write over it)
Parsed in Python on purpose: shell regexes over ANSI broke in the pilot.
Usage: inputbox.py < capture.ansi   -> prints the class.
"""
import re
import sys

SGR = re.compile(r"\x1b\[([0-9;]*)m")
OTHER_ESC = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07")
BORDER = "─"


def _visible_with_dim(segment, dim):
    """Yield (char, is_dim) for one line, tracking SGR dim state; returns final dim state."""
    out = []
    pos = 0
    for m in SGR.finditer(segment):
        for ch in OTHER_ESC.sub("", segment[pos:m.start()]):
            out.append((ch, dim))
        params = [p for p in m.group(1).split(";")] if m.group(1) else ["0"]
        i = 0
        while i < len(params):
            p = params[i]
            if p in ("38", "48") and i + 1 < len(params):
                i += 5 if params[i + 1] == "2" else 3  # skip truecolor / 256-color arguments
                continue
            if p in ("0", ""):
                dim = False
            elif p == "2":
                dim = True
            elif p == "22":
                dim = False
            i += 1
        pos = m.end()
    for ch in OTHER_ESC.sub("", segment[pos:]):
        out.append((ch, dim))
    return out, dim


def classify(ansi_text):
    return read_box(ansi_text)[0]


def read_box(ansi_text):
    """(class, text): class as classify(); text = what the box holds, whitespace collapsed
    (the dim suggestion included). deliver.py compares it with its own prompt (docs/plan.md 6.2.5)."""
    lines = ansi_text.replace("\r", "").split("\n")
    idx = None
    for i in range(len(lines) - 1, -1, -1):
        if "❯" in lines[i]:
            idx = i
            break
    if idx is None:
        return "desconocida", ""
    chars = []
    dim = False
    first = lines[idx]
    # SGR state before the prompt glyph still applies to what follows it
    before, _, after = first.partition("❯")
    _, dim = _visible_with_dim(before, dim)
    got, dim = _visible_with_dim(after, dim)
    chars.extend(got)
    for line in lines[idx + 1:]:
        plain = SGR.sub("", OTHER_ESC.sub("", line)).strip()
        if plain.startswith(BORDER) or not plain:
            break
        got, dim = _visible_with_dim(line, dim)
        chars.extend(got)
    shown = " ".join("".join(" " if c == "\xa0" else c for c, _ in chars).split())
    text = [(c, d) for c, d in chars if not c.isspace() and c != "\xa0"]
    if not text:
        return "vacia", ""
    if all(d for _, d in text):
        return "sugerencia", shown
    return "borrador", shown


def main():
    print(classify(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
