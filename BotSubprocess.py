# Subprocess handler for creating sub-bot instances
from Logger import Logger, LogLevel
from BotBase import DiscordBot
from Config import Config

def CreateBotProcess(ConnectionLocation: str, BotID: int):
  Logger.Log(LogLevel.Log, f"Bot process #{BotID} starting...")
  NewBot:DiscordBot = DiscordBot(ConnectionLocation, BotID)
  # This will block and run forever.
  NewBot.run(Config.GetToken(BotID))