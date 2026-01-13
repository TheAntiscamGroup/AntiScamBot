# The core main instance of ScamGuard, used as the primary instance. This should have code that only needs to be ran by a single instance
# Such as the host system that shares commands/messages to sub-instances and things like backup.
# It should not handle any recv instructions from ServerHandler except for requests by sub-instances.
from Logger import Logger, LogLevel
from BotEnums import BanResult, BanAction, ModerationAction
from Config import Config
from BotBase import DiscordBot
from BotConnections import RelayServer
from datetime import datetime, timedelta
from discord import Embed, User, Member, HTTPException, Message, Thread
from discord.ext import tasks
from multiprocessing import Process
from BotSubprocess import CreateBotProcess
import asyncio

__all__ = ["ScamGuard"]

ConfigData:Config=Config()

class ScamGuard(DiscordBot):
  ServerHandler:RelayServer = None # pyright: ignore[reportAssignmentType]
  HasStartedInstances:bool = False
  SubProcess={}

  ### Initialization ###
  def __init__(self, AssignedBotID:int):
    self.ServerHandler = RelayServer(AssignedBotID, self)
    super().__init__(self.ServerHandler.GetFileLocation(), AssignedBotID)
    
  async def setup_hook(self):
    # TODO: Make a fancy table for this in the future
    if (ConfigData["RunBackupEveryXHours"] > 0):
      self.PeriodicBackup.start()
      
    if (ConfigData["RunIdleCleanupEveryXHours"] > 0):
      self.PeriodicLeave.start()
      
    self.HandleListenRelay.start()
    self.HandleBanExceed.start()
    await super().setup_hook()
      
  ### Discord Tasks Handling ###
  @tasks.loop(seconds=0.5)
  async def HandleListenRelay(self):
    await self.ServerHandler.TickRelay()
  
  ### Task Interval Handling ###
  def ConfigBackupInterval(self):
    self.PeriodicBackup.change_interval(seconds=0.0, minutes=0.0, hours=float(ConfigData["RunBackupEveryXHours"])) # pyright: ignore[reportAttributeAccessIssue]

  def ConfigLeaveInterval(self):
    self.PeriodicLeave.change_interval(seconds=0.0, minutes=0.0, hours=float(ConfigData["RunIdleCleanupEveryXHours"])) # pyright: ignore[reportAttributeAccessIssue]
    
  def RetryTaskInterval(self, task):
    task.change_interval(seconds=0.0, minutes=5.0, hours=0.0)
  
  ### Backup handling ###
  # By default, this runs every 5 minutes, however upon loading configurations, this will update the
  # backup interval to the proper settings
  @tasks.loop(minutes=2)
  async def PeriodicBackup(self):
    # Prevent the first time this task runs from trying to backup at start.
    if (self.PeriodicBackup.minutes == 2.0):
      self.ConfigBackupInterval()
      return
    
    # These are safe async tasks that we can run backup during. If the task queue only has tasks of these names, then it is safe.
    SafeAsyncTaskNames = ["CreateBanAnnouncement", "PostFirstTimeMessage", "PostScamReport"]
    
    # If we have active async tasks in progress, check to see if we can continue without them
    # i.e. we are currently waiting to do something.
    if (len(self.AsyncTasks) > 0):
      for itm in self.AsyncTasks:
        if not itm.get_name() in SafeAsyncTaskNames:
          Logger.Log(LogLevel.Warn, "There are currently async tasks in progress, will try backup again in 5 minutes...")
          self.RetryTaskInterval(self.PeriodicBackup)
          return
    
    # If we currently have the minutes value set, then we need to make sure we get back onto the right track
    if (self.PeriodicBackup.minutes != 0.0):
      self.ConfigBackupInterval()
    
    Logger.Log(LogLevel.Log, "Periodic Bot DB Backup Started...")    
    self.Database.Backup()
    self.Database.CleanupBackups()
    
  ### Instance Cleanup ###
  @tasks.loop(minutes=2)
  async def PeriodicLeave(self):
    # Prevent the first time this code ever runs from running directly at startup.
    if (self.PeriodicLeave.minutes == 2.0):
      self.ConfigLeaveInterval()
      return
      
    # If we are processing any async tasks, do not clean up the deactivated table
    if (len(self.AsyncTasks) > 0):
      self.RetryTaskInterval(self.PeriodicLeave)
      return
    
    # If the instances code hasn't been able to start, wait for when it's ready again.
    if (not self.HasStartedInstances):
      self.RetryTaskInterval(self.PeriodicLeave)
      return
    
    await self.RunPeriodicLeave(False)
    
  async def RunPeriodicLeave(self, DryRun:bool):
    # If this config is less than or equal to 0, then we don't execute the task
    InactiveInstanceWindow:int = ConfigData["InactiveServerDayWindow"]
    if (InactiveInstanceWindow <= 0):
      return
    
    # If we were in a retry state, reset the config loop again so that it's in the proper cadance
    if (self.PeriodicLeave.minutes != 0.0):
      self.ConfigLeaveInterval()

    CurrentTime:datetime = datetime.now() - timedelta(days=float(InactiveInstanceWindow))
    AllDisabledServers = self.Database.GetAllDeactivatedServers()
    OldServerCount:int = len(AllDisabledServers)
    Logger.CLog(OldServerCount > 0, LogLevel.Notice, f"Non-activated server ({OldServerCount}) purge. Dry run? {DryRun}")
    ServersLeft:int = 0
    for ServerData in AllDisabledServers:
      if (CurrentTime > ServerData.created_at):
        ServerID:int = int(ServerData.discord_server_id)
        if (DryRun or self.LeaveServer(ServerID)):
          ServersLeft += 1
          Logger.Log(LogLevel.Verbose, f"Attempting to leave server {ServerID}.")
          Logger.CLog(DryRun, LogLevel.Log, f"Attempting to leave server {ServerID}.")
        else:
          Logger.Log(LogLevel.Warn, f"Could not send leave request for server {ServerID}")

        # Attempt to sleep the big scary rate limits away
        if (not DryRun):
          await asyncio.sleep(1.0)
    
    Logger.CLog(ServersLeft > 0, LogLevel.Notice, f"Server Instance Cleanup Completed, left {ServersLeft} out of {len(AllDisabledServers)}")
    
  ### Handling Ban Exceeds ###
  @tasks.loop(hours=1)
  async def HandleBanExceed(self):
    ExhaustedList = self.Database.GetExhaustedServers()
    ExhaustedListCount = len(ExhaustedList)
    if (ExhaustedListCount <= 0):
      return
    
    # If the instances are not started, then we should wait for them to start
    if (not self.HasStartedInstances):
      return
    
    NumBans:int = self.Database.GetNumBans()
    Logger.Log(LogLevel.Notice, f"Attempting to process {ExhaustedListCount} cooldown servers now")
    for Server in ExhaustedList:
      NumCount:int = NumBans - int(Server.current_pos)
      ServerId:int = int(Server.discord_server_id)
      self.Database.SetProcessingServerCooldown(ServerId, True)
      self.AddAsyncTask(self.ReprocessBansForServer(ServerId, NumCount, True))
      Logger.Log(LogLevel.Log, f"Enqueueing reprocessing of {NumCount} bans for server {ServerId}")
  
  # Handling async tasks step flow
  @PeriodicBackup.before_loop
  @HandleBanExceed.before_loop
  @PeriodicLeave.before_loop
  @HandleListenRelay.before_loop
  async def BeforeScheduledAsyncTasks(self):
    # Wait until the bot is all set up before attempting periodic leaves
    await self.wait_until_ready()
  
  ### Config Handling ###
  def ProcessConfig(self, ShouldReload:bool):
    super().ProcessConfig(ShouldReload)
      
  ### Discord Eventing ###
  async def InitializeBotRuntime(self):
    await super().InitializeBotRuntime()
    await self.StartAllInstances()       

  ### Thread handling (for automated checks) ###
  async def LeaveThread(self, thread: Thread) -> bool:
    try:
      await thread.leave()
      return True
    except:
      Logger.Log(LogLevel.Warn, f"Unable to leave the thread, encountered exception")
    return False

  async def on_thread_join(self, thread: Thread):
    # Only handle in the control server
    if (thread.guild.id == ConfigData["ControlServer"]):   
      # and in the external reports channel
      if (thread.parent_id == ConfigData["ExternalReportChannel"]):
        async for message in thread.history(limit=2, oldest_first=True):
          # leave the thread if we were invited by someone else.
          if (message.author.id != ConfigData["ThreadInviteUser"]):
            continue
          
          # Check to see if we have content, which means it's our mentionable
          if (message.content == ""):
            continue

          Logger.Log(LogLevel.Debug, f"Got post content of {message.content}")
          IDGrabList = message.content.split()
          if (len(IDGrabList) >= 2):
            userID:int = int(IDGrabList[1])
            try:
              await message.delete()
            except:
              Logger.Log(LogLevel.Log, f"Could not delete mention message {message.id}")
            ResponseEmbed:Embed = await self.CreateBanEmbed(userID)
            await thread.send(embed = ResponseEmbed)
            return

    Logger.Log(LogLevel.Debug, f"Could not find any mentionable message, leaving thread {thread.id}")
    await self.LeaveThread(thread)

  ### Subprocess instances ###
  async def StartAllInstances(self, BypassCheck:bool=False, RestartMainClient:bool=False):
    # Prevent us from restarting instances when on_ready may run again.
    if (self.HasStartedInstances and not BypassCheck):
      return
    
    if (RestartMainClient):
      Logger.Log(LogLevel.Log, "Restarting client instance for control bot instance")
      await self.StartInstance(0)
    
    # Spin up all the subinstances of the other bot clients
    AllInstances = Config.GetAllSubTokens()
    for InstanceID in AllInstances:
      await self.StartInstance(int(InstanceID))
      
    self.HasStartedInstances = True
      
  async def StartInstance(self, InstanceID:int):
    RelayFileHandleLocation = self.ServerHandler.GetFileLocation()
    if (InstanceID == 0):
      self.ClientHandler = None # pyright: ignore[reportAttributeAccessIssue]
      self.SetupClientConnection(RelayFileHandleLocation)
      self.ClientHandler.SendHello()
      return
    
    # Make sure to exit out of any instances if they're already running for this index
    await self.StopInstanceIfExists(InstanceID)
    
    Logger.Log(LogLevel.Log, f"Spinning up instance #{InstanceID}")
    self.SubProcess[InstanceID] = Process(target=CreateBotProcess, args=(RelayFileHandleLocation, InstanceID), name=f'Bot-{InstanceID}')
    self.SubProcess[InstanceID].start()

  async def StopInstanceIfExists(self, InstanceID:int):       
    if (InstanceID in self.SubProcess and self.SubProcess[InstanceID] is not None):
      ExistingProcess:Process = self.SubProcess[InstanceID]
      ExistingProcess.terminate()
      ExistingProcess.close()
      self.SubProcess[InstanceID] = None

  ### Command Processing & Utils ###    
  async def PublishAnnouncement(self, InMessage:str|Embed):
    if (ConfigData.IsDevelopment()):
      Logger.Log(LogLevel.Notice, "Announcement message was dropped because this instance is in development mode")
      return
    try:
      NewMessage:Message|None = None
      if (self.AnnouncementChannel is None):
        return
      
      if (type(InMessage) == Embed):
        NewMessage = await self.AnnouncementChannel.send(embed=InMessage)
      else:
        NewMessage = await self.AnnouncementChannel.send(str(InMessage))
      if (NewMessage is not None):
        await NewMessage.publish()
      elif (type(InMessage) == str):
        Logger.Log(LogLevel.Error, f"Could not publish message {str(InMessage)}! Did not send!")
      else:
        Logger.Log(LogLevel.Error, f"Could not publish message, as it did not send!")
    except HTTPException as ex:
      Logger.Log(LogLevel.Log, f"WARN: Unable to publish message to announcement channel {str(ex)}")

  ### Ban Handling ###
  async def HandleBanAction(self, TargetId:int, Sender:Member|User, Action:ModerationAction, ThreadId:int|None=None) -> BanAction:
    DatabaseAction:BanAction
    
    if (Action == ModerationAction.Ban):
      DatabaseAction = self.Database.AddBan(TargetId, Sender.name, Sender.id, ThreadId)
    elif (Action == ModerationAction.Unban):
      DatabaseAction = self.Database.RemoveBan(TargetId)
    else:
      Logger.Log(LogLevel.Error, f"An invalid moderation action was passed to HandleBanAction, {Action}")
      return BanAction.DBError
    
    # If we encountered an error, return said error, don't do anything else.
    if (DatabaseAction not in [BanAction.Banned, BanAction.Unbanned]):
      return DatabaseAction
    
    # Queue up tasks to fire later
    self.AddAsyncTask(self.CreateBanAnnouncement(TargetId, Action))
    self.AddAsyncTask(self.PropagateActionToServers(TargetId, Sender, Action))
    
    return DatabaseAction
  
  async def CreateBanAnnouncement(self, TargetId:int, ActionTaken:ModerationAction):
    if ActionTaken is ModerationAction.Ban or ActionTaken is ModerationAction.Unban:
      # Send a message to the announcement channel
      NewAnnouncement:Embed = await self.CreateBanEmbed(TargetId)
      NewAnnouncement.title = f"{str(ActionTaken)} in Progress"
      await self.PublishAnnouncement(NewAnnouncement)
  
  async def ReprocessBansForInstance(self, InstanceID:int, LastActions:int):
    if (InstanceID == self.BotID):
      await self.ReprocessInstance(LastActions)
    else:
      self.ClientHandler.SendReprocessInstanceBans(InstanceId=InstanceID, InNumToRetry=LastActions)

  async def ReprocessBansForServer(self, ServerId:int, LastActions:int=0, HandlingCooldown:bool=False) -> BanResult:
    TargetBotId:int|None = self.Database.GetBotIdForServer(ServerId)
    if (TargetBotId == self.BotID):
      return await self.ReprocessBans(ServerId, LastActions, HandlingCooldown)
    elif (TargetBotId is None):
      return BanResult.Error
    else:
      self.ClientHandler.SendReprocessBans(ServerId, InstanceId=TargetBotId, 
                                           InNumToRetry=LastActions, InHandlingCooldown=HandlingCooldown)
      return BanResult.Processed
    
  async def PropagateActionToServers(self, TargetId:int, Sender:Member|User, Action:ModerationAction):
    SenderName:str = Sender.name
    if (Action == ModerationAction.Ban):
      self.ClientHandler.SendBan(TargetId, SenderName)
    elif (Action == ModerationAction.Unban):
      self.ClientHandler.SendUnban(TargetId, SenderName)
    elif (Action == ModerationAction.Kick):
      self.ClientHandler.SendKick(TargetId, SenderName)
      
    await self.ProcessActionOnUser(TargetId, SenderName, Action)
    