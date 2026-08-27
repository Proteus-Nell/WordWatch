# WordWatch Setup

To run this bot on a Discord server:

### 1. Set Up Your Application on the Discord Developer Portal

1. Visit the [Discord Developer Portal](https://discord.com/developers/applications).
2. Click **New Application** in the top right corner, name your bot, and save.
3. Select the **Bot** tab on the left menu, then click **Add Bot** (if not already a bot).
4. Scroll down on the **Bot** tab to the **Privileged Gateway Intents** section.
5. **CRITICAL**: Enable the **Message Content Intent** (and optionally *Presence Intent* and *Server Members Intent*), then click **Save Changes**.

### 2. Generate the Bot Invite Link

1. Go to the **OAuth2** tab on the left menu, then select the **URL Generator** sub-menu.
2. Under **Scopes**, you MUST select both:
   * `bot` (to add the bot to the server)
   * `applications.commands` (to register Slash Commands in Discord's chat autocomplete box)
3. Under **Bot Permissions**, select:
   * `Send Messages`
   * `Embed Links`
   * `Read Messages/View Channels`
   * `Read Message History`
4. Copy the generated URL at the bottom, paste it into your web browser, and authorize the bot to join your server.

### 3. Run the Bot Locally

1. Obtain the bot's token from the **Bot** tab by clicking the **Reset Token** button.
2. Copy `.env.example` in the project root to a new file named `.env`:

   ```bash
   copy .env.example .env
   ```

3. Open `.env` and replace `your_discord_bot_token_here` with your copied Discord bot token.
4. Ensure you have the dependencies installed:

   ```bash
   pip install -r requirements.txt
   ```

5. Run the bot:

   ```bash
   python main.py
   ```

Slash commands are synced globally only when the command set changes (name, description, or options). Set `WORDWATCH_FORCE_SYNC=1` to force a sync. It may take up to 1 hour for changes to appear in a new server.

All tunable settings live in `.env.example` — copy it to `.env` and uncomment anything you want to change.

# Commands

All commands are invoked via Discord's **Slash Commands** — type `/` in any text channel to see available options.

Note: Type words and phrases exactly as you want them matched — do **not** wrap them in quotes. A quote character typed into a slash-command option is stored as part of the word and will never match a message. Matching ignores case and matches anywhere inside a message (`class` also triggers on `classroom`), and watched words must be at least 3 characters long. Commands will not work outside servers the bot is running in.

1. `/help` - Posts the full command documentation in the current channel.

2. `/watched [page]` - Gives user list of all watched words/phrases on the server. Also shows current `cd` setting. Long lists are split into pages; the footer shows `Page X of Y` and the total count.

         /watched
         /watched page:2

3. `/watchword <word> [channels (optional)]` - Start watching a word or phrase and be alerted according to your `cd` setting. Channels can be filtered, skipping the `addfilter` step. Simply list channels after the word/phrase separated by spaces. Must be at least 3 characters long.

         /watchword lorem ipsum #general
         /watchword lorem #general #off-topic
         /watchword lorem ipsum
         /watchword lorem

4. `/deleteword <word>` - Deletes the specified word/phrase from your watch list.

         /deleteword lorem ipsum
         /deleteword lorem

5. `/watchclear` - Clears all watched words/phrases that you are watching.

6. `/cd [minutes]` - Toggle how long before you want to be alerted again after the most recent alert. Set at 15 minutes by default.

         /cd
         /cd 3

7. `/worddetail <word>` - Tells you the filtered channels enabled for the word/phrase and time the word/phrase was last seen.

         /worddetail lorem ipsum
         /worddetail lorem

8. `/addfilter <word> [channels]` - Start watching for word/phrase in specified channels. Will not replace previously watching channels.

         /addfilter lorem #general #games

9. `/deletefilter <word> [channels]` - Stop watching for word/phrase in specified channels.

         /deletefilter lorem ipsum #off-topic #general

10. `/clearfilter <word>` - Remove all filters from word/phrase; watch entire server instead.

         /clearfilter lorem ipsum
         /clearfilter lorem

11. `/swearboard` - Outputs a live-updating table of the top swearers in the server.

12. `/swearreset` - Resets the swear leaderboard. Admin only!

13. `/swearexport` - Exports the swear leaderboard as a JSON file. Admin only!

14. `/swearimport` - Imports swear leaderboard data from an attached JSON file. Admin only!

15. `/forcesave` - Force saves all current data into the JSON files. Admin only!

16. `/botstop` - Saves data and logs out bot. Admin only!

## AI Usage Disclaimer

This is a fork of WordWatch which was modified using AntiGravity/Gemini for my own personal usecases :P
