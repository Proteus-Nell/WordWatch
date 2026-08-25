"""Documentation strings used by the /help command.

Discord embed limits, for reference (per embed):
    title 256 | description 4096 | field name 256 | field value 1024
    footer 2048 | max 25 fields | 6000 characters total per embed
Every ``*_str`` below is used as a field value, so keep each one under 1024
characters. ``description_str`` is used as a description (4096) and
``footer_str`` / ``admin_footer_str`` as footers (2048).
"""

description_str = (
    "Watches server messages for your words and phrases, then DMs you when one shows up.\n"
    "Everything is a slash command — type `/` in a channel to browse them."
)

# Explains matching semantics, including that quotes are NOT used: the
# slash-command option is taken verbatim, so a typed quote becomes part of the
# word. {min_length} is filled in from bot.min_watchword_length by /help.
usage_str = (
    "Type the word or phrase exactly as you want it matched — **do not wrap it in quotes**. "
    "Multi-word phrases work as-is: `/watchword lorem ipsum`.\n"
    "Matching ignores case and matches anywhere inside a message, so `class` also "
    "triggers on `classroom`. Words must be at least {min_length} characters long."
)

help_cmd_str = """Shows this documentation in the current channel.\n`/help`"""

watched_str = (
    "Lists every word and phrase you watch on this server, plus your current `/cd` setting.\n"
    "Long lists are split into pages — pass a page number to see the rest.\n"
    "`/watched`\n`/watched page:2`"
)

watchword_str = (
    "Start watching a word or phrase and get DMed when it appears, no more often than your "
    "`/cd` setting allows. Optionally list channels after it to watch only those.\n"
    "`/watchword lorem`\n`/watchword lorem ipsum`\n`/watchword lorem ipsum #general #off-topic`"
)

deleteword_str = """Stop watching a word or phrase.\n`/deleteword lorem`\n`/deleteword lorem ipsum`"""

watchclear_str = """Stops watching everything on this server at once.\n`/watchclear`"""

# {default_cd} is filled in from bot.default_cooldown_minutes by /help.
cd_str = (
    "How long to wait before alerting you again about the same word. {default_cd} minutes by default.\n"
    "`/cd` (back to the default)\n`/cd 3`"
)

worddetail_str = (
    "Shows the channel filters on a watched word and when it was last seen.\n"
    "`/worddetail lorem`\n`/worddetail lorem ipsum`"
)

addfilter_str = (
    "Narrows a watched word to specific channels. Channels are separated by spaces and add to "
    "any already set.\n`/addfilter lorem #general #games`"
)

deletefilter_str = (
    "Removes channels from a watched word's filter.\n`/deletefilter lorem ipsum #off-topic #general`"
)

clearfilter_str = (
    "Removes every channel filter from a word so the whole server is watched again.\n`/clearfilter lorem`"
)

admin_description_str = (
    "Server-wide swear counting, plus the maintenance commands.\n"
    "The Admin only commands need the Administrator permission."
)

swearboard_str = (
    "Posts a live-updating table of the server's top swearers. The table edits itself as "
    "people swear.\n`/swearboard`"
)

swearreset_str = """Wipes the server's swear counts and forgets the posted leaderboard message.\n`/swearreset`"""

swearexport_str = """Exports this server's swear counts as a downloadable JSON file.\n`/swearexport`"""

swearimport_str = (
    "Replaces this server's swear counts with an attached JSON file in the same format "
    "`/swearexport` produces.\n`/swearimport file:<attachment>`"
)

forcesave_str = """Writes all in-memory data to the JSON files right now, instead of waiting for the next autosave.\n`/forcesave`"""

botstop_str = """Saves all data and logs the bot out.\n`/botstop`"""

footer_str = """Do not put quotes around words or phrases. Commands only work inside servers."""

admin_footer_str = """Commands marked Admin only require the Administrator permission."""
