# Database driver for ScamGuard
from BotEnums import BanAction, ModerationAction
from Logger import Logger, LogLevel
from Config import Config
import shutil, time, os
from BotDatabaseSchema import Ban, DeniedServers, ExhaustedServer, Server
from sqlalchemy import create_engine, Engine, select, URL, desc, asc, func
from sqlalchemy.orm import Session
from BotServerSettings import BotSettingsPayload
from datetime import timezone, datetime, timedelta
from typing import cast

ConfigData:Config = Config()

class DatabaseDriver():
  Database:Session = None # pyright: ignore[reportAssignmentType]

  ### Initialization/Teardown ###
  def __init__(self, *args, **kwargs):
    self.Open()

  def __del__(self):
    self.Close()

  def Open(self):
    self.Close()

    database_url = URL.create(
      'sqlite',
      username='',
      password='',
      host='',
      database=Config.GetDBFile(),
    )
    self.Database = Session(create_engine(database_url))

  def Close(self):
    if (self.IsConnected()):
      cast(Engine, self.Database.get_bind()).dispose()
      self.Database = None # pyright: ignore[reportAttributeAccessIssue]

  def IsConnected(self) -> bool:
    if (self.Database is not None):
      return True
    return False

  def HasBackupDirectory(self) -> bool:
    DestinationLocation = os.path.abspath(Config.GetBackupLocation())
    if (not os.path.exists(DestinationLocation)):
      return False

    return True

  def Backup(self) -> bool:
    if (not self.HasBackupDirectory()):
      Logger.Log(LogLevel.Warn, "Backup directory does not exist!!")
      return False

    if (self.IsConnected()):
      self.Database.commit()
      self.Close()

    # Copy the database file over here
    DestinationLocation = os.path.abspath(Config.GetBackupLocation())
    shutil.copy(os.path.relpath(Config.GetDBFile()), DestinationLocation)

    # Rename the file
    NewFileName:str = time.strftime("%Y%m%d-%H%M%S.db")
    NewFile = os.path.join(DestinationLocation, NewFileName)
    OriginalFile = os.path.join(DestinationLocation, Config.GetDBFile())
    os.rename(OriginalFile, NewFile)
    Logger.Log(LogLevel.Log, f"Current database has been backed up to new file {NewFileName}")
    self.Open()
    return True

  def CleanupBackups(self):
    if (not self.HasBackupDirectory()):
      return

    BackupsCleaned:int = 0
    OlderThan:float = ConfigData["RemoveDaysOldBackups"]
    BackupLocation = os.path.abspath(Config.GetBackupLocation())
    FileList = os.listdir(BackupLocation)
    FilesOlderThan:float = time.time() - OlderThan * 86400
    for File in FileList:
      FileLocation:str = os.path.join(BackupLocation, File)
      FileModTime:float = os.stat(FileLocation).st_mtime
      if (FileModTime < FilesOlderThan):
        if (os.path.isfile(FileLocation)):
          Logger.Log(LogLevel.Log, f"Removing file {File}")
          os.remove(FileLocation)
          BackupsCleaned += 1

    Logger.Log(LogLevel.Log, f"Cleaned up {BackupsCleaned} backups older than {OlderThan} days!")

  ### Adding/Updating/Removing Server Entries ###
  def AddBotGuilds(self, ListOwnerAndServerTuples, BotID:int):
    BotAdditionUpdates:list[Server] = []
    for Entry in ListOwnerAndServerTuples:
      server = Server(
        bot_instance_id = BotID,
        discord_server_id = Entry.id,
        owner_discord_user_id = Entry.owner_id,
        activator_discord_user_id = -1
      )
      BotAdditionUpdates.append(server)

    self.Database.bulk_save_objects(BotAdditionUpdates)
    self.Database.commit()

    Logger.Log(LogLevel.Notice, f"Bot #{BotID} had {len(BotAdditionUpdates)} new server updates")

  def SetNewServerOwner(self, ServerId:int, NewOwnerId:int, BotId:int):
    stmt = select(Server).where((Server.discord_server_id==ServerId) & (Server.bot_instance_id==BotId))
    server = self.Database.scalars(stmt).first()

    if (server is None):
      Logger.Log(LogLevel.Warn, f"Bot #{BotId} attempted to set new owner on non-assigned server: {ServerId}")
      return

    server.owner_discord_user_id = str(NewOwnerId)

    self.Database.add(server)
    self.Database.commit()

  def SetFromServerSettings(self, ServerId:int, ServerSettings:BotSettingsPayload):
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    serverToChange = self.Database.scalars(stmt).first()

    if (serverToChange is None):
      Logger.Log(LogLevel.Warn, f"Bot attempted to set channel updates to {ServerId}, but server doesn't exist in db!")
      return

    serverToChange.message_channel = ServerSettings.GetMessageID()
    serverToChange.has_webhooks = 1 if ServerSettings.WantsWebhooks else 0
    serverToChange.kick_sus_users = 1 if ServerSettings.KickSusUsers else 0
    self.Database.add(serverToChange)
    self.Database.commit()


  def RemoveServerEntry(self, ServerId:int, BotId:int):
    stmt = select(Server).where((Server.discord_server_id==ServerId) & (Server.bot_instance_id==BotId))
    server = self.Database.scalars(stmt).first()

    if (server is None):
      Logger.Log(LogLevel.Warn, f"Bot #{BotId} attempted to remove an non-assigned server: {ServerId}")
      return

    # Remove any cooldown entries if we exist in there
    self.RemoveServerCooldown(ServerId)

    self.Database.delete(server)
    self.Database.commit()

  def ToggleServerBan(self, ServerId:int, NewStatus:bool):
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return

    server.should_ban_in = int(NewStatus)
    self.Database.add(server)
    self.Database.commit()

  def ToggleServerReport(self, ServerId:int, NewStatus:bool):
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return

    server.can_report = int(NewStatus)
    self.Database.add(server)
    self.Database.commit()

  def SetBotActivationForOwner(self, Servers:list[int], IsActive:bool, BotId:int, OwnerId:int=-1, ActivatorId:int=-1):
    NumActivationChanges = 0
    NumActivationAdditions = 0
    ActiveVal = int(IsActive)

    for ServerId in Servers:
      # If we're not in the server, and we've been given an OwnerId, then create the server
      # IsActive SHOULD be False when passed in this manner
      if (not self.IsInServer(ServerId)):
        if (OwnerId > 0):
          NumActivationAdditions += 1

          serverToChange = Server(
            bot_instance_id = BotId,
            discord_server_id = ServerId,
            owner_discord_user_id = OwnerId,
            activation_state = ActiveVal,
            activator_discord_user_id = -1,
          )

          self.Database.add(serverToChange)
      # Otherwise, fetch the existing server and update it
      else:
        NumActivationChanges += 1

        stmt = select(Server).where(Server.discord_server_id==ServerId)
        serverToChange = self.Database.scalars(stmt).first()
        if (serverToChange is None):
          Logger.Log(LogLevel.Warn, f"Attempted to change server info for {ServerId} but DB entry was missing!")
          return

        serverToChange.activation_state = ActiveVal
        serverToChange.activator_discord_user_id = str(ActivatorId)

        self.Database.add(serverToChange)


    if (NumActivationAdditions > 0):
      Logger.Log(LogLevel.Debug, f"We have {NumActivationAdditions} additions")

    if (NumActivationChanges > 0):
      Logger.Log(LogLevel.Notice, f"Server activation changed in {NumActivationChanges} servers to {str(IsActive)} by {ActivatorId}")

    self.Database.commit()

  ### Server Forbidden ###
  def ForbidServerActivation(self, ServerId: int, UserId: int):
    if (self.IsServerForbidden(ServerId)):
      return False

    NewForbiddenServer = DeniedServers(
      discord_server_id = ServerId,
      adjudicar_handle = UserId,
    )

    self.Database.add(NewForbiddenServer)
    self.Database.commit()
    return True

  def RemoveForbiddenActivation(self, ServerId: int):
    stmt = select(DeniedServers).where(DeniedServers.discord_server_id==ServerId)
    serverban = self.Database.scalars(stmt).first()
    if (serverban is None):
      return False

    self.Database.delete(serverban)
    self.Database.commit()
    return True

  def IsServerForbidden(self, ServerId: int):
    stmt = select(DeniedServers).where(DeniedServers.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return False
    return True

  ### Reconcile Servers ###
  def ReconcileServers(self, Servers, BotId:int):
    NewAdditions = []
    # Discord Guild IDs that we will later use to remove
    ServersIn:list[int] = []
    # Control server id
    ControlServerID:int = ConfigData["ControlServer"]
    # Loop through all the servers we are in and grab their guild ids
    for DiscordServer in Servers:
      # Check to see if we know about this server already.
      if (not self.IsInServer(DiscordServer.id)):
        NewAdditions.append(DiscordServer)

      # Ignore the control server but add any other servers to this list.
      if (DiscordServer.id != ControlServerID):
        ServersIn.append(DiscordServer.id)

    # Add any new servers we have found
    if (len(NewAdditions) > 0):
      self.AddBotGuilds(NewAdditions, BotId)

    # Check the current list of servers vs what the database has
    # to see if there are any servers we need to remove
    stmt = select(Server).where((Server.discord_server_id!=ControlServerID) & (Server.bot_instance_id==BotId))
    AllServersWithThisBot = list(self.Database.scalars(stmt).all())
    Logger.Log(LogLevel.Debug, f"Bot #{BotId} server count: {len(AllServersWithThisBot)} with discord in {len(ServersIn)}")
    # Go through all the servers in the database for this bot
    for InServerId in AllServersWithThisBot:
      ServerId = int(InServerId.discord_server_id)
      try:
        # If we are in the server, then we remove the entry from the list of servers
        # we are in. This is because this list will be used later to remove entries that
        # mismatch
        ServersIn.remove(ServerId)
      except ValueError:
        # If the entry fails to be removed from the discord guild list, then
        # it's a floating entry in the database and should be removed.
        ServersIn.append(ServerId)
        continue

    if (len(ServersIn) > 0):
      Logger.Log(LogLevel.Notice, f"Bot needs to reconcile {len(ServersIn)} servers from the list")
    else:
      Logger.Log(LogLevel.Debug, "Bot does not need to remove any servers from last run.")
      return

    for ServerToRemove in ServersIn:
      self.RemoveServerEntry(ServerToRemove, BotId)
      Logger.Log(LogLevel.Warn, f"Bot #{BotId} has been removed from server {ServerToRemove}")

  ### Query Status ###
  def IsInServer(self, ServerId:int) -> bool:
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return False
    return True

  def IsActivatedInServer(self, ServerId:int) -> bool:
    if (not self.IsInServer(ServerId)):
      return False

    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return False

    if (server.activation_state > 0):
      return True

    return False

  def CanServerReport(self, ServerId:int) -> bool:
    if (not self.IsInServer(ServerId)):
      return False

    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()
    if (server is None):
      return False

    if (server.can_report):
      return True

    return False

  def DoesBanExist(self, TargetId:int) -> bool:
    stmt = select(Ban).where(Ban.discord_user_id==TargetId)
    result = self.Database.scalars(stmt).first()

    if (result is None):
      return False

    return True

  # Returns ban information
  def GetBanInfo(self, TargetId:int) -> Ban|None:
    stmt = select(Ban).where(Ban.discord_user_id==TargetId)
    return self.Database.scalars(stmt).first()

  # Returns server information
  def GetServerInfo(self, ServerId:int) -> Server|None:
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    return self.Database.scalars(stmt).first()

  ### Adding/Removing Bans ###
  def AddBan(self, TargetId:int, BannerName:str, BannerId:int, ThreadId:int|None) -> BanAction:
    if (self.DoesBanExist(TargetId)):
      return BanAction.Duplicate

    ban = Ban(
      discord_user_id = TargetId,
      assigner_discord_user_id = BannerId,
      assigner_discord_user_name = BannerName
    )

    if (ThreadId is not None):
      ban.evidence_thread = ThreadId

    self.Database.add(ban)
    self.Database.commit()

    return BanAction.Banned

  def RemoveBan(self, TargetId:int) -> BanAction:
    if (not self.DoesBanExist(TargetId)):
      return BanAction.NotExist

    stmt = select(Ban).where(Ban.discord_user_id==TargetId)
    ban = self.Database.scalars(stmt).first()

    self.Database.delete(ban)
    self.Database.commit()

    return BanAction.Unbanned

  ### Updating Ban Data ###
  def SetEvidenceThread(self, TargetId:int, ThreadId:int):
    if (TargetId <= 0 or ThreadId <= 0):
      return

    if (not self.DoesBanExist(TargetId)):
      return

    stmt = select(Ban).where(Ban.discord_user_id==TargetId)
    if (stmt is None):
      return

    banToChange = self.Database.scalars(stmt).first()
    if (banToChange is None):
      return

    banToChange.evidence_thread = ThreadId
    self.Database.add(banToChange)

  ### Getting Server Information ###
  def GetAllServersOfOwner(self, OwnerId:int) -> list[Server]:
    stmt = select(Server).where(Server.owner_discord_user_id==OwnerId)
    servers = self.Database.scalars(stmt).all()

    if (not len(servers)):
      Logger.Log(LogLevel.Warn, f"Failed to load servers for given discord user id of: {OwnerId}!")

    return list(servers)

  def GetOwnerOfServer(self, ServerId:int) -> int|None:
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()

    if (server is None):
      Logger.Log(LogLevel.Warn, f"Tried to load owner for non-existent server: {ServerId}!")
      return None

    return int(server.owner_discord_user_id)

  def GetBotIdForServer(self, ServerId:int) -> int|None:
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()

    if (server is None):
      Logger.Log(LogLevel.Warn, f"Tried to load bot instance for non-existent server: {ServerId}!")
      return None

    return int(server.bot_instance_id)

  def GetChannelIdForServer(self, ServerId:int) -> int|None:
    stmt = select(Server).where(Server.discord_server_id==ServerId)
    server = self.Database.scalars(stmt).first()

    if (server is None):
      Logger.Log(LogLevel.Warn, f"Tried to load bot instance for non-existent server: {ServerId}!")
      return None

    ReturnValue:int = int(server.message_channel)
    if (ReturnValue == 0):
      return None

    return ReturnValue

  def GetAllBans(self, NumLastActions:int=0) -> list[Ban]:
    stmt = select(Ban)

    if (NumLastActions > 0):
      stmt = stmt.order_by(desc(Ban.created_at)).limit(NumLastActions)
    else:
      stmt = stmt.order_by(asc(Ban.created_at))

    return list(self.Database.scalars(stmt).all())

  def GetAllServers(self, FilterOnlyActivated:bool=False, OfInstance:int=-1, FilterBanability:bool=False, FilterKicking:bool=False) -> list[Server]:
    stmt = select(Server)

    if (FilterOnlyActivated):
      stmt = stmt.where(Server.activation_state==True)

    if (OfInstance > -1):
      stmt = stmt.where(Server.bot_instance_id==OfInstance)

    if (FilterBanability):
      stmt = stmt.where(Server.should_ban_in==1)

    if (FilterKicking):
      stmt = stmt.where(Server.kick_sus_users==1)

    return list(self.Database.scalars(stmt).all())

  def GetAllActivatedServers(self, OfInstance:int=-1) -> list[Server]:
    return self.GetAllServers(True, OfInstance)

  def GetAllActivatedServersForAction(self, OfInstance:int=-1, Action:ModerationAction=ModerationAction.Nothing) -> list[Server]:
    match Action:
      case ModerationAction.Ban | ModerationAction.Unban:
        return self.GetAllServers(True, OfInstance, True)
      case ModerationAction.Kick:
        return self.GetAllServers(True, OfInstance, False, True)

    return []

  def GetAllDeactivatedServers(self) -> list[Server]:
    ControlServerID:int = ConfigData["ControlServer"]
    # Always ignore the control server
    stmt = select(Server).where(Server.activation_state==False).where(Server.discord_server_id!=ControlServerID)

    return list(self.Database.scalars(stmt).all())

  ### Cooldown ###
  def GetServerCooldown(self, ServerId:int) -> ExhaustedServer|None:
    stmt = select(ExhaustedServer).where(ExhaustedServer.discord_server_id==ServerId)
    return self.Database.scalars(stmt).first()

  def IsServerInCooldown(self, ServerId:int) -> bool:
    return self.GetServerCooldown(ServerId) is not None

  def IsProcessingServerCooldown(self, ServerId:int) -> bool:
    ServerObj:ExhaustedServer|None = self.GetServerCooldown(ServerId)
    if (ServerObj is None):
      return False

    return ServerObj.is_processing > 0

  def SetProcessingServerCooldown(self, ServerId:int, NewFlag:bool):
    exUpdate:ExhaustedServer|None = self.GetServerCooldown(ServerId)
    if (exUpdate is None):
      return

    exUpdate.is_processing = NewFlag
    self.Database.add(exUpdate)
    self.Database.commit()

  def UpdateServerCooldown(self, ServerId:int, NumCompleted:int) -> int:
    exhaustedUpdate:ExhaustedServer|None = self.GetServerCooldown(ServerId)

    # Create if it doesn't exist.
    if (exhaustedUpdate is None):
      exhaustedUpdate = ExhaustedServer()
      exhaustedUpdate.discord_server_id = ServerId

    if (exhaustedUpdate.current_pos is not None and exhaustedUpdate.current_pos > 0):
      exhaustedUpdate.current_pos = exhaustedUpdate.current_pos + NumCompleted
    else:
      exhaustedUpdate.current_pos = NumCompleted

    exhaustedUpdate.is_processing = False
    self.Database.add(exhaustedUpdate)
    self.Database.commit()

    return exhaustedUpdate.current_pos

  def RemoveServerCooldown(self, ServerId:int):
    server = self.GetServerCooldown(ServerId)
    if (server is None):
      return

    self.Database.delete(server)
    self.Database.commit()

  def GetExhaustedServers(self, OverrideTime:bool=False):
    stmt = select(ExhaustedServer)

    if (OverrideTime is False):
      CooldownWaitTime:int = ConfigData["CooldownWaitInHours"]
      BeginningOfTime:datetime = datetime.fromtimestamp(0)
      ADayAgo:timedelta = timedelta(hours=CooldownWaitTime)
      ADayAgoTime:datetime = datetime.now(timezone.utc) - ADayAgo
      print(ADayAgoTime)
      stmt = stmt.where(ExhaustedServer.last_run.between(BeginningOfTime, ADayAgoTime))
    return self.Database.scalars(stmt).all()

  def GetAllExhaustedServers(self):
    return self.Database.scalars(select(ExhaustedServer)).all()

  ### Stats ###
  def GetNumBans(self) -> int:
    stmt = select(func.count()).select_from(Ban)
    return self.Database.scalars(stmt).first() or 0

  def GetNumActivatedServers(self) -> int:
    stmt = select(func.count()).select_from(Server).where(Server.activation_state==True)
    return self.Database.scalars(stmt).first() or 0

  def GetNumServers(self) -> int:
    stmt = select(func.count()).select_from(Server)
    return self.Database.scalars(stmt).first() or 0

  def GetNumExhaustedServers(self) -> int:
    stmt = select(func.count()).select_from(ExhaustedServer)
    return self.Database.scalars(stmt).first() or 0