import discord
from discord.ext import commands
import calendar
import time
import datetime
import asyncio
import json
import os
import re

import help_str

prefix = ".."
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True

bot = commands.Bot(command_prefix=prefix, description='WordWatch Bot', intents=intents)
bot.remove_command('help')  # removes default help command!

# Swear word tracking constants & regex
def load_env(filepath=".env"):
    import os
    if not os.path.exists(filepath):
        return
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ[key.strip()] = val.strip().strip('"').strip("'")

load_env()
token = os.getenv("DISCORD_TOKEN")

def load_swear_words(filepath="swear_words.txt"):
    if not os.path.exists(filepath):
        return {"ass", "bitch", "crap", "damn", "fuck", "hell", "shit"}
    with open(filepath, "r", encoding="utf-8") as f:
        return {line.strip() for line in f if line.strip()}

SWEAR_WORDS = load_swear_words()

SWEAR_PATTERN = re.compile(r'\b(' + '|'.join(map(re.escape, SWEAR_WORDS)) + r')\b', re.IGNORECASE)

# Const attributes
bot.prefix = prefix
bot.user_words_file = "userwords.json"
bot.user_cds_file = "usercds.json"
bot.swear_counts_file = "swearcounts.json"
bot.leaderboards_file = "leaderboards.json"
bot.thumb = "https://raw.githubusercontent.com/pixeltopic/WordWatch/master/alertimage.gif"
bot.static = -1  # used for channel dict values to mimic a set
bot.scan_frequency = 5  # number of seconds before bot looks at a message again
bot.save_frequency = 900  # number of seconds before bot saves user data

# Non-Constants
bot.user_words = dict()
bot.user_cds = dict()
bot.swear_counts = dict()
bot.leaderboards = dict()
bot.last_checked = -1  # throttles event checking to prevent overload

@bot.event
async def on_ready():
    print("Logged in as")
    print(bot.user.name)
    print("Warning: bot requires both {} and {} to load data.".format(bot.user_words_file, bot.user_cds_file))
    if os.path.isfile("./" + bot.user_words_file) and os.path.isfile("./" + bot.user_cds_file):
        with open(bot.user_words_file) as word_data:
            bot.user_words = json.load(word_data)
        with open(bot.user_cds_file) as cd_data:
            bot.user_cds = json.load(cd_data)
        print("Data loaded successfully.")
    else:
        print("No data files provided or one was missing. No user data loaded.")

    if os.path.isfile("./" + bot.swear_counts_file):
        with open(bot.swear_counts_file) as f:
            bot.swear_counts = json.load(f)
    else:
        bot.swear_counts = {}

    if os.path.isfile("./" + bot.leaderboards_file):
        with open(bot.leaderboards_file) as f:
            bot.leaderboards = json.load(f)
    else:
        bot.leaderboards = {}

    await bot.change_presence(activity=discord.Game(name="Questions? Type {prefix}help".format(prefix=bot.prefix)))

@bot.command()
@commands.has_permissions(administrator=True)
async def sync(ctx):
    """Syncs slash commands to the current server (guild) instantly for testing."""
    await ctx.send("Syncing commands to this guild...")
    try:
        # Syncing to guild copies commands specifically to this guild (instant propagation)
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"Successfully synced {len(synced)} commands to this guild!")
    except Exception as e:
        await ctx.send(f"Failed to sync commands: {e}")

@bot.hybrid_command()
async def help(ctx):
    """Messages the user bot documentation"""
    embed = discord.Embed(title="WordWatch Bot",
                          description="Checks messages for key words and notifies you!",
                          color=0x30abc0)
    embed.set_thumbnail(url=bot.thumb)
    embed.set_footer(text="by pixeltopic")
    await ctx.author.send(embed=embed)

    embed = discord.Embed(title="WordWatch Bot Commands",
                          description=help_str.description_str.format(prefix=bot.prefix),
                          color=0xa3a3a3)
    embed.add_field(name="watched",
                    value=help_str.watched_str,
                    inline=False)
    embed.add_field(name="watchword \"word\" [channels (optional)]",
                    value=help_str.watchword_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="deleteword \"word\"",
                    value=help_str.deleteword_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="watchclear",
                    value=help_str.watchclear_str,
                    inline=False)
    embed.add_field(name="cd [minutes]",
                    value=help_str.cd_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="worddetail \"word\"",
                    value=help_str.worddetail_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="addfilter \"word\" [channels]",
                    value=help_str.addfilter_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="deletefilter \"word\" [channels]",
                    value=help_str.deletefilter_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="clearfilter \"word\"",
                    value=help_str.clearfilter_str.format(prefix=bot.prefix),
                    inline=False)
    embed.add_field(name="swearboard",
                    value="Outputs a live-updating table of the top swearers in the server.",
                    inline=False)
    embed.set_footer(text=help_str.footer_str)

    await ctx.author.send(embed=embed)

def get_channel_id(channel_mention: str) -> int:
    """Extracts numeric channel ID from a discord channel mention string."""
    match = re.search(r'\d+', channel_mention)
    return int(match.group()) if match else 0

def check_user(member: discord.Member):
    """Given a member, check if they are in the dictionary. if not, create one for them."""
    mem_id = str(member.id)
    if mem_id not in bot.user_words:
        bot.user_words[mem_id] = dict()
        bot.user_cds[mem_id] = 15 * 60

def check_server(member: discord.Member, server_id: str):
    """Given a server ID, checks if it exists in the dictionary. Intended to be used after check_user"""
    mem_id = str(member.id)
    srv_id = str(server_id)
    if srv_id not in bot.user_words[mem_id]:
        bot.user_words[mem_id][srv_id] = dict()

def ensure_valid_channels(member: discord.Member, server: discord.Guild, word: str):
    """If a word's watched channel is nonexistent, removes it from the dict to prevent errors"""
    result = dict()
    mem_id = str(member.id)
    srv_id = str(server.id)
    if word not in bot.user_words[mem_id][srv_id].keys():
        return
    all_channels = [x.id for x in server.channels]
    for channel_id in bot.user_words[mem_id][srv_id][word]["channels"].keys():
        digits = get_channel_id(channel_id)
        if digits in all_channels:
            result[channel_id] = bot.static
    bot.user_words[mem_id][srv_id][word]["channels"] = result

def get_timeStamp() -> str:
    """Returns current time (hr:min:sec)"""
    return datetime.datetime.fromtimestamp(time.time()).strftime('%H:%M:%S')

def write_to_json():
    """Opens .json files and writes data into it"""
    user_word_str = json.dumps(bot.user_words)
    user_cd_str = json.dumps(bot.user_cds)

    f = open(bot.user_words_file, "w+")
    f.write(user_word_str)
    f.close()
    f = open(bot.user_cds_file, "w+")
    f.write(user_cd_str)
    f.close()

    with open(bot.swear_counts_file, "w+") as f:
        json.dump(bot.swear_counts, f)
    with open(bot.leaderboards_file, "w+") as f:
        json.dump(bot.leaderboards, f)

    print("Saving user data @ {}".format(get_timeStamp()))

@bot.hybrid_command()
async def cd(ctx, mins: float = 15.0):
    """Set cooldown (in minutes) for each word. If no parameter, automatically defaults to 15 minutes"""
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return
    check_user(ctx.author)
    if mins >= 0:
        bot.user_cds[str(ctx.author.id)] = int(mins)*60
        embed = discord.Embed(title="Notification cooldown set to {} min".format(int(mins)), color=0x39c12f)
    else:
        embed = discord.Embed(title="Minute cooldown must be positive.", color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def deleteword(ctx, word: str = None):
    """Deletes specified word from the user's pinged words"""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()

    if len(bot.user_words[str(member.id)][server_id]) == 0:
        embed = discord.Embed(title="You don't have any words added.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    if word in bot.user_words[str(member.id)][server_id].keys():
        embed = discord.Embed(title="\"{}\" deleted from watch list".format(word), color=0x39c12f)
        bot.user_words[str(member.id)][server_id].pop(word, None)
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(title="\"{}\" was not found on your watch list".format(word), color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def watchclear(ctx):
    """Clears all the user's watched words."""
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    bot.user_words[str(member.id)][server_id] = dict()

    embed = discord.Embed(title="Your watch list is cleared.", color=0x39c12f)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def watchword(ctx, word: str = None, *, channels: str = ""):
    """Adds word to user's watched list with timestamp. Optionally supports channel filtering."""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()

    if word in bot.user_words[str(member.id)][server_id].keys():
        embed = discord.Embed(title="You are already watching \"{}\"".format(word), color=0x39c12f)
        await ctx.send(embed=embed)
        return

    args = channels.split() if channels else []
    for channel in args:
        if not (channel.startswith("<#") or channel.startswith("<!#")) or not channel.endswith(">"):
            embed = discord.Embed(title="Invalid channel(s), use the \"#\" symbol to select channel.", color=0xe23a1d)
            await ctx.send(embed=embed)
            return

    bot.user_words[str(member.id)][server_id][word] = {"last_alerted": calendar.timegm(time.gmtime()),
                                                  "channels": {x: bot.static for x in args}}
    if len(args) == 0:
        embed = discord.Embed(title="\"{}\" added to watch list".format(word), color=0x39c12f)
        embed.set_footer(
            text="Watching entire server. Use \"{}addfilter\" to only watch certain channels.".format(bot.prefix))
    else:
        embed = discord.Embed(title="\"{}\" added to watch list".format(word), color=0x39c12f)
        channel_names = []
        for x in args:
            chan_id = get_channel_id(x)
            channel_obj = bot.get_channel(chan_id)
            channel_names.append("#" + (channel_obj.name if channel_obj else "unknown-channel"))
        embed.set_footer(text="Watching {}".format(", ".join(channel_names)))
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def worddetail(ctx, word: str = None):
    """Gives user details for a watched word or phrase."""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()
    ensure_valid_channels(member, ctx.guild, word)

    if word in bot.user_words[str(member.id)][server_id].keys():
        data = bot.user_words[str(member.id)][server_id][word]
        embed = discord.Embed(title="Word Details for {}".format(member.name), color=0xeb8d25)
        embed.add_field(name="Word/Phrase", value=word, inline=False)
        channel_names = []
        for x in data["channels"].keys():
            chan_id = get_channel_id(x)
            channel_obj = bot.get_channel(chan_id)
            channel_names.append("#" + (channel_obj.name if channel_obj else "unknown-channel"))
        channels_watching = ", ".join(channel_names)
        embed.add_field(name="Channels watching",
                        value="All channels" if channels_watching == "" else channels_watching,
                        inline=False)
        current_time = calendar.timegm(time.gmtime())
        embed.add_field(name="Last seen",
                        value=str((current_time - data["last_alerted"])//60) + " min ago",
                        inline=False)

    else:
        embed = discord.Embed(title="\"{}\" was not found on your watch list".format(word), color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def addfilter(ctx, word: str = None, *, channels: str = ""):
    """Adds filter to specified word"""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()

    args = channels.split() if channels else []
    if len(args) == 0:
        embed = discord.Embed(title="No channels specified.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    for channel in args:
        if not (channel.startswith("<#") or channel.startswith("<!#")) or not channel.endswith(">"):
            embed = discord.Embed(title="Invalid channel(s), use the \"#\" symbol to select channel.", color=0xe23a1d)
            await ctx.send(embed=embed)
            return

    if word in bot.user_words[str(member.id)][server_id].keys():
        bot.user_words[str(member.id)][server_id][word]["channels"].update({x: bot.static for x in args})
        channel_names = []
        for x in args:
            chan_id = get_channel_id(x)
            channel_obj = bot.get_channel(chan_id)
            channel_names.append("#" + (channel_obj.name if channel_obj else "unknown-channel"))
        embed = discord.Embed(
            title="{} added to \"{}\"".format(", ".join(channel_names), word),
            color=0x39c12f)
        await ctx.send(embed=embed)
        return
    embed = discord.Embed(title="\"{}\" is not being watched.".format(word), color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def deletefilter(ctx, word: str = None, *, channels: str = ""):
    """Removes filter from specified word"""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()

    args = channels.split() if channels else []
    if len(args) == 0:
        embed = discord.Embed(title="No channels specified.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    for channel in args:
        if not (channel.startswith("<#") or channel.startswith("<!#")) or not channel.endswith(">"):
            embed = discord.Embed(title="Invalid channel(s), use the \"#\" symbol to select channel.", color=0xe23a1d)
            await ctx.send(embed=embed)
            return

    if word in bot.user_words[str(member.id)][server_id].keys():
        for to_remove in args:
            bot.user_words[str(member.id)][server_id][word]["channels"].pop(to_remove, None)
        channel_names = []
        for x in args:
            chan_id = get_channel_id(x)
            channel_obj = bot.get_channel(chan_id)
            channel_names.append("#" + (channel_obj.name if channel_obj else "unknown-channel"))
        embed = discord.Embed(
            title="{} removed from \"{}\"".format(", ".join(channel_names), word),
            color=0x39c12f)
        await ctx.send(embed=embed)
        return
    embed = discord.Embed(title="\"{}\" is not being watched.".format(word), color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def clearfilter(ctx, word: str = None):
    """Clears filter from specified word"""
    if word is None:
        embed = discord.Embed(
            title="Use {prefix}help for command documentation.".format(prefix=bot.prefix), color=0x9f9f9f)
        await ctx.send(embed=embed)
        return
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    word = word.lower()

    if word in bot.user_words[str(member.id)][server_id].keys():
        bot.user_words[str(member.id)][server_id][word]["channels"] = dict()
        embed = discord.Embed(title="All filters removed from \"{}\"".format(word), color=0x39c12f)
        embed.set_footer(text="Now watching entire server for word/phrase.")
        await ctx.send(embed=embed)
        return
    embed = discord.Embed(title="\"{}\" is not being watched.".format(word), color=0xe23a1d)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def watched(ctx):
    """Shows user a list of their watched words"""
    if ctx.guild is None:
        embed = discord.Embed(
            title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return
    member = ctx.author
    server_id = str(ctx.guild.id)

    check_user(member)
    check_server(member, server_id)

    if bot.user_words[str(member.id)][server_id] != dict():
        watched_str = ""
        for watchedword in bot.user_words[str(member.id)][server_id].keys():
            watched_str += "\"{}\", ".format(watchedword)
        watched_str = watched_str[:-2]
    else:
        watched_str = "No words or phrases currently watched."
    embed = discord.Embed(
        title="{}'s watched words/phrases".format(member.name), description=watched_str, color=0x76c7e9)
    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(text="Notification Cooldown Preference: {} min".format(int(bot.user_cds[str(member.id)]/60)))
    await ctx.send(embed=embed)

async def make_swearboard_embed(guild: discord.Guild) -> discord.Embed:
    guild_id_str = str(guild.id)
    server_data = bot.swear_counts.get(guild_id_str, {})
    
    # Sort users by count descending
    sorted_users = sorted(server_data.items(), key=lambda item: item[1], reverse=True)
    
    # Render table content
    table_lines = []
    table_lines.append("+------+----------------------+-------+")
    table_lines.append("| Rank | User                 | Count |")
    table_lines.append("+------+----------------------+-------+")
    
    rank = 1
    for user_id_str, count in sorted_users[:15]:  # show top 15
        user_name = "Unknown User"
        try:
            member = guild.get_member(int(user_id_str))
            if not member:
                member = await guild.fetch_member(int(user_id_str))
            if member:
                user_name = member.name
        except Exception:
            pass
            
        if len(user_name) > 18:
            user_name = user_name[:15] + "..."
            
        line = f"| {rank:<4} | {user_name:<20} | {count:<5} |"
        table_lines.append(line)
        rank += 1
        
    if not sorted_users:
        table_lines.append("| -    | No users yet         | -     |")
        
    table_lines.append("+------+----------------------+-------+")
    
    table_str = "\n".join(table_lines)
    
    embed = discord.Embed(title="🤬 Swear Word Leaderboard", color=0xe23a1d)
    embed.description = f"```\n{table_str}\n```"
    embed.set_footer(text=f"Updates in real-time. Tracking {len(SWEAR_WORDS)} words.")
    return embed

@bot.hybrid_command()
async def swearboard(ctx):
    """Outputs a live-updating table of the top swearers in the server."""
    if ctx.guild is None:
        embed = discord.Embed(title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    embed = await make_swearboard_embed(ctx.guild)
    msg = await ctx.send(embed=embed)
    
    # Store the leaderboard message info for updates
    guild_id_str = str(ctx.guild.id)
    bot.leaderboards[guild_id_str] = {
        "channel_id": str(ctx.channel.id),
        "message_id": str(msg.id)
    }
    write_to_json()

@bot.event
async def on_message(message):
    """Scans messages for key words/phrases and alerts any user that might be watching them"""
    if message.author == bot.user:
        return
    current_time = calendar.timegm(time.gmtime())

    # message.guild is None means it's a DM, which we shouldn't scan
    if message.guild is not None:
        guild_id_str = str(message.guild.id)
        author_id_str = str(message.author.id)

        # 1. Swear word detection & counting
        if message.content[:2] != bot.prefix:
            matches = SWEAR_PATTERN.findall(message.content)
            if matches:
                if guild_id_str not in bot.swear_counts:
                    bot.swear_counts[guild_id_str] = {}
                if author_id_str not in bot.swear_counts[guild_id_str]:
                    bot.swear_counts[guild_id_str][author_id_str] = 0
                
                bot.swear_counts[guild_id_str][author_id_str] += len(matches)
                write_to_json()

                # Trigger leaderboard update
                if guild_id_str in bot.leaderboards:
                    try:
                        leaderboard_info = bot.leaderboards[guild_id_str]
                        channel = bot.get_channel(int(leaderboard_info["channel_id"]))
                        if channel:
                            try:
                                msg = await channel.fetch_message(int(leaderboard_info["message_id"]))
                                updated_embed = await make_swearboard_embed(message.guild)
                                await msg.edit(embed=updated_embed)
                            except discord.NotFound:
                                # Message deleted in Discord: clean up stale entry without error spam
                                bot.leaderboards.pop(guild_id_str, None)
                                write_to_json()
                            except Exception as e:
                                print(f"Could not edit leaderboard message: {e}")
                                bot.leaderboards.pop(guild_id_str, None)
                                write_to_json()
                    except Exception as e:
                        print(f"Error updating leaderboard: {e}")

        # 2. Key words scanning & alerts
        if (bot.last_checked == -1 or current_time - bot.last_checked >= bot.scan_frequency) and \
                message.content[:2] != bot.prefix:
            bot.last_checked = current_time

            for mem in list(bot.user_words.keys()):
                if guild_id_str in bot.user_words[mem]:
                    for keyword, innerdict in list(bot.user_words[mem][guild_id_str].items()):
                        # Make sure we don't alert if the author is the watcher themselves
                        if author_id_str == mem:
                            continue
                        
                        is_detected = keyword in message.content.lower()
                        cooldown_expired = current_time - innerdict["last_alerted"] >= bot.user_cds.get(mem, 15*60)
                        not_command = message.content[:2] != bot.prefix

                        if is_detected and cooldown_expired and not_command:
                            has_no_filters = len(innerdict["channels"]) == 0
                            has_channel_filter = ("<#"+str(message.channel.id)+">" in innerdict["channels"]) or \
                                                 ("<!#"+str(message.channel.id)+">" in innerdict["channels"])
                            
                            if has_no_filters or has_channel_filter:
                                bot.user_words[mem][guild_id_str][keyword]["last_alerted"] = current_time
                                try:
                                    user = await bot.fetch_user(int(mem))
                                    if user:
                                        embed = discord.Embed(title="A watched word/phrase was detected!", color=0xeb8d25)
                                        embed.set_thumbnail(url=bot.thumb)
                                        embed.add_field(name="Server", value=message.guild.name, inline=False)
                                        embed.add_field(name="Channel", value=message.channel.name, inline=False)
                                        embed.add_field(name="Author", value=str(message.author), inline=False)
                                        embed.add_field(name="Content", value=message.content, inline=False)
                                        embed.set_footer(text="Detected message sent at {}".format(message.created_at))
                                        await user.send(embed=embed)
                                except Exception as e:
                                    print(f"Error alerting user {mem}: {e}")

    await bot.process_commands(message)

async def save_json():
    """Saves user data in JSON format periodically."""
    await bot.wait_until_ready()
    while not bot.is_closed():
        await asyncio.sleep(bot.save_frequency)  # task runs every 900 seconds (15 mins)
        write_to_json()

@bot.hybrid_command()
async def forcesave(ctx):
    """Forces the bot to write current saved user data into their respective JSON files."""
    if ctx.guild is None:
        embed = discord.Embed(
            title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    perms = ctx.author.guild_permissions

    if not perms.administrator:
        embed = discord.Embed(title="Command only usable by admin", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    write_to_json()

    embed = discord.Embed(title="Force save complete.", color=0x39c12f)
    await ctx.send(embed=embed)

@bot.hybrid_command()
async def botstop(ctx):
    """Turns off the bot"""
    if ctx.guild is None:
        embed = discord.Embed(
            title="You can't use this command outside of servers.", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    perms = ctx.author.guild_permissions

    if not perms.administrator:
        embed = discord.Embed(title="Command only usable by admin", color=0xe23a1d)
        await ctx.send(embed=embed)
        return

    embed = discord.Embed(title="WordWatch Bot saving data and logging out.", color=0xe23a1d)
    await ctx.send(embed=embed)
    print("Saving before logging out...")
    write_to_json()
    print("Done.")
    await bot.close()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    if interaction.response.is_done():
        await interaction.followup.send(f"❌ An error occurred: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ An error occurred: {error}", ephemeral=True)

async def custom_setup():
    bot.loop.create_task(save_json())
    try:
        # Sync globally on startup
        await bot.tree.sync()
        print("Commands synced globally.")
    except Exception as e:
        print(f"Error syncing commands globally on startup: {e}")

bot.setup_hook = custom_setup
bot.run(token)
