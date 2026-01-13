# ScamGuard AntiScam Bot

This is a Discord bot that bans scammers who offer unsolicited commissions to users of a Discord server.

These scammers are a scourge on our Discord communities. Unfortunately, unless they are banned in all relative servers, they’ll hop onto the next server and then attempt to scam people from there next.

To stop this from happening, this bot shares a ban list of known scammers to any servers it is activated in such that the scammers are unable to contact anyone.

This bot is powered via community reporting, trusted verification, and complete transparency in all actions.

You can read more on [the website here](https://scamguard.app/)!

---

## Configurations to Run the Bot

This bot requires that you are using (at minimum) Python 3.11

### Environment Vars

To start the bot locally, create a .env file in the current directory with the following environment variables:

```txt
DISCORD_TOKEN="your discord bot token"  
DATABASE_FILE="a path to your sql file"  
CONFIG_FILE="a path to your config file"  
API_KEYS="a path to the file with api keys for subinstance bots to spin up"
BACKUP_LOCATION="a path to a directory to store your backup sql file"  
DEVELOPMENT_MODE="true if you want to test without banning, false to ban people"  
```

Here is an example of a .env file.

```txt
DISCORD_TOKEN="0"  
DATABASE_FILE="database.db"  
CONFIG_FILE="config.json"
API_KEYS="apikeys.json"    
BACKUP_LOCATION="backup/"  
DEVELOPMENT_MODE="true"  
```

You can also have these environment variables set directly

### config.json

By default, the config.json file is preconfigured with IDs specifically for the TAG server.

To test the bot on your own Discord server for debugging purposes, here's how you can get the IDs for the server, roles, and channels

- Server ID: Right click your server icon and click on Copy Server ID
- Role ID: Go to your Server Settings -> Roles -> "..." button for the role -> Copy Role ID
- Channel ID: Right click the channel and click on Copy Channel ID

---

If you want to have a publicly accessible API endpoint for your bot instance, you can [clone this project](https://theantiscamgroup.com/AntiScamBotAPI).
