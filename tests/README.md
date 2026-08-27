# Tests

Run everything:

```bash
python3 tests/run_all.py
```

Or a single suite:

```bash
python3 tests/test_fixes.py
python3 tests/test_behaviour.py
```

Both exit non-zero on failure. The only dependency is `discord.py` from
`requirements.txt` — there is no test framework to install, and no Discord
connection is made: `Bot.run` is stubbed out before `main.py` is imported, and
the module is loaded in a temporary working directory so the real `*.json` data
files are never touched.

## `test_fixes.py`

Structural assertions that the fixes are present and wired up: atomic writes,
`process_commands` dispatch, the swear-count determinism check (which re-runs
`main.py` under eight different `PYTHONHASHSEED` values in subprocesses and
requires identical counts), pagination, guild cleanup, `default_permissions` on
the admin commands, and the command-set fingerprint.

Where a property is behavioural rather than textual, it is asserted that way —
for example the non-blocking-save test makes the write take 300ms and checks the
event loop keeps ticking, rather than grepping for `to_thread`.

## `test_behaviour.py`

Drives `on_message` end to end against fake Discord objects and asserts on what
actually happens. Every test here corresponds to a bug that was real: the alert
embed exceeding Discord's 1024-character field cap, a failed DM burning the
cooldown, a concurrent `/deleteword` raising `KeyError` out of `on_message`, a
burst of messages defeating the cooldown, the swearboard caching an
interaction-bound message that expires after 15 minutes, a transient 429
unregistering the board or disabling the debounce, and a malformed stored entry
producing an un-recordable cooldown.

It also carries plain regression guards — a watcher is never alerted by their own
message, channel filters still gate alerts, `"class"` still does not count as a
swear — so a suite that silently stops exercising anything is visible.

## Adding a test

Both files use the same shape: a `check(name, fn)` / `run(fn, name)` helper that
records PASS/FAIL/ERR and prints a summary. Add a function, register it in the
list at the bottom, and keep the assertion message specific enough to say what
broke without opening the file.
