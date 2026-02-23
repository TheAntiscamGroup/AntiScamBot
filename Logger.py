from enum import auto
from BotEnums import CompareEnum
import datetime, time, asyncio, sys, coloredlogs
from logger_tt import setup_logging, logger

__all__ = ["LogLevel", "Logger"]

class LogLevel(CompareEnum):
  Debug=auto()
  Verbose=auto()
  Log=auto()
  Warn=auto()
  Error=auto()
  Notice=auto()
  Silence=auto()

CurrentLoggingLevel = LogLevel.Debug
CurrentNotificationLevel = LogLevel.Warn
HasInitialized = False
NotificationCallback = None

coloredlogs.DEFAULT_LOG_FORMAT = '[%(asctime)s] %(processName)-24s %(levelname)9s %(message)s'
coloredlogs.DEFAULT_LEVEL_STYLES = {'critical': {'bold': True, 'color': 'red'}, 'debug': {'color': 'green'}, 'error': {'color': 'red'}, 'info': {}, 'notice': {'color': 'magenta'}, 'spam': {'color': 'green', 'faint': True}, 'success': {'bold': True, 'color': 'green'}, 'verbose': {'color': 'blue'}, 'warning': {'color': 'yellow'}}
coloredlogs.DEFAULT_FIELD_STYLES = {}

setup_logging(config_path='log_config.json')
coloredlogs.install(level='VERBOSE')

class Logger():
  @staticmethod
  def Start():
    global HasInitialized
    if (not HasInitialized):
      HasInitialized = True

  @staticmethod
  def GetTimestamp():
    return time.time()

  @staticmethod
  def PrintDate():
    NowTime = str(datetime.datetime.now())
    return f"[{NowTime}] "

  @staticmethod
  def CLog(Conditional, Level:LogLevel, Input:str):
    ShouldPrint:bool = False
    try:
      if (callable(Conditional)):
        ShouldPrint = Conditional() # pyright: ignore[reportAssignmentType]
      else:
        ShouldPrint = bool(Conditional)
    except Exception as ex:
      logger.debug(f"Encountered error on conditional check {ex}")
      return

    if (ShouldPrint):
      Logger.Log(Level, Input)

  @staticmethod
  def Log(Level:LogLevel, Input:str):
    global NotificationCallback

    if Level < CurrentLoggingLevel:
      return

    if CurrentLoggingLevel == LogLevel.Silence:
      return

    # Set up color logging
    ColorStr = ""
    LoggerFunc = logger.info
    MessageStr = f"[{sys._getframe(1).f_code.co_name}] {Input}"
    if Level == LogLevel.Error:
      LoggerFunc = logger.error
    elif Level == LogLevel.Warn:
      LoggerFunc = logger.warning
    elif Level == LogLevel.Verbose:
      LoggerFunc = logger.info
    elif Level == LogLevel.Debug:
      LoggerFunc = logger.debug

    LoggerFunc(f"{MessageStr}")

    if (NotificationCallback is not None and Level >= CurrentNotificationLevel):
      try:
        CurrentLoop = asyncio.get_running_loop()
      except RuntimeError:
        # If there is no currently running loop, then don't bother sending notification messages
        return

      # This will automatically get added to the task loop.
      CurrentLoop.create_task(NotificationCallback(f"[{str(Level)}]: {MessageStr}"))

  @staticmethod
  def SetLogLevel(NewLevel: LogLevel):
    global CurrentLoggingLevel

    CurrentLoggingLevel = NewLevel

  @staticmethod
  def GetLogLevel():
    return CurrentLoggingLevel

  @staticmethod
  def GetLogLevelName():
    return CurrentLoggingLevel.name

  @staticmethod
  def SetNotificationCallback(NewCallback):
    global NotificationCallback
    NotificationCallback = NewCallback

Logger.Start()