import discord
from discord.ext import commands
import calendar
import time
import datetime
import asyncio
import hashlib
import json
import math
import os
import re
import io
import traceback

import help_str


# ---------------------------------------------------------------------------
# Environment loading
# ---------------------------------------------------------------------------
def load_env(filepath: str = ".env") -> None:
    """Loads KEY=VALUE pairs from a dotenv file into os.environ.

    The real process environment always wins: a key is only taken from the file
    when it is not already present in os.environ. This makes `DISCORD_TOKEN=xxx
    python main.py`, systemd/Docker `Environment=` entries and CI secrets behave
    the way operators expect, instead of being silently clobbered by a stale
    committed-next-to-the-code .env file.

    Tolerated syntax: blank lines, `#` comment lines, an optional `export `
    prefix, and values wrapped in a matching pair of single or double quotes.
    """
    if not os.path.isfile(filepath):
        return
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export ") or line.startswith("export\t"):
                    line = line[len("export"):].lstrip()
                if "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                if not key or key in os.environ:
                    # Already set for real: the process environment wins.
                    continue
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                    val = val[1:-1]
                os.environ[key] = val
    except OSError as e:
        print("WARNING: could not read {} ({}); using the process environment only.".format(filepath, e))


load_env()


# ---------------------------------------------------------------------------
# Typed environment readers
#
# Every one of these falls back to the documented default and prints a warning
# when the value is unusable. Configuration mistakes must never stop the bot
# from booting.
# ---------------------------------------------------------------------------
def _env_str(name: str, default: str) -> str:
    """Reads a string setting; blank/whitespace-only values fall back to the default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    raw = raw.strip()
    if not raw:
        print("WARNING: {} is set but empty; using default {!r}.".format(name, default))
        return default
    return raw


def _env_int(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    """Reads an integer setting, clamped to [minimum, maximum] when given."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except ValueError:
        print("WARNING: {}={!r} is not a whole number; using default {}.".format(name, raw, default))
        return default
    if minimum is not None and value < minimum:
        print("WARNING: {}={} is below the minimum of {}; using {}.".format(name, value, minimum, minimum))
        return minimum
    if maximum is not None and value > maximum:
        print("WARNING: {}={} is above the maximum of {}; using {}.".format(name, value, maximum, maximum))
        return maximum
    return value


def _env_float(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    """Reads a floating-point setting, clamped to [minimum, maximum] when given."""
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw.strip())
    except ValueError:
        print("WARNING: {}={!r} is not a number; using default {}.".format(name, raw, default))
        return default
    if not math.isfinite(value):
        # Catches NaN and +/-inf. int(inf * 60) raises OverflowError, which would
        # kill the boot -- exactly what these readers exist to prevent.
        print("WARNING: {}={!r} is not a finite number; using default {}.".format(name, raw, default))
        return default
    if minimum is not None and value < minimum:
        print("WARNING: {}={} is below the minimum of {}; using {}.".format(name, value, minimum, minimum))
        return minimum
    if maximum is not None and value > maximum:
        print("WARNING: {}={} is above the maximum of {}; using {}.".format(name, value, maximum, maximum))
        return maximum
    return value


# ---------------------------------------------------------------------------
# Configuration
#
# Everything tunable lives here and can be overridden from the environment or
# from .env (see .env.example). The literal in each call is the default that
# ships with the bot.
# ---------------------------------------------------------------------------

# Required. Bot token from the Discord Developer Portal.
DISCORD_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()
if not DISCORD_TOKEN:
    raise SystemExit("ERROR: DISCORD_TOKEN not set. Copy .env.example to .env and add your token.")

# Data files. Relative paths resolve against the process working directory.
USER_WORDS_FILE = _env_str("WORDWATCH_USER_WORDS_FILE", "userwords.json")
USER_CDS_FILE = _env_str("WORDWATCH_USER_CDS_FILE", "usercds.json")
SWEAR_COUNTS_FILE = _env_str("WORDWATCH_SWEAR_COUNTS_FILE", "swearcounts.json")
LEADERBOARDS_FILE = _env_str("WORDWATCH_LEADERBOARDS_FILE", "leaderboards.json")

# Newline-separated list of tracked swear words.
SWEAR_WORDS_FILE = _env_str("WORDWATCH_SWEAR_WORDS_FILE", "swear_words.txt")

# Cached fingerprint of the slash-command set, used to skip redundant syncs.
SYNC_STATE_FILE = _env_str("WORDWATCH_SYNC_STATE_FILE", ".command_sync.json")

# Thumbnail shown on /help and on watched-word alerts.
ALERT_THUMBNAIL_URL = _env_str(
    "WORDWATCH_ALERT_THUMBNAIL_URL",
    "https://raw.githubusercontent.com/pixeltopic/WordWatch/master/alertimage.gif")

# Seconds between periodic autosaves of all bot data.
SAVE_FREQUENCY = _env_int("WORDWATCH_SAVE_FREQUENCY", 900, minimum=1)

# Seconds between debounced swear-count saves. 0 saves on every swear.
SWEAR_SAVE_FREQUENCY = _env_int("WORDWATCH_SWEAR_SAVE_FREQUENCY", 30, minimum=0)

# Minimum seconds between edits of a server's live swearboard message.
# Discord rate-limits message edits, so this keeps a busy server from
# burning its budget (and getting the bot 429'd) on leaderboard updates.
LEADERBOARD_UPDATE_FREQUENCY = _env_int("WORDWATCH_LEADERBOARD_UPDATE_FREQUENCY", 30, minimum=0)

# Default per-user alert cooldown, in minutes, for users who never ran /cd.
DEFAULT_COOLDOWN_MINUTES = _env_float("WORDWATCH_DEFAULT_COOLDOWN_MINUTES", 15.0, minimum=0.0)
DEFAULT_COOLDOWN_SECONDS = int(DEFAULT_COOLDOWN_MINUTES * 60)

# Shortest word /watchword will accept. Very short words match constantly.
MIN_WATCHWORD_LENGTH = _env_int("WORDWATCH_MIN_WATCHWORD_LENGTH", 3, minimum=1)

# Truncation limit for the "Content" field of an alert embed. Discord rejects
# embed field values longer than 1024 characters, so that is the hard ceiling.
ALERT_CONTENT_MAX_CHARS = _env_int("WORDWATCH_ALERT_CONTENT_MAX_CHARS", 1000, minimum=1, maximum=1024)

# Words listed per page by /watched.
WATCHED_PAGE_SIZE = _env_int("WORDWATCH_WATCHED_PAGE_SIZE", 50, minimum=1)

# Largest accepted /swearimport attachment, in bytes.
MAX_IMPORT_BYTES = _env_int("WORDWATCH_MAX_IMPORT_BYTES", 1_000_000, minimum=1)

# Set to 1 to force a global command sync regardless of the cached fingerprint.
FORCE_SYNC = _env_str("WORDWATCH_FORCE_SYNC", "0").lower() in ("1", "true", "yes", "on")




# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True


class WordWatchBot(commands.Bot):
    """commands.Bot subclass so setup_hook is a real override, not a monkey-patch.

    discord.Client awaits setup_hook() exactly once, inside login(), after the loop
    and HTTP session exist but before the first CONNECT. That makes it the correct
    home for one-time startup work. on_ready is NOT such a place - it re-fires on
    every RESUME/reconnect.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data_loaded = False
        # Strong reference: loop.create_task only keeps a weak one, so without
        # this the periodic save task can be garbage collected mid-flight.
        self._save_task = None

    async def close(self) -> None:
        """Flushes unsaved state before disconnecting.

        Without this, anything changed since the last periodic save is lost on
        SIGTERM/Ctrl-C, because save_json's sleep is simply cancelled.
        """
        try:
            if bot.swear_dirty or bot.data_dirty:
                await save_data()
        except Exception as e:
            print("Could not save during shutdown: {!r}".format(e))
        await super().close()

    async def setup_hook(self) -> None:
        load_data()
        if self._save_task is None or self._save_task.done():
            self._save_task = self.loop.create_task(save_json(), name="wordwatch-periodic-save")
        await sync_commands_if_changed()


bot = WordWatchBot(command_prefix=commands.when_mentioned,
                   description='WordWatch Bot', intents=intents)
bot.remove_command('help')  # removes default help command!

# ---------------------------------------------------------------------------
# Swear word list
# ---------------------------------------------------------------------------
DEFAULT_SWEAR_WORDS = {"ass", "bitch", "crap", "damn", "fuck", "hell", "shit"}


def load_swear_words(filepath: str = SWEAR_WORDS_FILE) -> set:
    """Reads the tracked swear words, falling back to a small built-in list."""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            words = {line.strip().lower() for line in f if line.strip()}
    except FileNotFoundError:
        print("WARNING: {} not found; falling back to the built-in swear list.".format(filepath))
        return set(DEFAULT_SWEAR_WORDS)
    except (OSError, UnicodeDecodeError) as e:
        print("WARNING: could not read {} ({}); falling back to the built-in list.".format(filepath, e))
        return set(DEFAULT_SWEAR_WORDS)
    if not words:
        print("WARNING: {} is empty; falling back to the built-in swear list.".format(filepath))
        return set(DEFAULT_SWEAR_WORDS)
    return words


SWEAR_WORDS = load_swear_words()

# Sentinel used as the value in channel dicts to mimic a set. Not configurable.
bot.static = -1

# ---------------------------------------------------------------------------
# Mutable runtime state
# ---------------------------------------------------------------------------
bot.user_words = dict()
bot.user_cds = dict()
bot.swear_counts = dict()
bot.leaderboards = dict()
bot.swear_dirty = False               # True when swear_counts holds unsaved changes
bot.data_dirty = False                # True when words/cooldowns hold unsaved changes
bot.last_swear_save = 0               # epoch seconds of the last successful save
bot.last_leaderboard_update = dict()  # guild_id -> epoch seconds of last board edit
bot.leaderboard_pending = set()       # guild_ids whose board needs a redraw
bot.leaderboard_tasks = dict()        # guild_id -> scheduled flush task
bot.leaderboard_locks = dict()        # guild_id -> asyncio.Lock
bot.leaderboard_messages = dict()     # guild_id -> cached Message handle

# Constants consumed by command callbacks, exposed on the bot for convenience.
bot.thumb = ALERT_THUMBNAIL_URL
bot.default_cooldown_minutes = DEFAULT_COOLDOWN_MINUTES
bot.default_cooldown_seconds = DEFAULT_COOLDOWN_SECONDS
bot.min_watchword_length = MIN_WATCHWORD_LENGTH
bot.alert_content_max_chars = ALERT_CONTENT_MAX_CHARS
bot.watched_page_size = WATCHED_PAGE_SIZE
bot.max_import_bytes = MAX_IMPORT_BYTES
bot.leaderboard_update_frequency = LEADERBOARD_UPDATE_FREQUENCY


# ---------------------------------------------------------------------------
# Swear word detection
#
# Two properties matter here and neither was true before:
#
#   Determinism. SWEAR_WORDS is a set, so '|'.join(...) produced a different
#   alternation order in every process (string hashing is seed-randomised).
#   Python's re alternation is first-alternative-wins, not longest-match, so a
#   message scored differently after a restart: "ass-fucker" counted 1 on some
#   boots and 2 on others. Sorting by descending length (then alphabetically to
#   break ties) makes the order stable AND makes the longest entry win.
#
#   Speed. The pattern has ~2745 alternatives and re has no trie optimisation,
#   so every word boundary retried all of them: ~17ms for a page of ordinary
#   prose, on the event loop, for every message. A cheap token prefilter skips
#   the regex entirely for the overwhelming majority of messages, which contain
#   no swear at all.
#
# Counting rule: non-overlapping, left-to-right, longest-match-first, case
# insensitive, each match bounded by \b exactly as before. "class" still does
# not count as "ass".
# ---------------------------------------------------------------------------

_WORD_RUN = re.compile(r'\w+', re.UNICODE)

# re.IGNORECASE folds two characters onto ASCII that str.casefold() does not.
# Derived by scanning the whole of Unicode (U+0000-U+10FFFF) for characters where
# re.fullmatch(ascii_char, ch, re.IGNORECASE) succeeds but casefold() does not
# produce that character; the result is exactly these two. Without them the token
# prefilter is stricter than the pattern it guards and silently drops real
# matches ("b\u0131tch", "sh\u0130t"). test asserts the set is still complete.
_IGNORECASE_FOLD = str.maketrans({"\u0130": "i", "\u0131": "i"})


def _fold(text: str) -> str:
    """Folds text at least as aggressively as re.IGNORECASE does."""
    return text.translate(_IGNORECASE_FOLD).casefold()


def _prefilter_key(entry: str):
    """The most selective \\w+ run of an entry, or None if it has none.

    Soundness: when a \\b-anchored entry matches, every one of its \\w+ runs is a
    complete token of the message. The first run is preceded by a non-word
    character (or the string start) because of the leading \\b; every later run is
    preceded by the non-word character that separates it inside the entry; and
    each run is followed either by a non-word character inside the entry or, for
    the final run, by the non-word character the trailing \\b requires. So keying
    on ANY run is sound -- and the longest one is the most selective, which keeps
    common words like "a" (from the entry "a s s") out of the prefilter.

    Entries with no word characters at all (e.g. "@$$") get no key and are always
    tested, since "b@$$y" is a legitimate match. Keys and message tokens are both
    folded via _fold() so the prefilter folds at least as hard as re.IGNORECASE.
    """
    runs = _WORD_RUN.findall(entry)
    if not runs:
        return None
    # casefold(), not lower(): re.IGNORECASE folds characters lower() leaves
    # alone (U+017F LATIN SMALL LETTER LONG S folds to "s", U+0131 DOTLESS I and
    # U+0130 I WITH DOT ABOVE fold to "i"). Keying the prefilter on lower() while
    # matching with IGNORECASE let "\u017fhit" slip past the counter entirely.
    return _fold(max(runs, key=lambda r: (len(r), r)))


def _build_swear_matcher(words):
    """Compiles the detection state used by count_swears()."""
    # Longest first so the longest alternative wins; the alphabetical tiebreak
    # makes the compiled pattern byte-identical from one process to the next.
    ordered = sorted(words, key=lambda w: (-len(w), w))

    prefilter = set()
    unanchored = []
    for entry in ordered:
        token = _prefilter_key(entry)
        if token is None:
            unanchored.append(entry)
        else:
            prefilter.add(token)

    full = re.compile(r'\b(' + '|'.join(map(re.escape, ordered)) + r')\b',
                      re.IGNORECASE) if ordered else None
    # Entries the prefilter cannot vouch for are always tested against this
    # much smaller pattern.
    always = re.compile(r'\b(' + '|'.join(map(re.escape, unanchored)) + r')\b',
                        re.IGNORECASE) if unanchored else None
    return full, always, prefilter


SWEAR_PATTERN, SWEAR_ALWAYS_PATTERN, SWEAR_FIRST_TOKENS = _build_swear_matcher(SWEAR_WORDS)


def count_swears(content: str) -> int:
    """Returns how many tracked swear words appear in content."""
    if not content or SWEAR_PATTERN is None:
        return 0

    # Prefilter: an entry can only match if its most selective token appears as
    # a token of the message. Tokenising is linear and cheap; the full
    # alternation is not. Ordinary chatter exits here.
    tokens = {_fold(m.group(0)) for m in _WORD_RUN.finditer(content)}
    if tokens.isdisjoint(SWEAR_FIRST_TOKENS):
        if SWEAR_ALWAYS_PATTERN is None:
            return 0
        return len(SWEAR_ALWAYS_PATTERN.findall(content))

    return len(SWEAR_PATTERN.findall(content))


# ---------------------------------------------------------------------------
# Discord embed limits. These are hard API limits, not tunables: exceeding any
# of them makes the whole send fail with HTTP 400 and the message is lost.
# ---------------------------------------------------------------------------
EMBED_TITLE_LIMIT = 256
EMBED_DESCRIPTION_LIMIT = 4096
EMBED_FIELD_VALUE_LIMIT = 1024
EMBED_FOOTER_LIMIT = 2048

# Opening -> closing quote pairs, mirroring discord.ext.commands.view._quotes so
# the slash-command path strips exactly what the prefix parser already strips.
QUOTE_PAIRS = {
    '"': '"', '‘': '’', '‚': '‛', '“': '”',
    '„': '‟', '⹂': '⹂', '「': '」', '『': '』',
    '〝': '〞', '﹁': '﹂', '﹃': '﹄', '＂': '＂',
    '｢': '｣', '«': '»', '‹': '›', '《': '》',
    '〈': '〉',
}


def clamp(text, limit: int, suffix: str = "…") -> str:
    """Truncates text so it fits one of Discord's embed limits."""
    text = "" if text is None else str(text)
    if len(text) <= limit:
        return text
    if limit <= len(suffix):
        return text[:limit]
    return text[:limit - len(suffix)] + suffix


def as_int(value, default: int = 0) -> int:
    """Coerces a value loaded from JSON to an int, falling back to default.

    The .json files are plain text on disk and may be hand-edited or predate the
    current schema, so nothing read out of them is trusted to be the right type.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_word(word) -> str:
    """Normalizes a word/phrase supplied by either command path.

    The prefix parser strips surrounding quotes before a callback sees them, but
    the app-command path passes the option value VERBATIM -- so
    /watchword "lorem ipsum" used to store the quote characters as part of the
    word, which could then never match message content. Strip matched surrounding
    quotes and outer whitespace so both paths store the same thing.
    """
    if word is None:
        return ""
    word = str(word).strip()
    while len(word) >= 2 and QUOTE_PAIRS.get(word[0]) == word[-1]:
        word = word[1:-1].strip()
    return word


def word_lookup_keys(word) -> list:
    """Ordered keys to try when looking up an already-watched word.

    Entries added before quote-stripping existed can be stored with literal quote
    characters, so the un-normalized form is tried as a fallback; without it those
    entries could never be inspected, filtered or deleted.
    """
    keys = []
    normalized = normalize_word(word).lower()
    if normalized:
        keys.append(normalized)
    legacy = ("" if word is None else str(word)).strip().lower()
    if legacy and legacy not in keys:
        keys.append(legacy)
    return keys


def get_channel_id(channel_mention: str) -> int:
    """Extracts numeric channel ID from a discord channel mention string."""
    match = re.search(r'\d+', str(channel_mention))
    return int(match.group()) if match else 0


def get_timeStamp() -> str:
    """Returns current time (hr:min:sec)"""
    return datetime.datetime.fromtimestamp(time.time()).strftime('%H:%M:%S')


def check_user(member: discord.Member):
    """Ensures a member exists in both user dictionaries.

    user_words and user_cds live in two separate files, so a user can legitimately
    exist in one and be missing from the other (a crash between the two writes, a
    restored backup, a hand-edited file). The two are therefore repaired
    independently -- previously user_cds was only ever seeded inside the
    "not in user_words" branch, which left /watched raising KeyError forever.
    """
    mem_id = str(member.id)
    if not isinstance(bot.user_words.get(mem_id), dict):
        bot.user_words[mem_id] = dict()
    if mem_id not in bot.user_cds:
        bot.user_cds[mem_id] = bot.default_cooldown_seconds


def check_server(member: discord.Member, server_id: str):
    """Ensures the member has a dict for this server. Use after check_user."""
    mem_id = str(member.id)
    srv_id = str(server_id)
    if not isinstance(bot.user_words.get(mem_id), dict):
        bot.user_words[mem_id] = dict()
    if not isinstance(bot.user_words[mem_id].get(srv_id), dict):
        bot.user_words[mem_id][srv_id] = dict()


def get_server_words(member: discord.Member, server_id: str) -> dict:
    """Returns the member's word dict for a server, creating/repairing as needed.

    Single entry point for command callbacks, so no command indexes into
    bot.user_words directly and risks a KeyError on unexpected persisted data.
    """
    check_user(member)
    check_server(member, server_id)
    return bot.user_words[str(member.id)][str(server_id)]


def get_word_entry(words: dict, key: str) -> dict:
    """Returns one word's entry, repairing anything the persisted file got wrong."""
    entry = words.get(key)
    if not isinstance(entry, dict):
        entry = {"last_alerted": 0, "channels": dict()}
        words[key] = entry
    channels = entry.get("channels")
    if isinstance(channels, (list, tuple, set)):
        # Older/hand-written data stored channels as a list instead of a dict.
        entry["channels"] = {str(x): bot.static for x in channels}
    elif not isinstance(channels, dict):
        entry["channels"] = dict()
    return entry


def find_watched_word(words: dict, word):
    """Returns the key actually stored for a user-supplied word, or None."""
    if not isinstance(words, dict):
        return None
    for key in word_lookup_keys(word):
        if key in words:
            return key
    return None


def get_user_cooldown(mem_id) -> int:
    """Returns a user's alert cooldown in seconds, tolerating missing values."""
    return max(0, as_int(bot.user_cds.get(str(mem_id)), bot.default_cooldown_seconds))


def format_channel_names(channel_mentions) -> str:
    """Renders stored channel mentions as #names, tolerating deleted channels."""
    names = []
    for mention in channel_mentions:
        channel = bot.get_channel(get_channel_id(mention))
        names.append("#" + (getattr(channel, "name", None) or "unknown-channel"))
    return ", ".join(names)


def valid_channel_mentions(args) -> bool:
    """True when every argument looks like a channel mention."""
    for channel in args:
        if not (channel.startswith("<#") or channel.startswith("<!#")) or not channel.endswith(">"):
            return False
    return True


async def send_missing_word(ctx, command_name: str):
    """Reply used when a word argument is missing, empty, or only quotes."""
    embed = discord.Embed(
        title="No word or phrase given.",
        description="Type it without quotes, for example `/{} lorem ipsum`.\n"
                    "Use `/help` for full documentation.".format(command_name),
        color=0x9f9f9f)
    await ctx.send(embed=embed)


async def send_bad_channels(ctx):
    embed = discord.Embed(title="Invalid channel(s), use the \"#\" symbol to select channel.",
                          color=0xe23a1d)
    await ctx.send(embed=embed)


async def send_not_watched(ctx, word: str):
    embed = discord.Embed(
        title=clamp("\"{}\" is not being watched.".format(word), EMBED_TITLE_LIMIT),
        color=0xe23a1d)
    await ctx.send(embed=embed)


def ensure_valid_channels(member: discord.Member, server: discord.Guild, word: str):
    """Drops filters pointing at channels that no longer exist."""
    mem_id = str(member.id)
    srv_id = str(server.id)
    words = bot.user_words.get(mem_id)
    if not isinstance(words, dict):
        return
    server_words = words.get(srv_id)
    if not isinstance(server_words, dict) or word not in server_words:
        return
    entry = get_word_entry(server_words, word)
    # Threads are not in guild.channels, so include them or a thread filter would
    # be silently deleted the first time /worddetail runs.
    all_channels = {x.id for x in server.channels} | {x.id for x in server.threads}
    kept = {cid: bot.static for cid in entry["channels"]
            if get_channel_id(cid) in all_channels}
    # Never prune a filter down to empty: on_message reads an empty channel dict
    # as "watch the whole server", so dropping the last entry would silently turn
    # a deliberately narrow watch into a server-wide DM firehose. guild.threads is
    # only the ACTIVE thread cache, so an archived thread would otherwise be
    # pruned here too. Leaving a dead filter in place simply matches nothing.
    if kept or not entry["channels"]:
        entry["channels"] = kept


# Serializes saves so a periodic autosave and a swear-triggered save can never
# write the same temp file at the same time.
_save_lock = asyncio.Lock()


def load_json(path: str, default=None):
    """Reads JSON from `path`, returning `default` if it cannot be used.

    A corrupt or unreadable data file must never crash the bot on boot with a
    traceback, and must never be mistaken for "no data". Pass a fresh object as
    `default` (usually `{}`), since it is returned as-is.
    """
    if default is None:
        default = {}
    if not os.path.isfile(path):
        print("INFO: {} not found; starting with empty data.".format(path))
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        print("WARNING: {} is not valid JSON ({}); starting with empty data. "
              "Back the file up now - the next save will overwrite it.".format(path, e))
        return default
    except OSError as e:
        print("WARNING: could not read {} ({}); starting with empty data. "
              "Back the file up now - the next save will overwrite it.".format(path, e))
        return default
    if not isinstance(data, type(default)):
        print("WARNING: {} contains a JSON {}, expected {}; starting with empty data.".format(
            path, type(data).__name__, type(default).__name__))
        return default
    return data


def write_to_json() -> bool:
    """Writes all bot data to disk atomically. Returns True on success.

    Each file is written to `<path>.tmp`, flushed and fsync'd, then moved into
    place with os.replace(), which is atomic on POSIX and on Windows. A crash or
    SIGKILL therefore can never leave a truncated JSON file behind: the previous
    copy survives untouched. All four payloads are staged before any file is
    swapped in, which shrinks the window in which userwords.json and
    usercds.json could disagree to a few consecutive rename syscalls.

    Never raises. This is reachable from on_message(), where an exception would
    take down message handling for every user.
    """
    targets = [
        (USER_WORDS_FILE, bot.user_words),
        (USER_CDS_FILE, bot.user_cds),
        (SWEAR_COUNTS_FILE, bot.swear_counts),
        (LEADERBOARDS_FILE, bot.leaderboards),
    ]

    staged = []
    try:
        for path, data in targets:
            # Serialize first so an unserializable payload never touches disk.
            payload = json.dumps(data)
            parent = os.path.dirname(path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())
            staged.append((tmp, path))
        for tmp, path in staged:
            os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as e:
        print("ERROR: could not save user data @ {}: {}".format(get_timeStamp(), e))
        for tmp, _ in staged:
            try:
                os.remove(tmp)
            except OSError:
                pass
        return False

    print("Saving user data @ {}".format(get_timeStamp()))
    return True


async def _save_locked() -> bool:
    """Performs the write. The caller must already hold _save_lock."""
    ok = await asyncio.to_thread(write_to_json)
    if ok:
        bot.swear_dirty = False
        bot.data_dirty = False
        bot.last_swear_save = calendar.timegm(time.gmtime())
    return ok


async def save_data() -> bool:
    """Saves all bot data without blocking the event loop.

    write_to_json() does blocking file I/O, so it runs in a worker thread. The
    bookkeeping is cleared in one place so that every save path - periodic,
    debounced, or command-triggered - leaves the dirty flags consistent.
    """
    async with _save_lock:
        return await _save_locked()


def _swear_save_due() -> bool:
    return (bot.swear_dirty and
            calendar.timegm(time.gmtime()) - bot.last_swear_save >= SWEAR_SAVE_FREQUENCY)


async def maybe_save_swears() -> bool:
    """Debounced save for swear counts.

    Writes only when there is something new to write and at most once every
    SWEAR_SAVE_FREQUENCY seconds. Cheap enough to call on every message.

    The condition is checked twice: once cheaply before contending for the lock,
    and again after acquiring it. Without the second check, every message that
    arrives while an earlier save is in flight would queue its own full four-file
    write, since the flags are only cleared once that write completes.
    """
    if not _swear_save_due():
        return False
    async with _save_lock:
        if not _swear_save_due():
            return False
        return await _save_locked()


async def save_json():
    """Saves user data in JSON format periodically."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(SAVE_FREQUENCY)
        await save_data()


# ---------------------------------------------------------------------------
# Live swearboard
#
# The board used to be redrawn on every single swearing message: a fetch_message
# plus an edit, per message. Discord allows roughly 5 message edits per 5s per
# channel, so an active server sat on 429s. Worse, the old handler unregistered
# the board on ANY exception -- a transient rate limit permanently killed it
# until somebody re-ran /swearboard.
#
# Updates are now coalesced per guild: the first swear schedules a flush, later
# swears inside the window mark the board dirty rather than editing, and the
# flush redraws once when the window expires. Nothing is dropped, it is deferred.
# ---------------------------------------------------------------------------


def _leaderboard_lock(guild_id: str) -> asyncio.Lock:
    lock = bot.leaderboard_locks.get(guild_id)
    if lock is None:
        lock = asyncio.Lock()
        bot.leaderboard_locks[guild_id] = lock
    return lock


def forget_leaderboard(guild_id: str) -> None:
    """Drops every trace of a guild's board. Used on permanent failures only."""
    bot.leaderboards.pop(guild_id, None)
    bot.last_leaderboard_update.pop(guild_id, None)
    bot.leaderboard_pending.discard(guild_id)
    bot.leaderboard_messages.pop(guild_id, None)
    bot.leaderboard_locks.pop(guild_id, None)


async def _resolve_leaderboard_message(guild_id: str):
    """Returns the board's Message, using a cached channel-bound handle if we have one.

    Only messages obtained via channel.fetch_message are ever cached. The object
    Context.send returns on the slash-command path is an InteractionMessage whose
    edit() routes through edit_original_response, i.e. the interaction webhook
    token - and that token expires 15 minutes after the interaction. Caching it
    meant every redraw after that window got a 404, which _redraw_leaderboard
    classified as permanent and used to unregister the board.
    """
    cached = bot.leaderboard_messages.get(guild_id)
    if cached is not None:
        return cached
    info = bot.leaderboards.get(guild_id)
    if not isinstance(info, dict):
        return None
    channel = bot.get_channel(as_int(info.get("channel_id"), 0))
    if channel is None:
        return None
    message = await channel.fetch_message(as_int(info.get("message_id"), 0))
    bot.leaderboard_messages[guild_id] = message
    return message


async def _redraw_leaderboard(guild: discord.Guild) -> None:
    """Edits a guild's board once. Only unregisters on permanent failures."""
    guild_id = str(guild.id)
    if guild_id not in bot.leaderboards:
        return
    # Stamped before the attempt, not after a success. If this were only updated
    # on success, one transient failure would leave `elapsed` unbounded and the
    # next swear would redraw immediately with no debounce at all - amplifying
    # the 429 storm the coalescing exists to prevent.
    bot.last_leaderboard_update[guild_id] = calendar.timegm(time.gmtime())
    try:
        message = await _resolve_leaderboard_message(guild_id)
        if message is None:
            return
        await message.edit(embed=await make_swearboard_embed(guild))
    except (discord.NotFound, discord.Forbidden) as e:
        # Permanent: the message is gone, or we can no longer edit it. Clean up
        # rather than retrying forever.
        print("Swearboard for guild {} is unreachable ({}); unregistering it.".format(guild_id, e))
        forget_leaderboard(guild_id)
        await save_data()
    except Exception as e:
        # Transient (429, 5xx, connection reset). Keep the registration and drop
        # any stale cached handle so the next attempt re-fetches.
        bot.leaderboard_messages.pop(guild_id, None)
        print("Could not edit swearboard for guild {} ({}); will retry.".format(guild_id, e))


async def _flush_leaderboard(guild: discord.Guild) -> None:
    """Waits out the debounce window, then redraws while the board is dirty."""
    guild_id = str(guild.id)
    async with _leaderboard_lock(guild_id):
        while guild_id in bot.leaderboard_pending:
            interval = max(0, as_int(bot.leaderboard_update_frequency, 30))
            elapsed = calendar.timegm(time.gmtime()) - bot.last_leaderboard_update.get(guild_id, 0)
            remaining = interval - elapsed
            if remaining > 0:
                await asyncio.sleep(remaining)
            # Clear before drawing: a swear arriving during the edit re-marks the
            # board and the loop goes round again, so nothing is missed.
            bot.leaderboard_pending.discard(guild_id)
            await _redraw_leaderboard(guild)


def schedule_leaderboard_update(guild: discord.Guild) -> None:
    """Marks a guild's board dirty and ensures exactly one flush is pending."""
    guild_id = str(guild.id)
    if guild_id not in bot.leaderboards:
        return
    bot.leaderboard_pending.add(guild_id)
    task = bot.leaderboard_tasks.get(guild_id)
    if task is not None and not task.done():
        return  # a flush is already scheduled; it will pick up this change
    # Keep a strong reference: create_task only holds a weak one.
    bot.leaderboard_tasks[guild_id] = asyncio.create_task(
        _flush_leaderboard(guild), name="swearboard-{}".format(guild_id))


async def make_swearboard_embed(guild: discord.Guild) -> discord.Embed:
    """Renders the top swearers as a fixed-width table."""
    guild_id_str = str(guild.id)
    server_data = bot.swear_counts.get(guild_id_str, {})
    if not isinstance(server_data, dict):
        server_data = {}

    sorted_users = sorted(server_data.items(),
                          key=lambda item: (-as_int(item[1], 0), str(item[0])))

    table_lines = ["+------+----------------------+-------+",
                   "| Rank | User                 | Count |",
                   "+------+----------------------+-------+"]

    for rank, (user_id_str, count) in enumerate(sorted_users[:15], start=1):
        # Cache only. The old code awaited guild.fetch_member() per uncached row,
        # up to 15 HTTP calls per redraw, inside a bare `except: pass`.
        member = guild.get_member(as_int(user_id_str, 0))
        user_name = member.name if member is not None else "Unknown User"
        if len(user_name) > 20:
            user_name = user_name[:17] + "..."
        # Abbreviated so a large count cannot widen the column and break the
        # table's alignment against the +---+ rules above and below.
        n = as_int(count, 0)
        shown = str(n) if n < 100000 else ("{}k".format(n // 1000) if n < 100000000 else "99999k")
        table_lines.append("| {:<4} | {:<20} | {:<5} |".format(rank, user_name, shown[:5]))

    if not sorted_users:
        table_lines.append("| -    | No users yet         | -     |")

    table_lines.append("+------+----------------------+-------+")

    embed = discord.Embed(title="🤬 Swear Word Leaderboard", color=0xe23a1d)
    embed.description = "```\n{}\n```".format("\n".join(table_lines))
    embed.set_footer(text="Updates about every {}s. Tracking {} words.".format(
        max(0, as_int(bot.leaderboard_update_frequency, 30)), len(SWEAR_WORDS)))
    return embed


@bot.hybrid_command()
async def help(ctx):
    """Shows the bot documentation in this channel"""
    # Posted in-channel, not by DM: ctx.author.send() raises discord.Forbidden for
    # anyone with DMs closed, which made /help fail outright for those users.
    # Branding card, carried over from upstream. Kept as its own embed so the
    # original author's attribution survives; /help no longer DMs, so all three
    # go out together in the channel.
    banner = discord.Embed(title="WordWatch Bot",
                           description="Checks messages for key words and notifies you!",
                           color=0x30abc0)
    banner.set_thumbnail(url=bot.thumb)
    banner.set_footer(text="by pixeltopic")

    core = discord.Embed(title="WordWatch Bot Commands",
                         description=help_str.description_str,
                         color=0xa3a3a3)
    core.add_field(name="How words are matched",
                   value=help_str.usage_str.format(min_length=bot.min_watchword_length),
                   inline=False)
    core.add_field(name="/help", value=help_str.help_cmd_str, inline=False)
    core.add_field(name="/watched [page]", value=help_str.watched_str, inline=False)
    core.add_field(name="/watchword <word> [channels]", value=help_str.watchword_str, inline=False)
    core.add_field(name="/deleteword <word>", value=help_str.deleteword_str, inline=False)
    core.add_field(name="/watchclear", value=help_str.watchclear_str, inline=False)
    core.add_field(name="/cd [minutes]",
                   value=help_str.cd_str.format(default_cd=bot.default_cooldown_minutes),
                   inline=False)
    core.add_field(name="/worddetail <word>", value=help_str.worddetail_str, inline=False)
    core.add_field(name="/addfilter <word> [channels]", value=help_str.addfilter_str, inline=False)
    core.add_field(name="/deletefilter <word> [channels]", value=help_str.deletefilter_str, inline=False)
    core.add_field(name="/clearfilter <word>", value=help_str.clearfilter_str, inline=False)
    core.set_footer(text=help_str.footer_str)

    extras = discord.Embed(title="WordWatch Bot — Swear Tracking & Admin",
                           description=help_str.admin_description_str,
                           color=0xa3a3a3)
    extras.add_field(name="/swearboard", value=help_str.swearboard_str, inline=False)
    extras.add_field(name="/swearreset  (Admin only)", value=help_str.swearreset_str, inline=False)
    extras.add_field(name="/swearexport  (Admin only)", value=help_str.swearexport_str, inline=False)
    extras.add_field(name="/swearimport <file>  (Admin only)", value=help_str.swearimport_str, inline=False)
    extras.add_field(name="/forcesave  (Admin only)", value=help_str.forcesave_str, inline=False)
    extras.add_field(name="/botstop  (Admin only)", value=help_str.botstop_str, inline=False)
    extras.set_footer(text=help_str.admin_footer_str)

    # 16 commands over 3 embeds (banner + 11 fields + 6 fields), each well inside
    # the 25-field and 6000-character caps, and under 6000 across the message.
    await ctx.send(embeds=[banner, core, extras])


@bot.hybrid_command()
@commands.guild_only()
async def cd(ctx, mins: float = None):
    """Set cooldown (in minutes) for each word. With no parameter, uses the default"""
    check_user(ctx.author)
    if mins is None:
        mins = float(bot.default_cooldown_minutes)
    if not math.isfinite(mins) or mins < 0:
        embed = discord.Embed(title="Minute cooldown must be a non-negative number.", color=0xe23a1d)
    else:
        # int(mins * 60), not int(mins) * 60: the latter truncated a fractional
        # setting (0.5 minutes) to a zero-second cooldown, i.e. no rate limiting.
        bot.user_cds[str(ctx.author.id)] = int(mins * 60)
        bot.data_dirty = True
        await save_data()
        embed = discord.Embed(title="Notification cooldown set to {:g} min".format(mins),
                              color=0x39c12f)
    await ctx.send(embed=embed)


@bot.hybrid_command()
@commands.guild_only()
async def deleteword(ctx, word: str = None):
    """Deletes specified word from the user's pinged words"""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    normalized = normalize_word(word).lower()
    if not normalized:
        await send_missing_word(ctx, "deleteword")
        return

    if len(words) == 0:
        await ctx.send(embed=discord.Embed(title="You don't have any words added.", color=0xe23a1d))
        return

    # find_watched_word also matches entries stored with literal quotes by the old
    # slash-command path, so those remain deletable.
    stored_key = find_watched_word(words, word)
    if stored_key is not None:
        words.pop(stored_key, None)
        bot.data_dirty = True
        await save_data()
        await ctx.send(embed=discord.Embed(
            title=clamp("\"{}\" deleted from watch list".format(stored_key), EMBED_TITLE_LIMIT),
            color=0x39c12f))
        return

    await ctx.send(embed=discord.Embed(
        title=clamp("\"{}\" was not found on your watch list".format(normalized), EMBED_TITLE_LIMIT),
        color=0xe23a1d))


@bot.hybrid_command()
@commands.guild_only()
async def watchclear(ctx):
    """Clears all the user's watched words."""
    check_user(ctx.author)
    check_server(ctx.author, str(ctx.guild.id))
    bot.user_words[str(ctx.author.id)][str(ctx.guild.id)] = dict()
    bot.data_dirty = True
    await save_data()
    await ctx.send(embed=discord.Embed(title="Your watch list is cleared.", color=0x39c12f))


@bot.hybrid_command()
@commands.guild_only()
async def watchword(ctx, word: str = None, *, channels: str = ""):
    """Adds word to user's watched list. Optionally supports channel filtering."""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    word = normalize_word(word)
    if not word:
        await send_missing_word(ctx, "watchword")
        return

    # Matching is substring-based and case-insensitive ("ass" matches "class"),
    # which is intentional -- but it means a 1-2 character word matches nearly
    # every message and floods the watcher's DMs, so enforce a floor.
    min_length = max(1, as_int(bot.min_watchword_length, 3))
    if len(word) < min_length:
        await ctx.send(embed=discord.Embed(
            title=clamp("\"{}\" is too short to watch.".format(word), EMBED_TITLE_LIMIT),
            description="Watched words must be at least **{}** characters long. Words match "
                        "anywhere inside a message, so shorter ones match almost everything "
                        "and would flood your DMs.".format(min_length),
            color=0xe23a1d))
        return

    word = word.lower()
    if find_watched_word(words, word) is not None:
        await ctx.send(embed=discord.Embed(
            title=clamp("You are already watching \"{}\"".format(word), EMBED_TITLE_LIMIT),
            color=0x39c12f))
        return

    args = channels.split() if channels else []
    if not valid_channel_mentions(args):
        await send_bad_channels(ctx)
        return

    words[word] = {"last_alerted": calendar.timegm(time.gmtime()),
                   "channels": {x: bot.static for x in args}}
    bot.data_dirty = True
    await save_data()

    embed = discord.Embed(
        title=clamp("\"{}\" added to watch list".format(word), EMBED_TITLE_LIMIT), color=0x39c12f)
    if len(args) == 0:
        embed.set_footer(text="Watching entire server. Use /addfilter to only watch certain channels.")
    else:
        embed.set_footer(text=clamp("Watching {}".format(format_channel_names(args)), EMBED_FOOTER_LIMIT))
    await ctx.send(embed=embed)


@bot.hybrid_command()
@commands.guild_only()
async def worddetail(ctx, word: str = None):
    """Gives user details for a watched word or phrase."""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    normalized = normalize_word(word).lower()
    if not normalized:
        await send_missing_word(ctx, "worddetail")
        return

    stored_key = find_watched_word(words, word)
    if stored_key is None:
        await ctx.send(embed=discord.Embed(
            title=clamp("\"{}\" was not found on your watch list".format(normalized), EMBED_TITLE_LIMIT),
            color=0xe23a1d))
        return

    ensure_valid_channels(ctx.author, ctx.guild, stored_key)
    data = get_word_entry(words, stored_key)

    embed = discord.Embed(
        title=clamp("Word Details for {}".format(ctx.author.name), EMBED_TITLE_LIMIT), color=0xeb8d25)
    embed.add_field(name="Word/Phrase", value=clamp(stored_key, EMBED_FIELD_VALUE_LIMIT), inline=False)
    channels_watching = format_channel_names(data["channels"].keys())
    embed.add_field(name="Channels watching",
                    value=clamp(channels_watching or "All channels", EMBED_FIELD_VALUE_LIMIT),
                    inline=False)
    last_alerted = as_int(data.get("last_alerted"), 0)
    if last_alerted <= 0:
        last_seen = "Never"
    else:
        last_seen = "{} min ago".format(max(0, (calendar.timegm(time.gmtime()) - last_alerted) // 60))
    embed.add_field(name="Last seen", value=last_seen, inline=False)
    await ctx.send(embed=embed)


@bot.hybrid_command()
@commands.guild_only()
async def addfilter(ctx, word: str = None, *, channels: str = ""):
    """Adds filter to specified word"""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    normalized = normalize_word(word).lower()
    if not normalized:
        await send_missing_word(ctx, "addfilter")
        return
    # No minimum-length check here on purpose: the word must already be on the
    # watch list, so it already passed /watchword's validation.

    args = channels.split() if channels else []
    if len(args) == 0:
        await ctx.send(embed=discord.Embed(title="No channels specified.", color=0xe23a1d))
        return
    if not valid_channel_mentions(args):
        await send_bad_channels(ctx)
        return

    stored_key = find_watched_word(words, word)
    if stored_key is None:
        await send_not_watched(ctx, normalized)
        return

    get_word_entry(words, stored_key)["channels"].update({x: bot.static for x in args})
    bot.data_dirty = True
    await save_data()
    await ctx.send(embed=discord.Embed(
        title=clamp("{} added to \"{}\"".format(format_channel_names(args), stored_key), EMBED_TITLE_LIMIT),
        color=0x39c12f))


@bot.hybrid_command()
@commands.guild_only()
async def deletefilter(ctx, word: str = None, *, channels: str = ""):
    """Removes filter from specified word"""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    normalized = normalize_word(word).lower()
    if not normalized:
        await send_missing_word(ctx, "deletefilter")
        return

    args = channels.split() if channels else []
    if len(args) == 0:
        await ctx.send(embed=discord.Embed(title="No channels specified.", color=0xe23a1d))
        return
    if not valid_channel_mentions(args):
        await send_bad_channels(ctx)
        return

    stored_key = find_watched_word(words, word)
    if stored_key is None:
        await send_not_watched(ctx, normalized)
        return

    entry = get_word_entry(words, stored_key)
    for to_remove in args:
        entry["channels"].pop(to_remove, None)
    bot.data_dirty = True
    await save_data()
    await ctx.send(embed=discord.Embed(
        title=clamp("{} removed from \"{}\"".format(format_channel_names(args), stored_key), EMBED_TITLE_LIMIT),
        color=0x39c12f))


@bot.hybrid_command()
@commands.guild_only()
async def clearfilter(ctx, word: str = None):
    """Clears filter from specified word"""
    words = get_server_words(ctx.author, str(ctx.guild.id))

    normalized = normalize_word(word).lower()
    if not normalized:
        await send_missing_word(ctx, "clearfilter")
        return

    stored_key = find_watched_word(words, word)
    if stored_key is None:
        await send_not_watched(ctx, normalized)
        return

    get_word_entry(words, stored_key)["channels"] = dict()
    bot.data_dirty = True
    await save_data()
    embed = discord.Embed(
        title=clamp("All filters removed from \"{}\"".format(stored_key), EMBED_TITLE_LIMIT),
        color=0x39c12f)
    embed.set_footer(text="Now watching entire server for word/phrase.")
    await ctx.send(embed=embed)


@bot.hybrid_command()
@commands.guild_only()
async def watched(ctx, page: int = 1):
    """Shows user a list of their watched words, one page at a time"""
    member = ctx.author
    words = sorted(get_server_words(member, str(ctx.guild.id)).keys())
    total = len(words)
    page_size = max(1, as_int(bot.watched_page_size, 50))
    total_pages = max(1, (total + page_size - 1) // page_size)
    # get_user_cooldown() instead of bot.user_cds[...]: the two data files are
    # saved separately, so the cooldown entry can legitimately be missing.
    cooldown_str = "Notification Cooldown Preference: {} min".format(get_user_cooldown(member.id) // 60)

    if total == 0:
        embed = discord.Embed(
            title=clamp("{}'s watched words/phrases".format(member.name), EMBED_TITLE_LIMIT),
            description="No words or phrases currently watched.", color=0x76c7e9)
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=clamp(cooldown_str, EMBED_FOOTER_LIMIT))
        await ctx.send(embed=embed)
        return

    if page < 1 or page > total_pages:
        await ctx.send(embed=discord.Embed(
            title=clamp("Page {} doesn't exist.".format(page), EMBED_TITLE_LIMIT),
            description="You are watching **{}** word(s) on this server, which is **{}** "
                        "page(s). Try `/watched page:1`.".format(total, total_pages),
            color=0xe23a1d))
        return

    page_words = words[(page - 1) * page_size:(page - 1) * page_size + page_size]

    # Descriptions are capped at 4096 characters. Paging by count is not enough on
    # its own, because a single watched phrase can itself be very long, so the
    # rendered lines are also kept inside a character budget.
    budget = EMBED_DESCRIPTION_LIMIT - 200
    lines, used, hidden = [], 0, 0
    for index, watchedword in enumerate(page_words):
        line = "• " + discord.utils.escape_markdown(str(watchedword))
        if used + len(line) + 1 > budget:
            hidden = len(page_words) - index
            break
        lines.append(line)
        used += len(line) + 1

    watched_str = "\n".join(lines)
    if hidden:
        notice = "*{} more on this page were too long to display.*".format(hidden)
        watched_str = (watched_str + "\n\n" + notice) if watched_str else notice

    embed = discord.Embed(
        title=clamp("{}'s watched words/phrases".format(member.name), EMBED_TITLE_LIMIT),
        description=clamp(watched_str, EMBED_DESCRIPTION_LIMIT), color=0x76c7e9)
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    if total_pages > 1:
        embed.add_field(
            name="⚠️ Your list spans several pages",
            value=clamp("Showing **{}** of **{}** watched words. Use `/watched page:<number>` "
                        "to see the rest (pages 1-{}).".format(len(lines), total, total_pages),
                        EMBED_FIELD_VALUE_LIMIT),
            inline=False)
    embed.set_footer(text=clamp("Page {} of {} • {} word(s) total • {}".format(
        page, total_pages, total, cooldown_str), EMBED_FOOTER_LIMIT))
    await ctx.send(embed=embed)


@bot.hybrid_command()
@commands.guild_only()
async def swearboard(ctx):
    """Outputs a live-updating table of the top swearers in the server."""
    msg = await ctx.send(embed=await make_swearboard_embed(ctx.guild))

    guild_id_str = str(ctx.guild.id)
    bot.leaderboards[guild_id_str] = {"channel_id": str(ctx.channel.id),
                                      "message_id": str(msg.id)}
    # Store ids only. msg may be an InteractionMessage bound to an interaction
    # token that expires in 15 minutes; _resolve_leaderboard_message will fetch a
    # durable channel-bound handle on the first redraw. Drop any stale handle from
    # a previous board in this guild.
    bot.leaderboard_messages.pop(guild_id_str, None)
    bot.last_leaderboard_update[guild_id_str] = calendar.timegm(time.gmtime())
    await save_data()


@bot.hybrid_command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
@discord.app_commands.default_permissions(administrator=True)
async def swearreset(ctx):
    """Resets the swear leaderboard for the current server. Admin only."""
    guild_id_str = str(ctx.guild.id)
    bot.swear_counts.pop(guild_id_str, None)
    forget_leaderboard(guild_id_str)
    await save_data()
    await ctx.send(embed=discord.Embed(title="🗑️ Swear leaderboard has been reset.", color=0x39c12f))


@bot.hybrid_command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
@discord.app_commands.default_permissions(administrator=True)
async def swearexport(ctx):
    """Exports the server's swear leaderboard as a JSON file. Admin only."""
    guild_id_str = str(ctx.guild.id)
    export_data = {
        "guild_id": guild_id_str,
        "guild_name": ctx.guild.name,
        "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "swear_counts": bot.swear_counts.get(guild_id_str, {}),
    }
    file = discord.File(io.BytesIO(json.dumps(export_data, indent=2).encode("utf-8")),
                        filename="swearboard_{}.json".format(guild_id_str))
    await ctx.send(embed=discord.Embed(title="📤 Swear leaderboard exported.", color=0x39c12f), file=file)


@bot.hybrid_command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
@discord.app_commands.default_permissions(administrator=True)
async def swearimport(ctx, file: discord.Attachment = None):
    """Imports swear leaderboard data from an attached JSON file. Admin only."""
    async def fail(title):
        await ctx.send(embed=discord.Embed(title=title, color=0xe23a1d))

    if file is None:
        await fail("❌ Please attach a JSON file to import.")
        return
    if not file.filename.endswith(".json"):
        await fail("❌ File must be a .json file.")
        return
    if file.size > bot.max_import_bytes:
        await fail("❌ File too large (max {} bytes).".format(bot.max_import_bytes))
        return

    try:
        data = json.loads((await file.read()).decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        await fail("❌ Invalid JSON file.")
        return

    if not isinstance(data, dict) or "swear_counts" not in data:
        await fail("❌ Invalid format: missing 'swear_counts' key.")
        return

    swear_counts = data["swear_counts"]
    if not isinstance(swear_counts, dict):
        await fail("❌ Invalid format: 'swear_counts' must be an object.")
        return

    for user_id, count in swear_counts.items():
        if not isinstance(user_id, str) or not user_id.isdigit():
            await fail("❌ Invalid user ID: '{}'. Must be a numeric string.".format(user_id))
            return
        # bool is a subclass of int, so it is excluded explicitly.
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            await fail("❌ Invalid count for user '{}': must be a non-negative integer.".format(user_id))
            return

    bot.swear_counts[str(ctx.guild.id)] = swear_counts
    await save_data()
    schedule_leaderboard_update(ctx.guild)

    await ctx.send(embed=discord.Embed(
        title="📥 Swear leaderboard imported.",
        description="Loaded **{}** users with **{}** total swears.".format(
            len(swear_counts), sum(swear_counts.values())),
        color=0x39c12f))


@bot.hybrid_command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
@discord.app_commands.default_permissions(administrator=True)
async def forcesave(ctx):
    """Forces the bot to write current user data into the JSON files. Admin only."""
    ok = await save_data()
    await ctx.send(embed=discord.Embed(
        title="Force save complete." if ok else "Force save FAILED - check the bot logs.",
        color=0x39c12f if ok else 0xe23a1d))


@bot.hybrid_command()
@commands.guild_only()
@commands.has_permissions(administrator=True)
@discord.app_commands.default_permissions(administrator=True)
async def botstop(ctx):
    """Saves data and logs the bot out. Admin only."""
    await ctx.send(embed=discord.Embed(title="WordWatch Bot saving data and logging out.",
                                       color=0xe23a1d))
    print("Saving before logging out...")
    await save_data()
    print("Done.")
    await bot.close()


def build_alert_embed(message: discord.Message) -> discord.Embed:
    """Builds the DM alert embed, with every part clamped to its Discord limit.

    Embed field values are capped at 1024 characters while a message body runs to
    2000 (4000 with Nitro), so an unclamped Content field made the DM fail with
    HTTP 400 and the alert was lost. Everything interpolated here is user- or
    server-controlled, so each part is clamped rather than trusted.
    """
    content_limit = min(as_int(bot.alert_content_max_chars, 1000), EMBED_FIELD_VALUE_LIMIT)
    channel_name = getattr(message.channel, "name", None) or "unknown-channel"

    embed = discord.Embed(title="A watched word/phrase was detected!", color=0xeb8d25)
    embed.set_thumbnail(url=bot.thumb)
    embed.add_field(name="Server", value=clamp(message.guild.name, EMBED_FIELD_VALUE_LIMIT), inline=False)
    embed.add_field(name="Channel", value=clamp(channel_name, EMBED_FIELD_VALUE_LIMIT), inline=False)
    embed.add_field(name="Author", value=clamp(str(message.author), EMBED_FIELD_VALUE_LIMIT), inline=False)
    # An empty field value is also rejected by Discord (attachment-only message).
    embed.add_field(name="Content",
                    value=clamp(message.content, content_limit) or "*(no text content)*",
                    inline=False)
    embed.add_field(name="Jump",
                    value=clamp("[Go to message]({})".format(message.jump_url), EMBED_FIELD_VALUE_LIMIT),
                    inline=False)
    embed.set_footer(text=clamp("Detected message sent at {}".format(message.created_at), EMBED_FOOTER_LIMIT))
    return embed


def commit_last_alerted(mem: str, server_id: str, keyword: str, when: int):
    """Records a successful alert, but only if the watcher still watches that word.

    on_message awaits between snapshotting the word dict and writing back to it, so
    a concurrent /deleteword or /watchclear can remove the entry in between.
    Re-indexing it blindly raised KeyError out of on_message entirely, abandoning
    every remaining watcher for that message.
    """
    guilds = bot.user_words.get(mem)
    if not isinstance(guilds, dict):
        return
    words = guilds.get(server_id)
    if not isinstance(words, dict):
        return
    entry = words.get(keyword)
    if isinstance(entry, dict):
        entry["last_alerted"] = when


@bot.event
async def on_message(message):
    """Scans messages for key words/phrases and alerts any user watching them"""
    if message.author == bot.user:
        return

    # commands.BotBase.on_message is nothing but `await self.process_commands(...)`.
    # Registering this function with @bot.event REPLACES that method, so without
    # this call every prefix (mention) invocation of all 16 hybrid commands is dead.
    # It sits at function level, not inside the guild check below, because the
    # prefix is commands.when_mentioned, which works in DMs too. No extra author
    # guard is needed: process_commands already starts with `if message.author.bot`.
    await bot.process_commands(message)

    current_time = calendar.timegm(time.gmtime())

    # message.guild is None means it's a DM, which we shouldn't scan
    if message.guild is None or message.author.bot:
        return

    guild_id_str = str(message.guild.id)
    author_id_str = str(message.author.id)

    # 1. Swear word detection & counting
    hits = count_swears(message.content)
    if hits:
        guild_counts = bot.swear_counts.setdefault(guild_id_str, {})
        guild_counts[author_id_str] = as_int(guild_counts.get(author_id_str), 0) + hits
        bot.swear_dirty = True
        # Coalesced: marks the board dirty and lets one scheduled flush redraw it.
        schedule_leaderboard_update(message.guild)

    # Debounced save: writes at most once every SWEAR_SAVE_FREQUENCY seconds, and
    # only when there is something new to write.
    await maybe_save_swears()

    # 2. Key words scanning & alerts
    lowered_content = message.content.lower()
    for mem in list(bot.user_words.keys()):
        # Never alert the author about their own message.
        if author_id_str == mem:
            continue

        # Nothing below indexes the persisted structure directly: userwords.json is
        # hand-editable and may predate the current schema, and a single KeyError
        # here used to escape on_message and kill alerting entirely.
        guilds = bot.user_words.get(mem)
        if not isinstance(guilds, dict):
            continue
        server_words = guilds.get(guild_id_str)
        if not isinstance(server_words, dict):
            continue

        for keyword, innerdict in list(server_words.items()):
            if not isinstance(keyword, str) or not keyword.strip():
                continue  # a legacy empty key would match every single message
            if not isinstance(innerdict, dict):
                # Repair the STORED value, not just a local shadow. Shadowing left
                # commit_last_alerted unable to write (it checks the stored entry),
                # so the cooldown never recorded and the watcher was DMed for every
                # matching message forever.
                innerdict = get_word_entry(server_words, keyword)

            if keyword not in lowered_content:
                continue

            last_alerted = as_int(innerdict.get("last_alerted"), 0)
            if current_time - last_alerted < get_user_cooldown(mem):
                continue

            channels = innerdict.get("channels")
            if not isinstance(channels, (dict, list, tuple, set)):
                channels = {}
            has_no_filters = len(channels) == 0
            has_channel_filter = ("<#" + str(message.channel.id) + ">" in channels) or \
                                 ("<!#" + str(message.channel.id) + ">" in channels)
            if not (has_no_filters or has_channel_filter):
                continue

            try:
                # Reserve the cooldown BEFORE the first await. discord.py runs each
                # on_message as its own task, so a burst of matching messages would
                # otherwise all read the same stale timestamp while the first is
                # parked on the DM and each send their own alert. Reserving here
                # (still inside the try) closes that window; a transient failure
                # rolls the value back below so the next message retries.
                previous_alerted = last_alerted
                commit_last_alerted(mem, guild_id_str, keyword, current_time)

                # Cache first: fetch_user is a full HTTP round trip, once per alert,
                # and the watcher is normally already cached.
                user = bot.get_user(int(mem))
                if user is None:
                    user = await bot.fetch_user(int(mem))
                if user:
                    await user.send(embed=build_alert_embed(message))
                else:
                    commit_last_alerted(mem, guild_id_str, keyword, previous_alerted)
            except discord.Forbidden:
                # DMs closed or bot blocked: this can never succeed, so keep the
                # reservation rather than taking a 403 on every matching message.
                print("Cannot DM user {}: DMs closed or bot blocked.".format(mem))
            except Exception as e:
                # Transient failure: put the cooldown back so the next matching
                # message retries instead of silently skipping.
                commit_last_alerted(mem, guild_id_str, keyword, previous_alerted)
                print("Error alerting user {}: {}".format(mem, e))


def load_data():
    """Loads every persisted structure from disk.

    Called once from WordWatchBot.setup_hook. Guarded so a second call is a no-op:
    reloading after the bot has been running would silently discard in-memory
    state, which is exactly what doing this in on_ready used to cause on every
    gateway reconnect.
    """
    if bot._data_loaded:
        return

    bot.user_words = load_json(USER_WORDS_FILE, {})
    bot.user_cds = load_json(USER_CDS_FILE, {})
    bot.swear_counts = load_json(SWEAR_COUNTS_FILE, {})
    bot.leaderboards = load_json(LEADERBOARDS_FILE, {})

    # The two user structures are written separately, so a crash between the two
    # writes can leave a user present in one and missing from the other.
    for mem_id in bot.user_words:
        bot.user_cds.setdefault(mem_id, DEFAULT_COOLDOWN_SECONDS)

    migrated = migrate_quoted_words()

    bot._data_loaded = True
    print("Data loaded: {} user(s), {} guild(s) with swear counts, {} leaderboard(s).{}".format(
        len(bot.user_words), len(bot.swear_counts), len(bot.leaderboards),
        " Normalized {} quoted word(s).".format(migrated) if migrated else ""))


def migrate_quoted_words() -> int:
    """Rewrites words stored with literal quote characters to their bare form.

    Before quote-stripping existed the slash-command path stored the option
    verbatim, so /watchword "lorem ipsum" saved the key '"lorem ipsum"'. Commands
    can still find those via word_lookup_keys, but on_message matches the stored
    key against the message text directly - so such an entry is listed by
    /watched and looks active while never firing an alert. Normalizing once on
    load fixes them for good; on a collision the bare key wins and the quoted
    duplicate is dropped.
    """
    migrated = 0
    for guilds in bot.user_words.values():
        if not isinstance(guilds, dict):
            continue
        for words in guilds.values():
            if not isinstance(words, dict):
                continue
            for key in list(words.keys()):
                if not isinstance(key, str):
                    continue
                fixed = normalize_word(key).lower()
                if not fixed or fixed == key:
                    continue
                entry = words.pop(key)
                words.setdefault(fixed, entry)
                migrated += 1
    return migrated


@bot.event
async def on_ready():
    """Fires on first login AND on every RESUME/reconnect.

    Everything here must therefore be cheap and idempotent. Data loading lives in
    WordWatchBot.setup_hook - doing it here rolled back up to SAVE_FREQUENCY
    seconds of in-memory state every time the gateway blipped.
    """
    await bot.change_presence(activity=discord.Game(name="Questions? Type /help"))
    print("Logged in as {} (id: {}) - connected to {} guild(s).".format(
        bot.user, bot.user.id, len(bot.guilds)))


@bot.event
async def on_guild_remove(guild: discord.Guild):
    """Purges a guild's data when the bot is kicked, banned, or the guild is deleted.

    Not the same as an outage: an unreachable guild fires on_guild_unavailable, so
    this only runs for a real removal.
    """
    guild_id_str = str(guild.id)

    watchers_cleared = words_cleared = 0
    for mem_id in list(bot.user_words.keys()):
        guilds = bot.user_words.get(mem_id)
        if not isinstance(guilds, dict):
            continue  # malformed persisted entry; nothing to purge here
        guild_words = guilds.pop(guild_id_str, None)
        if guild_words is not None:
            watchers_cleared += 1
            words_cleared += len(guild_words)

    had_counts = bot.swear_counts.pop(guild_id_str, None) is not None
    had_board = guild_id_str in bot.leaderboards
    forget_leaderboard(guild_id_str)

    print("Removed from guild {} ({}). Purged {} watched word(s) across {} user(s); "
          "swear counts: {}; leaderboard: {}.".format(
              guild.name, guild_id_str, words_cleared, watchers_cleared,
              "yes" if had_counts else "none", "yes" if had_board else "none"))
    await save_data()


# ---------------------------------------------------------------------------
# Application command syncing
#
# Global tree.sync() is heavily rate-limited and there is no reason to call it on
# a boot that changed nothing. Instead, hash everything Discord actually stores
# about the command surface and sync only when that hash moves.
#
# Command.to_dict(tree) returns the exact payload sent to Discord - name,
# description, every option's name/description/type/required/choices, plus
# default_member_permissions and dm_permission - so ANY user-visible text change,
# including a reworded docstring, moves the hash.
# ---------------------------------------------------------------------------

COMMAND_FINGERPRINT_VERSION = 1  # bump to force a one-off resync for everyone


def compute_command_fingerprint() -> str:
    """sha256 over the full global command surface. Stable across processes."""
    entries = []
    for command in bot.tree.get_commands():
        try:
            payload = command.to_dict(bot.tree)
        except Exception:
            # Fall back to the attributes we can read if the private shape changes.
            payload = {"name": command.name,
                       "description": getattr(command, "description", "")}
        entries.append(payload)
    # Registration order is not user-visible, so sort for a stable hash.
    entries.sort(key=lambda d: (str(d.get("type", "")), str(d.get("name", ""))))
    blob = json.dumps({"version": COMMAND_FINGERPRINT_VERSION, "commands": entries},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def read_stored_command_fingerprint():
    """Returns the fingerprint recorded by the last SUCCESSFUL sync, or None."""
    state = load_json(SYNC_STATE_FILE, {})
    fingerprint = state.get("fingerprint") if isinstance(state, dict) else None
    return fingerprint if isinstance(fingerprint, str) and fingerprint else None


def write_stored_command_fingerprint(fingerprint: str, command_count: int) -> None:
    """Records a successful sync. Written atomically."""
    state = {"version": COMMAND_FINGERPRINT_VERSION,
             "fingerprint": fingerprint,
             "command_count": command_count,
             "synced_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    tmp_path = SYNC_STATE_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, SYNC_STATE_FILE)
    except OSError as e:
        print("Could not write {}: {}. Commands will re-sync next boot.".format(SYNC_STATE_FILE, e))
        try:
            os.remove(tmp_path)
        except OSError:
            pass


async def sync_commands_if_changed() -> None:
    """Syncs the global command tree only when its user-visible surface changed."""
    current = compute_command_fingerprint()
    stored = read_stored_command_fingerprint()

    if FORCE_SYNC:
        reason = "WORDWATCH_FORCE_SYNC is set"
    elif stored is None:
        reason = "no stored fingerprint"
    elif stored != current:
        reason = "fingerprint changed ({} -> {})".format(stored[:12], current[:12])
    else:
        print("Commands unchanged (fingerprint {}); skipping global sync.".format(current[:12]))
        return

    print("Syncing application commands globally: {}.".format(reason))
    try:
        synced = await bot.tree.sync()
    except Exception as e:
        # Deliberately do NOT store the fingerprint, so a rate-limited or failed
        # sync retries next boot instead of being skipped forever.
        print("Error syncing commands globally: {!r}. Will retry on next startup.".format(e))
        return

    write_stored_command_fingerprint(current, len(synced))
    print("Synced {} application command(s). Fingerprint stored: {}.".format(
        len(synced), current[:12]))


# ---------------------------------------------------------------------------
# Error handling
#
# How errors actually flow for a hybrid command (verified against discord.py
# 2.7.1): the ext check predicates installed by commands.guild_only() and
# commands.has_permissions() raise commands.NoPrivateMessage /
# commands.MissingPermissions. On the slash path hybrid.py catches those with
# `except CommandError` and hands them to command.dispatch_error(...), which
# dispatches on_command_error and SWALLOWS the exception - bot.tree.error never
# sees it. So on_command_error is the workhorse for BOTH paths, and tree.error
# only catches what the ext layer never wraps (a stale registration, etc.).
# ---------------------------------------------------------------------------

ERROR_COLOR = 0xe23a1d


def unwrap_command_error(error: BaseException) -> BaseException:
    """Peels the wrapper layers discord.py puts around the real cause."""
    for _ in range(5):
        original = getattr(error, "original", None)
        if original is None or original is error:
            break
        error = original
    return error


def explain_command_error(error: BaseException):
    """Maps an error onto (user-facing message, whether to log a traceback)."""
    app = discord.app_commands
    err = unwrap_command_error(error)

    if isinstance(err, (commands.NoPrivateMessage, app.NoPrivateMessage)):
        return "This command can only be used inside a server.", False

    if isinstance(err, (commands.MissingPermissions, app.MissingPermissions)):
        missing = ", ".join(p.replace("_", " ").replace("guild", "server").title()
                            for p in getattr(err, "missing_permissions", None) or [])
        return ("You need the **{}** permission to use this command.".format(missing)
                if missing else "You do not have permission to use this command."), False

    if isinstance(err, (commands.BotMissingPermissions, app.BotMissingPermissions)):
        missing = ", ".join(p.replace("_", " ").replace("guild", "server").title()
                            for p in getattr(err, "missing_permissions", None) or [])
        return ("I am missing the **{}** permission in this channel.".format(missing)
                if missing else "I am missing a permission I need here."), False

    # Must precede the generic CheckFailure branch: CommandOnCooldown subclasses it.
    if isinstance(err, (commands.CommandOnCooldown, app.CommandOnCooldown)):
        return "That command is on cooldown. Try again in {:.1f}s.".format(err.retry_after), False

    if isinstance(err, commands.MissingRequiredArgument):
        return "Missing required argument `{}`. Use `/help` for usage.".format(err.param.name), False

    if isinstance(err, (commands.BadArgument, commands.BadUnionArgument,
                        commands.TooManyArguments, commands.ArgumentParsingError)):
        return "Bad argument: {}".format(err), False

    if isinstance(err, app.TransformerError):
        return "Could not interpret one of the options you supplied.", False

    if isinstance(err, (app.CommandNotFound, app.CommandSignatureMismatch)):
        return ("This command is out of date on Discord's side. It will be refreshed "
                "the next time the bot restarts - please try again later."), True

    if isinstance(err, commands.DisabledCommand):
        return "That command is currently disabled.", False

    # Any other failed check. Keep AFTER every specific CheckFailure subclass.
    if isinstance(err, (commands.CheckFailure, app.CheckFailure)):
        return "You can't use that command here.", False

    return "Something went wrong while running that command.", True


def build_error_embed(message: str) -> discord.Embed:
    if len(message) <= 240:
        return discord.Embed(title="❌ " + message, color=ERROR_COLOR)
    return discord.Embed(title="❌ Command error",
                         description=clamp(message, EMBED_DESCRIPTION_LIMIT), color=ERROR_COLOR)


@bot.event
async def on_command_error(ctx: commands.Context, error: commands.CommandError):
    """Handles the prefix path AND the slash path of every hybrid command.

    Replaces commands.Bot.on_command_error, whose default behaviour is to print a
    raw traceback to stderr and tell the user nothing.
    """
    # A stray mention that isn't a command: stay silent. The prefix is
    # commands.when_mentioned, so every plain @WordWatch reaches this.
    if isinstance(error, commands.CommandNotFound):
        return
    if ctx.command is not None and ctx.command.has_error_handler():
        return
    if ctx.cog is not None and ctx.cog.has_error_handler():
        return

    message, should_log = explain_command_error(error)
    if should_log:
        print("[on_command_error] {} raised {!r}".format(
            getattr(ctx.command, "qualified_name", "<unknown command>"), error))
        traceback.print_exception(type(error), error, error.__traceback__)

    try:
        await ctx.send(embed=build_error_embed(message), ephemeral=True)
    except Exception as exc:
        # Reporting an error must never become a second error.
        print("[on_command_error] could not deliver error response: {!r}".format(exc))


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction,
                               error: discord.app_commands.AppCommandError):
    """Handles app-command failures the ext layer never sees."""
    message, should_log = explain_command_error(error)
    if should_log:
        name = interaction.command.qualified_name if interaction.command else "<unknown command>"
        print("[on_app_command_error] {} raised {!r}".format(name, error))
        traceback.print_exception(type(error), error, error.__traceback__)

    embed = build_error_embed(message)
    try:
        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=True)
    except Exception as exc:
        print("[on_app_command_error] could not deliver error response: {!r}".format(exc))


bot.run(DISCORD_TOKEN)
