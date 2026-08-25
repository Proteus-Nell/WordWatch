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
   *   `bot` (to add the bot to the server)
   *   `applications.commands` (to register Slash Commands in Discord's chat autocomplete box)
3. Under **Bot Permissions**, select:
   *   `Send Messages`
   *   `Embed Links`
   *   `Read Messages/View Channels`
   *   `Read Message History`
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
   pip install discord.py
   ```
5. Run the bot:
   ```bash
   python main.py
   ```

### 4. Register Slash Commands
Once the bot is online, type the prefix command `..sync` in any text channel on your server (you must be a server administrator to do this). This will instantly register all commands as slash commands in that server. (Otherwise, global registration can take up to 1 hour to propagate).

# Commands
The bot uses the prefix `..` to invoke commands or you can use the slash command and preview your available options.

Calling a command in the chat (example demonstrates the `help` command): `..help`

Note: Phrases must be wrapped in quotes but single words don't. Also, commands will not work outside servers the bot is running in.

1. `help` - Displays documentation in chat on how to use the bot.

2. `watched` - Gives user list of all watched words/phrases on the server. Also shows current `cd` setting.

3. `watchword "word" [channels (optional)]` - Start watching a word and be alerted according to your `cd` setting. Channels can be filtered, skipping the `addfilter` step. Simply list channels after the word/phrase separated by spaces.

`..watchword "lorem ipsum" #general` <br />
`..watchword lorem #general #off-topic` <br />
`..watchword "lorem ipsum"` <br />
`..watchword lorem`

4. `deleteword "word"` - Deletes the specified word/phrase from your watch list.

`..deleteword "lorem ipsum"` <br />
`..deleteword lorem`

5. `watchclear` - Clears all watched words/phrases that you are watching.

6. `cd [minutes]` - Toggle how long before you want to be alerted again after the most recent alert. Set at 15 minutes by default.

`..cd` <br />
`..cd 3`

7. `worddetail "word"` - Tells you the filtered channels enabled for the word/phrase and time the word/phrase was last seen.

`..worddetail "lorem ipsum"` <br />
`..worddetail lorem`

8. `addfilter "word" [channels]` - Start watching for word/phrase in specified channels. Will not replace previously watching channels.

`..addfilter lorem #general #games`

9. `deletefilter "word" [channels]` - Stop watching for word/phrase in specified channels.

`..deletefilter "lorem ipsum" #off-topic #general`

10. `clearfilter "word"` - Remove all filters from word/phrase; watch entire server instead.

`..clearfilter "lorem ipsum"` <br />
`..clearfilter lorem`

11. `forcesave` - Force saves all current data into the JSON files. Admin only!

12. `botstop` - Saves data and logs out bot. Admin only!