#!/usr/bin/env python3
"""Scriptable fake `herdr` for the phase-2 unit tests (deliver.py, lote.py).

Reads $HERDR_STUB_CONF (JSON) and appends each call to $HERDR_STUB_LOG (one JSON list per line).
Conf keys:
  agent_get:   dict returned as {"result": {"agent": …}}
  agent_read:  text printed for `agent read` (ANSI capture)
  prompt_event: if set, `agent prompt` appends a `working` event with the prompt to this events.jsonl
               path, as the agent's UserPromptSubmit hook would ({"path", "session_id"})
  enter_event: same, for `agent send-keys … enter` (the stuck text gets submitted)
  read_after_prompt: new `agent_read` value once a prompt or Enter was sent
  version:     text printed for `--version` (default "herdr 0.9.1"); version_rc: its exit code
  status:      dict printed as JSON for `status --json` (default: client and server 0.9.1, compatible)
"""
import json
import os
import sys
import time

conf_path = os.environ["HERDR_STUB_CONF"]
with open(conf_path) as fh:
    conf = json.load(fh)
args = sys.argv[1:]
with open(os.environ["HERDR_STUB_LOG"], "a") as fh:
    fh.write(json.dumps(args) + "\n")


def emit(spec, prompt):
    line = json.dumps({"ts": time.time(), "session_id": spec["session_id"], "event": "working",
                       "prompt": prompt[:120], "hook": "UserPromptSubmit"}) + "\n"
    with open(spec["path"], "a") as fh:
        fh.write(line)


def after_send(prompt):
    if "read_after_prompt" in conf:
        conf["agent_read"] = conf["read_after_prompt"]
        with open(conf_path, "w") as fh:
            json.dump(conf, fh)


STATUS = {"client": {"version": "0.9.1"}, "server": {"status": "running", "running": True, "version": "0.9.1",
                                                    "compatible": True, "endpoint_compatible": True}}

if args[:1] == ["--version"]:
    sys.stdout.write(conf.get("version", "herdr 0.9.1") + "\n")
    sys.exit(conf.get("version_rc", 0))
elif args[:1] == ["status"]:
    print(json.dumps(conf.get("status", STATUS)))
elif args[:2] == ["agent", "get"]:
    print(json.dumps({"result": {"agent": conf.get("agent_get")}}))
elif args[:2] == ["agent", "read"]:
    sys.stdout.write(conf.get("agent_read", ""))
elif args[:2] == ["agent", "prompt"]:
    if conf.get("prompt_event"):
        emit(conf["prompt_event"], args[3])
    after_send(args[3])
    print(json.dumps({"result": {}}))
elif args[:2] == ["agent", "send-keys"] and args[-1] == "enter":
    if conf.get("enter_event"):
        emit(conf["enter_event"], conf["enter_event"]["prompt"])
    after_send("")
    print(json.dumps({"result": {}}))
else:
    print(json.dumps({"result": {}}))
