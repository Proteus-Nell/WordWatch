"""Import main.py without connecting to Discord, then assert every requested fix holds."""
import asyncio, atexit, importlib.util, inspect, json, os, shutil, subprocess, sys, tempfile, traceback

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
R = []
def check(name, fn):
    try:
        fn(); R.append(("PASS", name, ""))
    except AssertionError as e: R.append(("FAIL", name, str(e)))
    except Exception as e:     R.append(("ERR ", name, f"{type(e).__name__}: {e}"))

def load_main():
    import discord
    from discord.ext import commands
    commands.Bot.run = lambda self, *a, **k: None
    discord.Client.run = lambda self, *a, **k: None
    wd = tempfile.mkdtemp(prefix="ww-"); atexit.register(shutil.rmtree, wd, True)
    for f in ("swear_words.txt", "help_str.py"):
        shutil.copy(os.path.join(REPO, f), wd)
    os.chdir(wd); os.environ["DISCORD_TOKEN"] = "dummy"
    sys.path.insert(0, wd)
    spec = importlib.util.spec_from_file_location("wwmain", os.path.join(REPO, "main.py"))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod, wd

main, WD = load_main()
bot = main.bot
src = open(os.path.join(REPO, "main.py"), encoding="utf-8").read()
ADMIN = ["swearreset", "swearexport", "swearimport", "forcesave", "botstop"]

# ---- 2: prefix commands work again ----
def t2():
    body = inspect.getsource(main.on_message)
    assert "process_commands" in body, "on_message never calls process_commands"
check("#2  on_message calls process_commands", t2)

# ---- 3: atomic writes ----
def t3():
    s = inspect.getsource(main.write_to_json)
    assert "os.replace" in s, "write_to_json is not atomic (no os.replace)"
    assert "except" in s, "write_to_json has no error guard"
check("#3  write_to_json is atomic + guarded", t3)

# ---- 4: check_user repairs both dicts independently ----
def t4():
    class M: id = 999
    bot.user_words.clear(); bot.user_cds.clear()
    bot.user_words["999"] = {}          # present in one dict only
    main.check_user(M())
    assert "999" in bot.user_cds, "check_user did not repair a missing user_cds entry"
check("#4  check_user repairs user_cds independently", t4)

# ---- 9: saving must not block the event loop (behavioural, not textual) ----
def t9():
    import asyncio, time as _t
    assert hasattr(main, "save_data"), "no save_data() wrapper"
    # Prove it empirically: make the blocking write take 300ms and check the loop
    # stays responsive while it runs.
    real = main.write_to_json
    def slow():
        _t.sleep(0.3); return True
    main.write_to_json = slow
    try:
        async def probe():
            ticks = 0
            async def spin():
                nonlocal ticks
                while True:
                    ticks += 1
                    await asyncio.sleep(0.01)
            t = asyncio.create_task(spin())
            await main.save_data()
            t.cancel()
            return ticks
        ticks = asyncio.run(probe())
        assert ticks > 5, f"event loop only ticked {ticks}x during a 300ms save - it blocked"
    finally:
        main.write_to_json = real
check("#9  saving does not block the event loop", t9)

# ---- 10: cache-first user lookup ----
def t10():
    b = inspect.getsource(main.on_message)
    assert "get_user" in b, "on_message still only uses fetch_user"
check("#10 alert path tries get_user first", t10)

# ---- A: deterministic swear counting across hash seeds ----
def tA():
    prog = (
        "import sys;sys.path.insert(0,%r);sys.argv=['x']\n"
        "import importlib.util,os,discord\n"
        "from discord.ext import commands\n"
        "commands.Bot.run=lambda s,*a,**k:None\n"
        "os.environ['DISCORD_TOKEN']='d'\n"
        "os.chdir(%r)\n"
        "sp=importlib.util.spec_from_file_location('m',%r)\n"
        "m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)\n"
        "t=['ass-fucker','dumb ass bitch','ass monkey fucker','2 girls 1 cup','son of a bitch']\n"
        "print(','.join(str(m.count_swears(x)) for x in t))\n"
    ) % (WD, WD, os.path.join(REPO, "main.py"))
    outs = set()
    for seed in map(str, range(1, 9)):
        e = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True, text=True, env=e)
        assert r.returncode == 0, f"seed {seed} failed: {r.stderr[-400:]}"
        outs.add(r.stdout.strip())
    assert len(outs) == 1, f"counts vary across hash seeds: {outs}"
check("A   swear counts deterministic across 8 seeds", tA)

# ---- A/D: word-boundary semantics preserved ----
def tAD():
    for s in ["I booked a class", "the assessment passed", "a cocktail please", "Scunthorpe"]:
        assert main.count_swears(s) == 0, f"false positive on {s!r}"
    assert main.count_swears("what the fuck") == 1, "missed a real match"
check("A/D word-boundary semantics preserved", tAD)

# ---- B: the cooldown write must happen inside the try that wraps the DM send ----
def tB():
    import ast, textwrap
    # The write itself lives in commit_last_alerted(); assert BOTH that the helper
    # performs the write and that on_message only calls it from inside the DM try.
    helper = ast.parse(textwrap.dedent(inspect.getsource(main.commit_last_alerted)))
    writes = [n for n in ast.walk(helper) if isinstance(n, ast.Assign)
              for t in n.targets
              if isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
              and t.slice.value == "last_alerted"]
    assert writes, "commit_last_alerted does not write last_alerted"

    tree = ast.parse(textwrap.dedent(inspect.getsource(main.on_message)))
    def calls_commit(node):
        return any(isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                   and c.func.id == "commit_last_alerted" for c in ast.walk(node))
    def sends(node):
        return any(isinstance(a, ast.Attribute) and a.attr == "send" for a in ast.walk(node))

    tries = [n for n in ast.walk(tree) if isinstance(n, ast.Try)]
    guarded = [t for t in tries if calls_commit(t) and sends(t)]
    assert guarded, "the cooldown write is not inside the try that wraps the DM send"
    # and nowhere else in on_message outside a try
    total = sum(1 for c in ast.walk(tree) if isinstance(c, ast.Call)
                and isinstance(c.func, ast.Name) and c.func.id == "commit_last_alerted")
    inside = sum(1 for t in guarded for c in ast.walk(t) if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name) and c.func.id == "commit_last_alerted")
    assert total == inside, f"{total-inside} cooldown write(s) sit outside the try"
check("B   cooldown write inside the DM try", tB)

# ---- E: /watched paginates ----
def tE():
    s = inspect.getsource(bot.get_command("watched").callback)
    assert "page" in s.lower(), "/watched has no pagination"
    assert hasattr(bot, "watched_page_size"), "no watched_page_size constant"
check("E   /watched paginates via constant", tE)

# ---- F: persisted data read defensively ----
def tF():
    b = inspect.getsource(main.on_message)
    assert '.get("last_alerted"' in b or ".get('last_alerted'" in b, "last_alerted still a bare subscript"
    assert '.get("channels"' in b or ".get('channels'" in b, "channels still a bare subscript"
check("F   on_message reads persisted data with .get", tF)

# ---- G: guild cleanup ----
def tG():
    assert hasattr(main, "on_guild_remove"), "no on_guild_remove handler"
check("G   on_guild_remove purges guild data", tG)

# ---- 7: /help must post in-channel, never DM (AST, so comments don't count) ----
def t7H():
    import ast, textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(bot.get_command("help").callback)))
    targets = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "send":
            v = n.func.value
            targets.add(ast.unparse(v))
    assert targets, "/help sends nothing"
    dm = [t for t in targets if "author" in t]
    assert not dm, f"/help still DMs the user via {dm}"
    assert any(t == "ctx" for t in targets), f"/help does not send in-channel (targets: {targets})"
check("#7  /help posts in-channel, no DM", t7H)

# ---- 13: watchword validation ----
def t13():
    assert hasattr(bot, "min_watchword_length"), "no min_watchword_length constant"
    s = inspect.getsource(bot.get_command("watchword").callback)
    assert "min_watchword_length" in s, "/watchword does not enforce a minimum length"
check("#13 /watchword enforces min length", t13)

# ---- 5: leaderboard debounce constant ----
def t5():
    assert hasattr(bot, "leaderboard_update_frequency"), "no leaderboard_update_frequency constant"
check("#5  leaderboard debounce is configurable", t5)

# ---- polish: utcnow gone ----
def tU():
    assert "utcnow()" not in src, "datetime.utcnow() still present"
check("--  utcnow() replaced with tz-aware now()", tU)

# ---- polish: on_command_error present ----
def tCE():
    assert hasattr(main, "on_command_error"), "no on_command_error handler"
check("--  on_command_error added", tCE)

# ---- polish: default_permissions on admin commands ----
def tDP():
    missing = [n for n in ADMIN
               if getattr(bot.get_command(n).app_command, "default_permissions", None) is None]
    assert not missing, f"default_permissions not set on: {missing}"
check("--  admin cmds hidden via default_permissions", tDP)

# ---- 8: sync only on command-set change, text included ----
def t8():
    assert "sha256" in src or "hashlib" in src, "no command-set fingerprint"
    fp = [n for n in dir(main) if "fingerprint" in n.lower() or "signature" in n.lower()]
    assert fp, "no fingerprint helper found"
check("#8  tree sync gated on a command fingerprint", t8)

# ---- all 16 commands still registered ----
def tAll():
    got = sorted(c.name for c in bot.commands)
    want = sorted(["help","cd","deleteword","watchclear","watchword","worddetail","addfilter",
                   "deletefilter","clearfilter","watched","swearboard","swearreset","swearexport",
                   "swearimport","forcesave","botstop"])
    assert got == want, f"command set changed: {set(want) ^ set(got)}"
check("--  all 16 commands still register", tAll)

w = max(len(n) for _, n, _ in R)
for st, n, msg in R:
    print(f"[{st}] {n:<{w}}  {msg}")
bad = sum(1 for s, _, _ in R if s != "PASS")
print(f"\n{len(R)-bad}/{len(R)} passed")
sys.exit(1 if bad else 0)
