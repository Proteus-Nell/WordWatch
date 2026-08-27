"""Drive main.on_message end-to-end against fake Discord objects.

Proves the runtime behaviour of the alert-path fixes, not just their source shape.
"""
import asyncio, atexit, importlib.util, os, shutil, sys, tempfile, traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = []
def rec(status, name, msg=""): R.append((status, name, msg))

# ---------------- fake discord objects ----------------
class FakeUser:
    def __init__(self, uid, name="alice", fail=False):
        self.id, self.name, self.fail = uid, name, fail
        self.bot = False
        self.sent = []
        self.display_avatar = None
    async def send(self, *a, **k):
        if self.fail:
            raise RuntimeError("403 Forbidden: Cannot send messages to this user")
        self.sent.append(k.get("embed"))
    def __str__(self): return self.name

class FakeChannel:
    def __init__(self, cid, name="general"):
        self.id, self.name = cid, name
        self.sent = []
    async def send(self, *a, **k): self.sent.append(k.get("embed")); return FakeMsg(1, self)
    async def fetch_message(self, mid): return FakeMsg(mid, self)

class FakeMsg:
    def __init__(self, mid, ch): self.id, self.channel = mid, ch
    async def edit(self, **k): self.channel.sent.append(("edit", k.get("embed")))

class FakeGuild:
    def __init__(self, gid, name="Test Server"):
        self.id, self.name = gid, name
        self.channels = []
        self.threads = []      # real Guild exposes the active-thread cache
        self._members = {}
    def get_member(self, mid): return self._members.get(mid)
    async def fetch_member(self, mid): return self._members.get(mid)

class FakeMessage:
    def __init__(self, content, author, guild, channel):
        self.content, self.author, self.guild, self.channel = content, author, guild, channel
        self.jump_url = "https://discord.com/x/y/z"
        self.created_at = "2026-01-01 00:00:00"

# ---------------- load main.py ----------------
def load_main():
    import discord
    from discord.ext import commands
    commands.Bot.run = lambda self, *a, **k: None
    discord.Client.run = lambda self, *a, **k: None
    wd = tempfile.mkdtemp(prefix="ww-beh-"); atexit.register(shutil.rmtree, wd, True)
    for f in ("swear_words.txt", "help_str.py"):
        shutil.copy(os.path.join(REPO, f), wd)
    os.chdir(wd); os.environ["DISCORD_TOKEN"] = "dummy"
    sys.path.insert(0, wd)
    spec = importlib.util.spec_from_file_location("wwmain", os.path.join(REPO, "main.py"))
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m, wd

main, WD = load_main()
bot = main.bot
# on_message now calls process_commands (fix #2), which needs a real Message.
# Record the calls so we can assert it IS invoked, then no-op.
PROCESSED = []
async def _fake_process_commands(message):
    PROCESSED.append(message)
bot.process_commands = _fake_process_commands

BOT_USER = FakeUser(1, "wordwatch-bot")
type(bot).user = property(lambda self: BOT_USER)  # Client.user is read-only
GUILD, CHAN = FakeGuild(500), FakeChannel(600)
GUILD.channels = [CHAN]

def use_watcher(u):
    """Stub both lookup paths: baseline uses fetch_user, the fix uses get_user first."""
    bot.get_user = lambda uid: u
    async def _fetch(uid): return u
    bot.fetch_user = _fetch

def reset(words):
    bot.user_words.clear(); bot.user_cds.clear()
    bot.user_words.update(words)
    bot.user_cds["77"] = 0
    bot.swear_counts.clear(); bot.leaderboards.clear()

async def run(test, name):
    try:
        await test(); rec("PASS", name)
    except AssertionError as e: rec("FAIL", name, str(e))
    except Exception as e:      rec("ERR ", name, f"{type(e).__name__}: {e}")

# ---------------- tests ----------------
async def t_long_message():
    """#6: a >1024-char message must not blow up the alert embed."""
    reset({"77": {"500": {"lorem": {"last_alerted": 0, "channels": {}}}}})
    watcher = FakeUser(77)
    use_watcher(watcher)
    author = FakeUser(88, "bob")
    msg = FakeMessage("lorem " + ("x" * 3000), author, GUILD, CHAN)
    await main.on_message(msg)
    assert watcher.sent, "no alert delivered for a long message"
    embed = watcher.sent[0]
    for f in embed.fields:
        assert len(str(f.value)) <= 1024, f"field {f.name!r} is {len(str(f.value))} chars (Discord cap 1024)"

async def t_failed_dm_keeps_cooldown():
    """#6: a failed DM must NOT consume the cooldown."""
    reset({"77": {"500": {"lorem": {"last_alerted": 0, "channels": {}}}}})
    watcher = FakeUser(77, fail=True)
    use_watcher(watcher)
    msg = FakeMessage("lorem ipsum", FakeUser(88, "bob"), GUILD, CHAN)
    await main.on_message(msg)
    la = bot.user_words["77"]["500"]["lorem"].get("last_alerted", 0)
    assert la == 0, f"cooldown was consumed despite the DM failing (last_alerted={la})"

async def t_race_deleteword():
    """B: /deleteword landing during the DM round-trip must not kill on_message."""
    reset({"77": {"500": {"alpha": {"last_alerted": 0, "channels": {}},
                          "beta":  {"last_alerted": 0, "channels": {}}}}})
    watcher = FakeUser(77)
    async def slow_send(*a, **k):
        await asyncio.sleep(0.05)          # the real HTTP round-trip
        watcher.sent.append(k.get("embed"))
    watcher.send = slow_send
    use_watcher(watcher)
    async def racer():
        await asyncio.sleep(0.02)
        bot.user_words["77"]["500"].pop("beta", None)   # concurrent /deleteword
    msg = FakeMessage("alpha and beta", FakeUser(88, "bob"), GUILD, CHAN)
    await asyncio.gather(main.on_message(msg), racer())   # must not raise

async def t_old_schema():
    """F: watcher entries missing keys must not brick every message."""
    reset({"77": {"500": {"lorem": {}}}})               # no last_alerted, no channels
    watcher = FakeUser(77)
    use_watcher(watcher)
    msg = FakeMessage("lorem ipsum", FakeUser(88, "bob"), GUILD, CHAN)
    await main.on_message(msg)                          # must not raise

async def t_self_no_alert():
    """regression: the watcher must never be alerted by their own message."""
    reset({"77": {"500": {"lorem": {"last_alerted": 0, "channels": {}}}}})
    watcher = FakeUser(77)
    use_watcher(watcher)
    msg = FakeMessage("lorem ipsum", FakeUser(77, "alice"), GUILD, CHAN)
    await main.on_message(msg)
    assert not watcher.sent, "user was alerted by their own message"

async def t_channel_filter():
    """regression: channel filters must still gate alerts."""
    reset({"77": {"500": {"lorem": {"last_alerted": 0, "channels": {"<#999>": -1}}}}})
    watcher = FakeUser(77)
    use_watcher(watcher)
    msg = FakeMessage("lorem ipsum", FakeUser(88, "bob"), GUILD, CHAN)  # chan 600, filter 999
    await main.on_message(msg)
    assert not watcher.sent, "alert fired for a channel outside the filter"

async def t_leaderboard_debounce():
    """#5: rapid swearing must not edit the leaderboard message once per message."""
    reset({})
    board = FakeChannel(700, "board")
    edits = []
    class Msg:
        id = 42
        async def edit(self, **k): edits.append(k)
    async def fetch_message(mid): return Msg()
    board.fetch_message = fetch_message
    bot.get_channel = lambda cid: board
    bot.leaderboards["500"] = {"channel_id": "700", "message_id": "42"}
    bot.leaderboard_update_frequency = 1   # short window so the test is fast
    author = FakeUser(88, "bob")
    for _ in range(12):
        await main.on_message(FakeMessage("what the fuck", author, GUILD, CHAN))
    await asyncio.sleep(1.4)
    assert len(edits) <= 3, f"leaderboard edited {len(edits)}x for 12 messages (rate-limit risk)"
    assert bot.swear_counts.get("500", {}).get("88", 0) == 12, \
        f"counts wrong under debounce: {bot.swear_counts.get('500')}"

async def t_leaderboard_survives_transient():
    """#5: a transient edit error must NOT unregister the guild's leaderboard."""
    reset({})
    board = FakeChannel(700, "board")
    class Msg:
        id = 42
        async def edit(self, **k): raise RuntimeError("429 Too Many Requests")
    async def fetch_message(mid): return Msg()
    board.fetch_message = fetch_message
    bot.get_channel = lambda cid: board
    bot.leaderboards["500"] = {"channel_id": "700", "message_id": "42"}
    bot.leaderboard_update_frequency = 0
    await main.on_message(FakeMessage("what the fuck", FakeUser(88, "bob"), GUILD, CHAN))
    await asyncio.sleep(0.2)
    assert "500" in bot.leaderboards, \
        "a transient 429 permanently unregistered the leaderboard"

async def t_process_commands_called():
    """#2: prefix/mention command dispatch must still happen for every message."""
    reset({})
    bot.get_channel = lambda cid: None
    PROCESSED.clear()
    await main.on_message(FakeMessage("just chatting", FakeUser(88, "bob"), GUILD, CHAN))
    assert len(PROCESSED) == 1, f"process_commands called {len(PROCESSED)}x, expected 1"

async def t_swear_counts_correct():
    """regression: counting still works through on_message."""
    reset({})
    bot.get_channel = lambda cid: None
    await main.on_message(FakeMessage("what the fuck", FakeUser(88, "bob"), GUILD, CHAN))
    assert bot.swear_counts.get("500", {}).get("88") == 1, \
        f"expected 1 swear, got {bot.swear_counts.get('500')}"

async def t_burst_respects_cooldown():
    """F2: concurrent on_message tasks must not all pass a stale cooldown check."""
    reset({"77": {"500": {"deploy": {"last_alerted": 0, "channels": {}}}}})
    bot.user_cds["77"] = 900
    watcher = FakeUser(77)
    sent = []
    async def slow_send(*a, **k):
        await asyncio.sleep(0.05)          # the real DM round-trip
        sent.append(k.get("embed"))
    watcher.send = slow_send
    use_watcher(watcher)
    bot.get_channel = lambda cid: None
    msgs = [FakeMessage("deploy now", FakeUser(88, "bob"), GUILD, CHAN) for _ in range(5)]
    await asyncio.gather(*[main.on_message(m) for m in msgs])
    assert len(sent) == 1, f"burst of 5 produced {len(sent)} DMs; cooldown defeated"

async def t_transient_failure_rolls_back():
    """F2: a transient DM failure must put the cooldown back so the next one retries."""
    reset({"77": {"500": {"deploy": {"last_alerted": 7, "channels": {}}}}})
    bot.user_cds["77"] = 0
    watcher = FakeUser(77)
    async def boom(*a, **k): raise RuntimeError("503 Service Unavailable")
    watcher.send = boom
    use_watcher(watcher)
    bot.get_channel = lambda cid: None
    await main.on_message(FakeMessage("deploy", FakeUser(88, "bob"), GUILD, CHAN))
    got = bot.user_words["77"]["500"]["deploy"]["last_alerted"]
    assert got == 7, f"cooldown not rolled back after transient failure (last_alerted={got})"

async def t_swearboard_does_not_cache_interaction_msg():
    """F1: /swearboard must store ids only, never the interaction-bound message."""
    reset({})
    posted = FakeMsg(4242, CHAN)
    class Ctx:
        guild, channel, author = GUILD, CHAN, FakeUser(88, "bob")
        async def send(self, **k): return posted   # stands in for InteractionMessage
    await bot.get_command("swearboard").callback(Ctx())
    assert "500" in bot.leaderboards, "board was not registered"
    assert bot.leaderboard_messages.get("500") is None, \
        "swearboard cached the object ctx.send returned (expires after 15 min on the slash path)"

async def t_debounce_survives_transient_failure():
    """F5: a failed edit must not disable the debounce for every later swear."""
    reset({})
    attempts = []
    board = FakeChannel(700, "board")
    class Msg:
        id = 42
        async def edit(self, **k):
            attempts.append(1); raise RuntimeError("429 Too Many Requests")
    async def fetch_message(mid): return Msg()
    board.fetch_message = fetch_message
    bot.get_channel = lambda cid: board
    bot.leaderboards["500"] = {"channel_id": "700", "message_id": "42"}
    bot.leaderboard_update_frequency = 60      # long window
    author = FakeUser(88, "bob")
    for _ in range(6):
        await main.on_message(FakeMessage("what the fuck", author, GUILD, CHAN))
    await asyncio.sleep(0.1)
    assert len(attempts) <= 1, f"{len(attempts)} edit attempts after a failure; debounce disabled"
    assert "500" in bot.leaderboards, "transient failure unregistered the board"

async def t_malformed_entry_records_cooldown():
    """F8: a malformed stored entry must be repaired, not just shadowed."""
    reset({"77": {"500": {"deploy": 5}}})     # int instead of the entry dict
    bot.user_cds["77"] = 900
    watcher = FakeUser(77)
    use_watcher(watcher)
    bot.get_channel = lambda cid: None
    await main.on_message(FakeMessage("deploy", FakeUser(88, "bob"), GUILD, CHAN))
    entry = bot.user_words["77"]["500"]["deploy"]
    assert isinstance(entry, dict), f"entry not repaired: {entry!r}"
    assert entry.get("last_alerted"), "cooldown never recorded -> would DM on every message"

async def t_guild_remove_tolerates_bad_data():
    """F9: malformed persisted data must not abort the purge."""
    reset({"77": {"500": {"deploy": {"last_alerted": 0, "channels": {}}}}})
    bot.user_words["bad"] = []                # malformed, as load_json permits
    bot.swear_counts["500"] = {"88": 3}
    await main.on_guild_remove(GUILD)          # must not raise
    assert "500" not in bot.user_words["77"], "guild words not purged"
    assert "500" not in bot.swear_counts, "swear counts not purged"

async def t_filter_never_widened():
    """Pruning the last dead channel must not turn a narrow watch server-wide."""
    reset({"77": {"500": {"deploy": {"last_alerted": 0, "channels": {"<#999>": -1}}}}})
    member = FakeUser(77)
    main.ensure_valid_channels(member, GUILD, "deploy")   # #999 does not exist
    ch = bot.user_words["77"]["500"]["deploy"]["channels"]
    assert len(ch) > 0, "filter pruned to empty -> on_message would alert server-wide"

async def main_():
    await run(t_long_message,            "#6  long message -> fields within 1024")
    await run(t_failed_dm_keeps_cooldown,"#6  failed DM does not consume cooldown")
    await run(t_race_deleteword,         "B   /deleteword during DM does not kill on_message")
    await run(t_old_schema,              "F   old-schema watcher entry does not raise")
    await run(t_self_no_alert,           "reg self-message never alerts the watcher")
    await run(t_channel_filter,          "reg channel filter still gates alerts")
    await run(t_leaderboard_debounce,     "#5  leaderboard debounced under rapid swearing")
    await run(t_leaderboard_survives_transient, "#5  transient 429 does not unregister board")
    await run(t_swear_counts_correct,     "reg swear counting still works")
    await run(t_process_commands_called,  "#2  process_commands dispatched per message")
    await run(t_burst_respects_cooldown,  "F2  burst of 5 sends exactly 1 DM")
    await run(t_transient_failure_rolls_back, "F2  transient failure rolls cooldown back")
    await run(t_swearboard_does_not_cache_interaction_msg, "F1  swearboard stores ids, not the message")
    await run(t_debounce_survives_transient_failure, "F5  debounce survives a failed edit")
    await run(t_malformed_entry_records_cooldown, "F8  malformed entry repaired + cooldown set")
    await run(t_guild_remove_tolerates_bad_data, "F9  guild purge tolerates bad data")
    await run(t_filter_never_widened,     "--  pruning never widens a watch")
    w = max(len(n) for _, n, _ in R)
    for s, n, m in R: print(f"[{s}] {n:<{w}}  {m}")
    bad = sum(1 for s, _, _ in R if s != "PASS")
    print(f"\n{len(R)-bad}/{len(R)} passed")
    return bad

sys.exit(asyncio.run(main_()) and 1 or 0)
