# This is the base class for all of our Discord bots
# Any code that needs to be referenced by sub-instances and the main instance of ScamGuard should go here
# Usually for any core shared features. 
# 
# This separation was originally due to Discord politics when ScamGuard was first developed.
# Since then, everything can potentially envelop back into the main instance instead.
from Logger import Logger, LogLevel
from BotEnums import BanResult, ChannelPostPermissions, RelayMessageType, ModerationAction
from Config import Config
from BotConnections import RelayClient
import discord, asyncio, json, aiohttp, io
from discord.ext import tasks
from BotDatabase import DatabaseDriver
from queue import SimpleQueue
from BotCommands import GlobalScamCommands
from CommandHelpers import CommandErrorHandler
from ServerActivation import ScamGuardServerSetup
from TextWrapper import TextLibrary
from typing import Sequence, cast

__all__ = ["DiscordBot"]

ConfigData:Config=Config()
Messages:TextLibrary = TextLibrary()

class DiscordBot(discord.Client):
  # Discord Channel that serves for notifications on bot activity/errors/warnings
  NotificationChannel = None
  ActivationChannel = None
  # Channel to send updates as to when someone is banned/unbanned
  AnnouncementChannel = None
  ReportChannel = None
  ReportChannelTag = None
  ServerSetupHelper = None
  BotID:int = -1

  def __init__(self, RelayFileLocation, AssignedBotID:int=-1):
    self.Database:DatabaseDriver = DatabaseDriver()
    # This gets set properly down below.
    self.ClientHandler:RelayClient = None # pyright: ignore[reportAttributeAccessIssue]
    # initialize other values
    self.AsyncTasks = set()
    self.LoggingMessageQueue = SimpleQueue()
    self.ServerSetupHelper = ScamGuardServerSetup(self)
    self.BotID = AssignedBotID
    intents = discord.Intents.none()
    intents.guilds = True
    intents.bans = True
    
    if (ConfigData["AllowWebhookInstall"]):
      intents.webhooks = True
    
    # bring in these intents so we can get an idea of shared servers scamcheck returns.
    # Do note, if these are enabled, the bot will take about 1 min to start up.
    if (ConfigData["ScamCheckShowsSharedServers"]):
      intents.members = True
      intents.presences = True
    elif (ConfigData["AllowSuspiciousUserKicks"]):
      intents.members = True

    super().__init__(intents=intents)
    self.Commands = discord.app_commands.CommandTree(self)
    self.Commands.on_error = CommandErrorHandler
    
    self.SetupClientConnection(RelayFileLocation)

  def __del__(self):
    Logger.Log(LogLevel.Notice, f"Closing the discord scam bot instance #{self.BotID} {self}")
    
  def SetupClientConnection(self, RelayLocation):
    Logger.Log(LogLevel.Log, f"Instance #{self.BotID} starting relay client")
    
    if (self.ClientHandler is None):
      self.ClientHandler = RelayClient(RelayLocation, self.BotID)
    
    Logger.Log(LogLevel.Verbose, f"Instance #{self.BotID} is setting up function registration")
    # Register functions for handling basic client actions
    self.ClientHandler.RegisterFunction(RelayMessageType.BanUser, self.BanUser)
    self.ClientHandler.RegisterFunction(RelayMessageType.UnbanUser, self.UnbanUser)
    self.ClientHandler.RegisterFunction(RelayMessageType.Kick, self.KickUser)
    self.ClientHandler.RegisterFunction(RelayMessageType.ReprocessInstance, self.ScheduleReprocessInstance)
    self.ClientHandler.RegisterFunction(RelayMessageType.ReprocessBans, self.ScheduleReprocessBans)
    self.ClientHandler.RegisterFunction(RelayMessageType.LeaveServer, self.LeaveServer)
    self.ClientHandler.RegisterFunction(RelayMessageType.ProcessServerActivation, self.ProcessServerActivationForInstance)
    self.ClientHandler.RegisterFunction(RelayMessageType.Ping, self.PostPongMessage)
      
  async def setup_hook(self):
    CommandControlServer=discord.Object(id=ConfigData["ControlServer"])
    
    GlobalCommands = GlobalScamCommands(name="scamguard",
                      description="Handles ScamGuard commands", 
                      # Allow only users that can submit bans
                      default_permissions=discord.Permissions(1 << 2),
                      extras={"instance": self})
    
    self.Commands.add_command(GlobalCommands)
    if (ConfigData.IsDevelopment()):
      # This copies the global commands over to your guild.
      self.Commands.copy_global_to(guild=CommandControlServer)
      await self.Commands.sync(guild=CommandControlServer)
      await self.Commands.sync()
    else:
      # Remove the report and check commands from any control servers
      self.Commands.remove_command(GlobalCommands, guild=CommandControlServer) # pyright: ignore[reportArgumentType]
      await self.Commands.sync(guild=CommandControlServer)
      await self.Commands.sync()
      
    await super().setup_hook()
     
  ### Event Queueing ###
  def AddAsyncTask(self, TaskToComplete):
    TaskName:str = str(TaskToComplete)
    try:
      CurrentLoop = asyncio.get_running_loop()
    except RuntimeError:
      Logger.Log(LogLevel.Log, f"Encountered an error while trying to add async task {TaskName}")
      return

    Logger.Log(LogLevel.Log, f"Added task {TaskName} to task queue")
    NewTask = CurrentLoop.create_task(TaskToComplete, name=TaskName)
    self.AsyncTasks.add(NewTask)
    NewTask.add_done_callback(self.AsyncTasks.discard)
  
  ### Discord Tasks Handling ###
  @tasks.loop(seconds=0.5)
  async def HandleRelayMessages(self):
    await self.ClientHandler.RecvMessage()
    
  @HandleRelayMessages.before_loop
  async def BeforeClientRelay(self):
    await self.wait_until_ready()
    self.ClientHandler.SendHello()
  
  @tasks.loop(seconds=1)
  async def PostLogMessages(self):
    while (not self.LoggingMessageQueue.empty()):
      Message:str = self.LoggingMessageQueue.get_nowait()
      # Truncate posted messages via queue
      if (len(Message) > 2000):
        Message = (Message[:1997] + "...")
      try:
        if (self.NotificationChannel is not None):
          await cast(discord.TextChannel, self.NotificationChannel).send(Message)
      except discord.HTTPException as ex:
        Logger.Log(LogLevel.Log, f"WARN: Unable to send message to notification channel {str(ex)}")
      
  @PostLogMessages.before_loop
  async def BeforePostLogMessages(self):
    await self.wait_until_ready()
      
  ### Config Handling ###
  def ProcessConfig(self, ShouldReload:bool):
    if (ShouldReload):
      ConfigData.Load()
        
    if (ConfigData.IsValid("NotificationChannel", int)):
      self.NotificationChannel = self.get_channel(ConfigData["NotificationChannel"])
      
    if (ConfigData.IsValid("ActivationChannel", int)):
      self.ActivationChannel = self.get_channel(ConfigData["ActivationChannel"])
      
    if (ConfigData.IsValid("AnnouncementChannel", int)):
      self.AnnouncementChannel = cast(None|discord.TextChannel, self.get_channel(ConfigData["AnnouncementChannel"]))
      
    if (ConfigData.IsValid("ReportChannel", int)):
      ReportChannel = self.get_channel(ConfigData["ReportChannel"])
      if (ReportChannel is not None):
        self.ReportChannel = cast(discord.ForumChannel, ReportChannel)
        for tag in self.ReportChannel.available_tags:
          if (tag.name == ConfigData["ReportChannelTag"]):
            self.ReportChannelTag = tag
            break

    Logger.Log(LogLevel.Notice, f"Bot (#{self.BotID}) configs applied")
    
  ### Leaving Servers ###
  def LeaveServer(self, ServerId:int) -> bool:
    BotServerIsIn:int|None = self.Database.GetBotIdForServer(ServerId)
    if (BotServerIsIn is None):
      return False
    
    # If the bot is in any server we know about
    if (BotServerIsIn != -1):
      # If the bot id == 0, then it is the control bot.
      if (BotServerIsIn == self.BotID):
        self.AddAsyncTask(self.ForceLeaveServer(ServerId))
      else:
        self.ClientHandler.SendLeaveServer(ServerId, BotServerIsIn)
      return True
    return False
  
  async def ForceLeaveServer(self, ServerId:int):
    ServerToLeave:discord.Guild|None = self.get_guild(ServerId)
    if (ServerToLeave is not None):
      ServerInfoStr:str = self.GetServerInfoStr(ServerToLeave)
      try:
        await ServerToLeave.leave()
        Logger.Log(LogLevel.Notice, f"We have left the server {ServerInfoStr}")
      except discord.errors.HTTPException:
        Logger.Log(LogLevel.Verbose, f"Could not leave server {ServerInfoStr}, we are getting rate limited")
    else:
      Logger.Log(LogLevel.Warn, f"Could not find server with id {ServerId}, id is invalid")        
   
  ### Discord Permission/Data Checking/Lookup ###       
  async def GetServersWithElevatedPermissions(self, UserID:int, SkipActivated:bool):
    # This was used for the old /activate method before we had the remote activation feature
    # this path doesn't really get called anymore
    ServersWithPermissions = []
    for Server in self.guilds:
      ServerId:int = Server.id
      if (SkipActivated and self.Database.IsActivatedInServer(ServerId)):
        continue
      
      ServerStr:str = self.GetServerInfoStr(Server)
      
      # Owners are an easy add
      if (Server.owner_id == UserID):
        ServersWithPermissions.append(ServerId)
      else:
        GuildMember = await self.LookupMember(UserID, ServerToInspect=Server)
        if (GuildMember is not None):
          if (self.UserHasElevatedPermissions(GuildMember)):
            ServersWithPermissions.append(ServerId)
            Logger.Log(LogLevel.Log, f"User [{UserID}] is in server {ServerStr} with permissions")
          else:
            Logger.Log(LogLevel.Verbose, f"User [{UserID}] does not have elevated permissions in {ServerStr}")
        else:
          Logger.Log(LogLevel.Verbose, f"User [{UserID}] is not in server {ServerStr}")
    return ServersWithPermissions
  
  async def UserAccountExists(self, UserID:int) -> bool:
    try:
      await self.fetch_user(UserID)
      return True
    except discord.NotFound:
      return False
    except discord.HTTPException:
      return False
  
  async def LookupMember(self, UserID:int, ServerToInspect:discord.Guild) -> discord.Member|None:
    User = await self.LookupUser(UserID, ServerToInspect)
    return cast(None|discord.Member, User)

  async def LookupUser(self, UserID:int, ServerToInspect:discord.Guild|None=None) -> discord.User|discord.Member|None:
    GivenServer:bool = (ServerToInspect is not None)
    try:
      if (GivenServer):
        return await ServerToInspect.fetch_member(UserID)
      else:
        return await self.fetch_user(UserID)
    except discord.Forbidden:
      Logger.CLog(GivenServer, LogLevel.Error, f"Bot does not have access to {ServerToInspect.name}") # pyright: ignore[reportOptionalMemberAccess]
    except discord.NotFound as ex:
      if (GivenServer):
        Logger.Log(LogLevel.Debug, f"Could not find user {UserID} in {ServerToInspect.name}")
      else:
        Logger.Log(LogLevel.Warn, f"UserID {UserID} was not found with error {str(ex)}")
    except discord.HTTPException as httpEx:
      Logger.Log(LogLevel.Warn, f"Failed to fetch user {UserID}, got {str(httpEx)}")
    return None
  
  def UserHasElevatedPermissions(self, User:discord.Member) -> bool:
    # This is the old method of /activate that's no longer used. It is deprecated.
    if (User is None):
      return False
     
    UserPermissions:discord.Permissions = User.guild_permissions 
    if (UserPermissions.administrator or (UserPermissions.manage_guild and UserPermissions.ban_members)):
      return True
    return False
  
  ### Activating Servers ###
  async def ActivateServerInstance(self, UserID:int, ServerID:int):
    if (self.Database.GetBotIdForServer(ServerID) != self.BotID):
      return
    
    Logger.Log(LogLevel.Notice, f"Activating ServerID {ServerID} from user {UserID}")
    self.Database.SetBotActivationForOwner([ServerID], True, self.BotID, ActivatorId=UserID)
    self.AddAsyncTask(self.ReprocessBans(ServerID))
    
  def ProcessServerActivationForInstance(self, UserId:int, ServerId:int):
    self.AddAsyncTask(self.ActivateServerInstance(UserId, ServerId))

  ### Starting execution ###
  async def InitializeBotRuntime(self):
    self.ProcessConfig(False)
    
    # Set status
    ActivityObj = None
    IdPrefix:str = f"ID: #{self.BotID} "
    if (ConfigData.IsDevelopment()):
      ActivityObj = discord.CustomActivity(name=IdPrefix + Messages["activity"]["development"])
    else:
      ActivityObj = discord.CustomActivity(name=IdPrefix + Messages["activity"]["default"])
    await self.change_presence(status=discord.Status.online, activity=ActivityObj)

    # Set logger callbacks for notifications
    if (self.NotificationChannel is not None):
      Logger.SetNotificationCallback(self.PostNotification)

    self.Database.ReconcileServers(self.guilds, self.BotID)
    
    # If our task is not already running, start it. 
    # We do this check because on_ready could be called again on reconnections.
    if (not self.HandleRelayMessages.is_running()):
      self.HandleRelayMessages.start()
      
    if (not self.PostLogMessages.is_running()):
      self.PostLogMessages.start()

    Logger.Log(LogLevel.Notice, f"Bot (#{self.BotID}) has started! Is Development? {ConfigData.IsDevelopment()}")
  
  ### Discord Eventing ###        
  async def on_ready(self):
    self.AddAsyncTask(self.InitializeBotRuntime())
  
  async def on_guild_update(self, PriorUpdate:discord.Guild, NewUpdate:discord.Guild):
    NewOwnerId:int|None = NewUpdate.owner_id
    if (NewOwnerId is None):
      return
    
    if (PriorUpdate.owner_id != NewOwnerId):
      self.Database.SetNewServerOwner(NewUpdate.id, NewOwnerId, self.BotID)
      Logger.Log(LogLevel.Notice, f"Detected that the server {self.GetServerInfoStr(PriorUpdate)} is now owned by {NewOwnerId}")
      
  async def on_guild_join(self, server:discord.Guild):
    OwnerName:str = "Admin"
    if (server.owner is not None):
      OwnerName = server.owner.display_name
      
    ServerStr:str = self.GetServerInfoStr(server)
    # Prevent ourselves from being added to a server we are already in.
    if (self.Database.IsInServer(server.id)):
      Logger.Log(LogLevel.Notice, f"Bot #{self.BotID} was attempted to be added to server {ServerStr} but already in there")
      # TODO: Print a message to the user?
      await server.leave()
      return
    
    # If a server is marked as forbidden, leave the server
    if (self.Database.IsServerForbidden(server.id)):
      Logger.Log(LogLevel.Notice, f"Forbidden server {ServerStr} has {len(server.roles)} roles:")
      # Get the member role list, to dump ids
      for RoleCheck in server.roles:
        RoleStr = f"{RoleCheck.name}({len(RoleCheck.members)}): "
        for member in RoleCheck.members:
          RoleStr = RoleStr + f"{member.id}, "
        Logger.Log(LogLevel.Notice, f"* {RoleStr}")

      await server.leave()
      return

    self.Database.SetBotActivationForOwner([server.id], False, self.BotID, OwnerId=server.owner_id or 0)
    if (ConfigData["PostWelcomeMessages"]):
      self.AddAsyncTask(self.PostFirstTimeMessage(server.id))
    Logger.Log(LogLevel.Notice, f"Bot (#{self.BotID}) has joined server {ServerStr} of owner {OwnerName}[{server.owner_id}]")
    
  async def on_guild_remove(self, server:discord.Guild):
    OwnerName:str = "Admin"
    if (server.owner is not None):
      OwnerName = server.owner.display_name
    
    self.Database.RemoveServerEntry(server.id, self.BotID)
    Logger.Log(LogLevel.Notice, f"Bot (#{self.BotID}) has been removed from server {self.GetServerInfoStr(server)} of owner {OwnerName}[{server.owner_id}]")
    
  ### Report Handling ###
  async def PostScamReport(self, ReportData):
    if (self.ReportChannel is None or self.ReportChannelTag is None):
      return
    
    ImageFormats = ("image/png", "image/jpeg", "image/jpg", "image/bmp", "image/webp")
    PostEmbeds:list[discord.Embed] = []
    PostFiles:list[discord.File] = []
    if (ConfigData["AutoEmbedScamCheckOnReport"]):
      PostEmbeds.append(await self.CreateBanEmbed(ReportData['ReportedUserId']))
    
    ReasoningString:str = ""
    if (len(ReportData["Reasoning"])):
      ReasoningString = f"Reasoning: {ReportData['Reasoning']}"
      
    ReportUserId = ReportData['ReportedUserId']
    ReportUserHandle = ReportData['ReportedUserName']
    ReportUserName = ReportData['ReportedUserGlobalName']
    
    # Format the message that is going to be posted!
    ReportContent:str = f"""
    User ID: `{ReportUserId}`
Username: {ReportUserName}
Type Of Scam: {ReportData['TypeOfScam']}
{ReasoningString}
    
Reported Remotely By: {ReportData['ReportingUserName']}[{ReportData['ReportingUserId']}] from {ReportData['ReportedServer']}[{ReportData['ReportedServerId']}]

Failed Copied Evidence Links:

"""
    # Format all the image embeds into the list properly
    NumEvidences:int = len(PostFiles)
    
    async with aiohttp.ClientSession() as session:
      HadCopyFailure:bool = False
      for Evidence in ReportData["Evidence"]:
        if (NumEvidences >= 10):
          break
        
        if (Evidence.startswith("https")):
          async with session.get(Evidence) as response:
            if (response.status != 200):
              Logger.Log(LogLevel.Warn, f"Bot (#{self.BotID}) could not download file {Evidence} for report {ReportUserId}")
              ReportContent += f"* {Evidence}\n"
              HadCopyFailure = True
              continue
            ContentType = response.headers['content-type']
            if ContentType not in ImageFormats:
              Logger.Log(LogLevel.Warn, f"Bot (#{self.BotID}) was given {Evidence} for {ReportUserId} but that is of type {ContentType} which is not an image")
              continue
            EvidenceData = io.BytesIO(await response.read())
            NewFile:discord.File = discord.File(EvidenceData, f'Evidence{NumEvidences}.png')
            PostFiles.append(NewFile)
            NumEvidences += 1
      if (not HadCopyFailure):
        ReportContent += "None"
    try:
      if (self.ReportChannel is None):
        return
      
      NewThread:discord.channel.ThreadWithMessage = await self.ReportChannel.create_thread(name=ReportData["ReportedUserGlobalName"],
                     content=ReportContent,
                     applied_tags=[self.ReportChannelTag],
                     reason=f"ScamReport from {ReportData['ReportingUserName']}[{ReportData['ReportingUserId']}]",
                     embeds=PostEmbeds, files=PostFiles)
      
      # Update the user with the ScamGuard thread that was created
      ThreadEmbed:discord.Embed = self.CreateBaseEmbed(f"Report created for {ReportUserName}")
      ThreadEmbed.add_field(name="User Name", value=f"{ReportUserName}")
      ThreadEmbed.add_field(name="User Handle", value=f"{ReportUserHandle}")
      ThreadEmbed.add_field(name="User ID", value=f"{ReportUserId}", inline=False)
      ThreadEmbed.add_field(name="Thread Link (for updates)", value=f"{NewThread.thread.mention}", inline=False)
      ThreadEmbed.set_footer(text="Can't see the thread? Join the server: https://scamguard.app/discord")
      await ReportData["Webhook"].send(embed=ThreadEmbed, ephemeral=False)
      
    except discord.NotFound:
      Logger.Log(LogLevel.Warn, "Unable to update the original command that sent a report with a new embed, the followup has expired.")
    except discord.Forbidden:
      Logger.Log(LogLevel.Error, f"Unable to make report on user {ReportData['ReportedUserId']} as we do not have permissions to do so!")
    except discord.HTTPException as ex:
      Logger.Log(LogLevel.Error, f"Unable to make report on user {json.dumps(ReportData)} with exception {str(ex)}")
  
  ### First Time Message Posting ###
  async def PostFirstTimeMessage(self, ServerId:int):
    CanCreatePrivateThread:bool = ConfigData["UseThreadsForWelcomeMessage"]
    Server:discord.Guild|None = self.get_guild(ServerId)
    if (Server is None):
      Logger.Log(LogLevel.Warn, f"Server {ServerId} was none")
      return

    # Find if we can even use threads (determined by if we can mention any of the moderators)
    MentionStr:str = ""
    # Need this to actually notify people 
    MentionPerms:discord.AllowedMentions = discord.AllowedMentions(roles=True, users=True)
    MentionRoles:Sequence[discord.Role] = []
    # Find all the roles that can ban members, we're about to mention them directly
    for RoleCheck in Server.roles:
      if (RoleCheck.permissions.ban_members and RoleCheck.mentionable):
        MentionRoles.append(RoleCheck)
    
    # If we can mention roles, generate the role mention string
    if (len(MentionRoles) > 0):
      # Create a giant mention role string
      MentionStr = " ".join([Role.mention for Role in MentionRoles])
    else:
      # We have no ability to @ mention any of the mods for the private
      # thread, thus no one will be able to see it, as such, we need to post publicly
      CanCreatePrivateThread = False 
    
    BotMember:discord.Member = Server.me
    # Try to find the channel that we can potentially post in
    ChannelSet:discord.TextChannel|None = None
    ChannelPermissionList:list[tuple[discord.TextChannel, ChannelPostPermissions]] = []
    if (Server.system_channel is not None):
      ChannelPermissionList.append((Server.system_channel, self.GetChannelPostPerms(Server.system_channel, BotMember, CanCreatePrivateThread)))
      
    if (Server.public_updates_channel is not None):
      ChannelPermissionList.append((Server.public_updates_channel, self.GetChannelPostPerms(Server.public_updates_channel, BotMember, CanCreatePrivateThread)))
    
    if (Server.safety_alerts_channel is not None):
      ChannelPermissionList.append((Server.safety_alerts_channel, self.GetChannelPostPerms(Server.safety_alerts_channel, BotMember, CanCreatePrivateThread)))
    
    # Find how many of the above we have added.
    StartingLength:int = len(ChannelPermissionList)
    
    # Rank sort all the potential channels, max add 5 in addition to the above.
    # I'm thinking it's better to go through the older channels first
    # as the first few channels are probably things like "rules" and "info"
    # and those are probably not ones we can message in anyways
    ChannelsQueried:int = 0
    OldestList = sorted(Server.text_channels, key=lambda chan: chan.created_at)
    for OldChannel in OldestList:
      # Break out on 5 for memory purposes.
      if (len(ChannelPermissionList) - StartingLength >= ConfigData["MaxRankSortForWelcomeMessage"] or 
          ChannelsQueried >= ConfigData["MaxChannelsToQueryForWelcomeMessage"]):
        break
      
      HighestPermission:ChannelPostPermissions = self.GetChannelPostPerms(OldChannel, BotMember, CanCreatePrivateThread)
      if (HighestPermission is not ChannelPostPermissions.NoPerms):
        ChannelPermissionList.append((OldChannel, HighestPermission))
      ChannelsQueried += 1

    # Sort the channels
    ChannelPermissionList.sort(key=lambda chan: chan[1], reverse=True)
    # Whatever is at the top is our channel
    if (len(ChannelPermissionList) > 1):
      ChannelSet = ChannelPermissionList[0][0]

    # If we find a channel to send into
    if (ChannelSet is not None):
      PostEmbed:discord.Embed = self.CreateFirstTimeEmbed()
      PostedInThread:bool = False
      ServerStr:str = f"{Server.name}[{ServerId}]"

      # Attempt to post our welcome as a private thread
      if (CanCreatePrivateThread):
        try:
          PostingThread = await ChannelSet.create_thread(name="ScamGuard Welcome", reason="ScamGuard Message to Moderators")
          await PostingThread.send(MentionStr, embed=PostEmbed, allowed_mentions=MentionPerms)
          PostedInThread = True
        except:
          Logger.Log(LogLevel.Debug, f"Could not post in private thread in server {ServerStr}")

      # We could not post in the thread or we have no thread posting abilities
      if (PostedInThread == False):
        try:
          # double check to see if we can put embeds here, if not the embed argument will just be ignored when we call .send
          if (self.GetChannelPostPerms(ChannelSet, BotMember, False) == ChannelPostPermissions.SendMessageOnly):
            MentionStr += " " + Messages["first_time"]["message_only"].format(days=ConfigData["InactiveServerDayWindow"])
            
          await ChannelSet.send(MentionStr, embed=PostEmbed, allowed_mentions=MentionPerms)
        except Exception as ex:
          Logger.Log(LogLevel.Error, f"Could not post message in {ServerStr} both Channel and PrivThread failed, got error {str(ex)}")
          return
      Logger.Log(LogLevel.Log, f"Found Posting Channel `{ChannelSet.name}` for server {ServerStr}. Used Thread? {PostedInThread}")
    else:
      Logger.Log(LogLevel.Error, f"Could not find a channel for server {ServerId} to post welcome message")

  def GetChannelPostPerms(self, channel: discord.TextChannel|None, GuildSelf:discord.Member, CheckThreads:bool) -> ChannelPostPermissions:
    if (channel is not None):
      ChannelPerms:discord.Permissions = channel.permissions_for(GuildSelf)
      if (CheckThreads and ChannelPerms.create_private_threads):
        return ChannelPostPermissions.CanThread
      
      if (ChannelPerms.send_messages and ChannelPerms.embed_links):
        return ChannelPostPermissions.SendMessageEmbed
      elif (ChannelPerms.send_messages):
        return ChannelPostPermissions.SendMessageOnly

    return ChannelPostPermissions.NoPerms
  
  ### Webhook Management ###
  async def InstallWebhook(self, ServerId:int):
    if (self.AnnouncementChannel is None):
      Logger.Log(LogLevel.Notice, "Announcement channel is None, cannot manage webhooks!")
      return
    
    ChannelID:int|None = self.Database.GetChannelIdForServer(ServerId)
    if (ChannelID is None):
      Logger.Log(LogLevel.Warn, f"Could not install webhook for server {ServerId}, the ChannelID was None")
      return
    
    MessageChannel:discord.TextChannel = self.get_channel(ChannelID) # pyright: ignore[reportAssignmentType]
    # Check to see if a webhook is already installed.
    if (MessageChannel is not None):
      try:
        CurrentWebhooks = await MessageChannel.webhooks()
        for Webhook in CurrentWebhooks:
          if (Webhook.source_channel is None):
            continue
          # The webhook is already installed, do not attempt to install again.
          if (Webhook.type == discord.WebhookType.channel_follower and Webhook.source_channel.id == self.AnnouncementChannel.id):
            return
      except discord.Forbidden:
        Logger.Log(LogLevel.Warn, f"Unable to check the currently installed webhooks to the channel {ChannelID} in server {ServerId} to see if it was already installed.")
    else:
      Logger.Log(LogLevel.Warn, f"Attempted to install a webhook for an invalid message channel object. Server: {ServerId}, ChannelId: {ChannelID}")
      return
    
    try:
      await self.AnnouncementChannel.follow(destination=MessageChannel, reason="ScamGuard Ban Notification Setup")
    except discord.Forbidden:
      await MessageChannel.send(Messages["webhook"]["install_error"])
    except discord.HTTPException:
      Logger.Log(LogLevel.Log, f"Encountered an HTTP error while trying to install the webhook")
      
  async def DeleteWebhook(self, ServerId:int):
    if (self.AnnouncementChannel is None):
      Logger.Log(LogLevel.Notice, "Announcement channel is None, cannot manage webhooks!")
      return
    
    ChannelID:int|None = self.Database.GetChannelIdForServer(ServerId)
    if (ChannelID is None):
      Logger.Log(LogLevel.Warn, f"Could not uninstall webhook for server {ServerId}, the ChannelID was None")
      return
    WebhookChannel:discord.TextChannel|None = cast(discord.TextChannel|None, self.get_channel(ChannelID))
    FoundWebhook:discord.Webhook|None = None
    
    # Check to see if a webhook is already installed.
    if (WebhookChannel is not None):
      try:
        CurrentWebhooks = await WebhookChannel.webhooks()
        for Webhook in CurrentWebhooks:
          if (Webhook.source_channel is None):
            continue
          # The webhook is already installed, grab a reference to it.
          if (Webhook.type == discord.WebhookType.channel_follower and Webhook.source_channel.id == self.AnnouncementChannel.id):
            FoundWebhook = Webhook
            break
      except discord.Forbidden:
        # This will throw if they never wanted webhooks and the channel doesn't have the permissions for it
        return
    else:
      return
    
    # If we didn't find any webhooks, then stop processing.
    if (FoundWebhook is None):
      return
    
    try:
      await FoundWebhook.delete(reason="ScamGuard Setting Change")
    except discord.Forbidden:
      await WebhookChannel.send(Messages["webhook"]["remove"]["perm"])
    except discord.HTTPException:
      await WebhookChannel.send(Messages["webhook"]["remove"]["fatal"])

  ### Utils ###
  def GetServerInfoStr(self, Server:discord.Guild|None) -> str:
    if Server is None:
      return ""
    
    return f"`{Server.name}`[{Server.id}]"
  
  def GetControlServerGuild(self) -> discord.Guild|None:
    return self.get_guild(ConfigData["ControlServer"])
  
  def PostPongMessage(self):
    Logger.Log(LogLevel.Notice, "I have been pinged!")
    
  async def PostNotification(self, Message:str):
    self.LoggingMessageQueue.put(Message)
    
  async def ApplySettings(self, NewSettings):
    ServerID:int = NewSettings.GetServerID()
    self.Database.SetFromServerSettings(ServerID, NewSettings)
    if (NewSettings.WantsWebhooks):
      await self.InstallWebhook(ServerID)
    else:
      await self.DeleteWebhook(ServerID)
      
  async def DeleteFutureMessage(self, Message:discord.WebhookMessage, time:float):
    try:
      await Message.delete(delay=time)
    except:
      # If this fails, we really don't care. Usually this happens by the message failing out
      # or already being deleted, which satisfies this function's execution anyways
      pass
  
  ### Embeds ###
  def CreateBaseEmbed(self, Title:str, ApplyThumbnail:bool=True) -> discord.Embed:
    ReturnEmbed:discord.Embed = discord.Embed(title=Title, colour=discord.Colour.from_rgb(0, 0, 0))
    if (ConfigData.IsValid("AppEmbedThumbnail", str) and ApplyThumbnail):
      ReturnEmbed.set_thumbnail(url=ConfigData["AppEmbedThumbnail"])
    
    ReturnEmbed.set_author(name="ScamGuard", url="https://scamguard.app")
    return ReturnEmbed
  
  def AddSettingsEmbedInfo(self, AddToEmbed:discord.Embed):
    AddToEmbed.add_field(name="Settings", value="", inline=False)
    AddToEmbed.add_field(name="Message Channel for Moderators", inline=False, value=Messages['settings']['mod_msg'])
    AddToEmbed.add_field(name="Ban Notification Channel", inline=False, value=Messages['settings']['ban_notif'])
  
  def CreateInfoEmbed(self) -> discord.Embed:
    NumServers:int = self.Database.GetNumServers()
    NumActivated:int = self.Database.GetNumActivatedServers()
    ResponseEmbed:discord.Embed = self.CreateBaseEmbed("ScamGuard Info")
    ResponseEmbed.add_field(name="About", inline=False, value=Messages['info']['about'])
    ResponseEmbed.add_field(name="Links", value=Messages["info"]["links"])
    ResponseEmbed.add_field(name="Help", value=Messages["info"]["help_links"])
    ResponseEmbed.add_field(name="Legal", value=Messages["info"]["legal"])
    ResponseEmbed.set_footer(text=f"Scammers Defeated: {self.Database.GetNumBans()} | Servers: {NumActivated}/{NumServers}")
    return ResponseEmbed
  
  def CreateFirstTimeEmbed(self) -> discord.Embed:
    NumDays:int = ConfigData["InactiveServerDayWindow"]
    ResponseEmbed:discord.Embed = self.CreateBaseEmbed("ScamGuard Welcome")
    ResponseEmbed.description = Messages["first_time"]["desc"].format(bans=self.Database.GetNumBans())
    ResponseEmbed.add_field(name=Messages["first_time"]["mod_role_title"], 
                            value=Messages["first_time"]["mod_role_desc"], inline=False)
    ResponseEmbed.add_field(name="", value="", inline=False)
    ResponseEmbed.add_field(name=Messages["first_time"]["activate_title"].format(days=NumDays), 
                            value=Messages["first_time"]["activate_desc"].format(days=NumDays), inline=False)
    ResponseEmbed.set_footer(text=Messages["first_time"]["footer"])
    return ResponseEmbed
    
  async def CreateBanEmbed(self, TargetId:int) -> discord.Embed:
    BanData = self.Database.GetBanInfo(TargetId)
    UserBanned:bool = (BanData is not None)
    User = await self.LookupUser(TargetId)
    HasUserData:bool = (User is not None)
    UserData = self.CreateBaseEmbed("User Data", False)
    if (HasUserData):
      UserData.add_field(name="Name", value=f"`{User.display_name}`")
      UserData.add_field(name="Discord Handle", value=f"`{User.name}`", inline=True)
      UserData.add_field(name="Mention", value=User.mention)
      # This will always be an approximation, plus they may be in servers the bot is not in.
      if (ConfigData["ScamCheckShowsSharedServers"]):
        UserData.add_field(name="Shared Servers", value=f"~{len(User.mutual_guilds)}")

      # If currently banned and has an evidence thread, display it.
      if (UserBanned and BanData.evidence_thread is not None):
        UserData.add_field(name="Evidence (TAG Server)", value=f"<#{BanData.evidence_thread}>", inline=False)
      UserData.add_field(name="Account Created", value=f"{discord.utils.format_dt(User.created_at)}", inline=False)
      UserData.set_thumbnail(url=User.display_avatar.url)
    
    UserData.add_field(name="Banned Status", value=f"{UserBanned}")
    
    # Figure out who banned them
    if (UserBanned):
      UserData.add_field(name="Banned By", value=f"{BanData.assigner_discord_user_name}")
      # Create a date time format (all of the database timestamps are in iso format)
      UserData.add_field(name="Banned At", value=f"{discord.utils.format_dt(BanData.created_at)}", inline=False)
      # Push a last updated field if the time stamps aren't the same
      if (BanData.created_at != BanData.updated_at):
        UserData.add_field(name="Last Updated", value=f"{discord.utils.format_dt(BanData.updated_at)}", inline=False)

      UserData.colour = discord.Colour.red()
    elif (not HasUserData):
      UserData.colour = discord.Colour.dark_orange()
    else:
      UserData.colour = discord.Colour.green()

    UserData.set_footer(text=f"User ID: {TargetId}")
    return UserData

  ### Ban Handling ###        
  async def ReprocessBans(self, ServerId:int, LastActions:int=0, HandlingCooldown:bool=False) -> BanResult:
    Server:discord.Guild|None = self.get_guild(ServerId)
    if (Server is None):
      Logger.Log(LogLevel.Error, f"Could not look up the server {ServerId} while reprocessing bans")
      if (HandlingCooldown):
        self.Database.SetProcessingServerCooldown(ServerId, False)
      return BanResult.Error
    
    ServerInfoStr:str = self.GetServerInfoStr(Server)
    BanReturn:BanResult = BanResult.Processed
    Logger.Log(LogLevel.Log, f"Attempting to import ban data to {ServerInfoStr}")
    # Number of bans processed
    NumBans:int = 0
    # Number of actual bans actioned on (used for the daily server rate limit)
    BanActions:int = 0
    NumFailures:int = 0
    RawBanQuery = self.Database.GetAllBans(LastActions)
    CurrentNumBans:int = len(RawBanQuery)
    ActionsAppliedThisLoop:int = 0
    DoesSleep:bool = ConfigData["UseSleep"]
    DoesHaltOnFailures:bool = ConfigData["MaxBanFailures"] > 0
    DoesHaltOnMaxBans:bool = ConfigData["MaxBulkImports"] > 0
    
    # resort the ban query list if we are handling cooldowns
    BanQueryResult = RawBanQuery
    if (HandlingCooldown):
      BanQueryResult = sorted(RawBanQuery, key=lambda ban: ban.created_at)
    
    for Ban in BanQueryResult:
      if (DoesSleep):
        # Put in sleep functionality on this loop, as it could be heavy
        if (ActionsAppliedThisLoop >= ConfigData["ActionsPerTick"]):
          await asyncio.sleep(ConfigData["SleepAmount"])
          ActionsAppliedThisLoop = 0
        else:
          ActionsAppliedThisLoop += 1
          
      if (DoesHaltOnFailures and NumFailures > ConfigData["MaxBanFailures"]):
        Logger.Log(LogLevel.Warn, f"Number of ban failures reached {NumFailures} for server {ServerInfoStr}, exiting subprocess.")
        BanReturn = BanResult.Error
        break
      
      # Check if we have a max and stop processing from here
      if (DoesHaltOnMaxBans and BanActions >= ConfigData["MaxBulkImports"]):
        BanReturn = BanResult.BansExceeded
        break

      UserId:int = int(Ban.discord_user_id)
      UserToBan:discord.User = cast(discord.User, discord.Object(UserId))
      BanResponse = await self.PerformActionOnServer(Server, UserToBan, 
                               f"User banned by {Ban.assigner_discord_user_name}", ModerationAction.Ban)

      BanResponseFlag:BanResult = BanResponse[1]
      # See if the ban did go through.
      if (BanResponse[0] == False):
        NumFailures += 1
        if (BanResponseFlag == BanResult.BansExceeded):
          Logger.Log(LogLevel.Error, f"Unable to process ban on user {UserId} for server {ServerInfoStr} due to exceed")
          BanReturn = BanResult.BansExceeded
          break
        else:
          # NOTE: discord outages will automatically retry this ban in the future,
          # there may exist a case where the ban might slip through if the given server hits an external global threshold
          # not just with our bot
          self.AddAsyncTask(self.PostBanFailureInformation(Server, UserId, BanResponseFlag, ModerationAction.Ban))
          if (BanResponseFlag == BanResult.LostPermissions):
            # TODO: Perhaps handle this better, there's no way to really retry
            Logger.Log(LogLevel.Error, f"Unable to process ban on user {UserId} for server {ServerInfoStr}")
            BanReturn = BanResult.LostPermissions
            break
      else:
        NumBans += 1
        # If we didn't expense a ban, then there's no need to expense one of our daily actions
        if (BanResponseFlag != BanResult.NoActionNeeded):
          BanActions += 1
    
    # If this is being handled by a server reprocessing, then make sure to update the db properly
    if (HandlingCooldown):
      CurrentNumBans = self.Database.GetNumBans()
      # Remove the server from the cooldown table ONLY if they have processed all the bans successfully
      if (BanReturn == BanResult.Processed):
        self.Database.RemoveServerCooldown(ServerId)
        Logger.Log(LogLevel.Notice, f"All delayed bans have been processed for {ServerInfoStr}")
        NumBans = CurrentNumBans
      # Otherwise if we're already in cooldown (other error occurred), or we have exceeded our bans (i.e. first time exceed)
      # then we should update our current server cooldown information
      elif (BanReturn == BanResult.BansExceeded or self.Database.IsServerInCooldown(ServerId)):
        NewBanPos:int = self.Database.UpdateServerCooldown(ServerId, NumBans)
        Logger.Log(LogLevel.Warn, f"{ServerInfoStr} had bans exceeded again, will continue from {NewBanPos}")
        # Make the debug print look nice
        NumBans = NewBanPos

    # If we are not processing server cooldowns and we encounter this error, and we're not in the db for this,
    # then add us to the db
    elif (BanReturn == BanResult.BansExceeded and not self.Database.IsServerInCooldown(ServerId)):
      NewBanPos:int = self.Database.UpdateServerCooldown(ServerId, NumBans)
      Logger.Log(LogLevel.Warn, f"Bans Exceeded. Pushing {ServerInfoStr} to continue processing in the future at {NewBanPos}")

    Logger.Log(LogLevel.Notice, f"Processed {NumBans}/{CurrentNumBans} bans for {ServerInfoStr}!")
    return BanReturn
  
  async def ReprocessInstance(self, LastActions:int):
    BanQueryResult = self.Database.GetAllBans(LastActions)
    NumBans:int = self.Database.GetNumBans() - LastActions
    Count:int = 0
    for Ban in BanQueryResult:
      UserId:int = int(Ban.discord_user_id)
      AuthorizerName:str = Ban.assigner_discord_user_name
      BanNumber:int = NumBans + Count
      await self.ProcessActionOnUser(UserId, AuthorizerName, ModerationAction.Ban, BanNumber)
      Count += 1
  
  def ScheduleReprocessInstance(self, LastActions:int):
    self.AddAsyncTask(self.ReprocessInstance(LastActions))
  
  def ScheduleReprocessBans(self, ServerId:int, LastActions:int=0, HandlingCooldown:bool=False):
    self.AddAsyncTask(self.ReprocessBans(ServerId, LastActions, HandlingCooldown))
    
  def KickUser(self, TargetId:int, AuthName:str):
    self.AddAsyncTask(self.ProcessActionOnUser(TargetId, AuthName, ModerationAction.Kick))
    
  def BanUser(self, TargetId:int, AuthName:str):
    self.AddAsyncTask(self.ProcessActionOnUser(TargetId, AuthName, ModerationAction.Ban))
    
  def UnbanUser(self, TargetId:int, AuthName:str):
    self.AddAsyncTask(self.ProcessActionOnUser(TargetId, AuthName, ModerationAction.Unban))
    
  # Handles pushing the ban/unban to every server we are in
  async def ProcessActionOnUser(self, TargetId:int, AuthorizerName:str, Action:ModerationAction, BanNumOverride:int=-1):
    NumServersPerformed:int = 0
    ActionsAppliedThisLoop:int = 0
    DoesSleep:bool = ConfigData["UseSleep"]
    # Used to get an estimation of what this ban number would be. It is not accurate in heavy ban waves.
    BanNumber:int = self.Database.GetNumBans() if BanNumOverride == -1 else BanNumOverride
    UserToWorkOn:discord.User = cast(discord.User, discord.Object(TargetId))
    
    BanReason=f"Confirmed {str(Action)} by {AuthorizerName}"
    AllServers = self.Database.GetAllActivatedServersForAction(self.BotID, Action)
    NumServers:int = len(AllServers)
    
    # Instead of going through all servers it's added to, choose all servers that are activated.
    for ServerData in AllServers:
      if (DoesSleep):
        # Put in sleep functionality on this loop, as it could be heavy
        if (ActionsAppliedThisLoop >= ConfigData["ActionsPerTick"]):
          await asyncio.sleep(ConfigData["SleepAmount"])
          ActionsAppliedThisLoop = 0
        else:
          ActionsAppliedThisLoop += 1

      ServerId:int = int(ServerData.discord_server_id)
      DiscordServer = self.get_guild(ServerId)
      if (DiscordServer is not None):
        BanResultTuple = await self.PerformActionOnServer(DiscordServer, UserToWorkOn, BanReason, Action)
        if (BanResultTuple[0]):
          # Ban was successful, continue processing
          NumServersPerformed += 1
        else:
          ResultFlag = BanResultTuple[1]
          ServerStr:str = self.GetServerInfoStr(DiscordServer)
          if (Action == ModerationAction.Ban):
            if (ResultFlag == BanResult.InvalidUser):
              Logger.Log(LogLevel.Warn, f"Got a ban result of invalid while trying to process ban for {TargetId}")
              break
            elif (ResultFlag == BanResult.ServerOwner):
              Logger.Log(LogLevel.Error, f"Attempted to ban a server owner! {ServerStr} with user to work {UserToWorkOn.id} == {DiscordServer.owner_id}")
              continue
          elif (ResultFlag == BanResult.LostPermissions or ResultFlag == BanResult.Error or ResultFlag == BanResult.BansExceeded):
            # Check if we should suppress the ban failure message, as the bot will automatically handle it later.
            if (ResultFlag == BanResult.BansExceeded):
              if (not self.Database.IsServerInCooldown(ServerId)):
                Logger.Log(LogLevel.Notice, f"Server {ServerStr} hit ban quota on {BanNumber}, adding them to exhausted servers")
                # This should be subtracted 1 so that we will retry this action from this ban forward
                self.Database.UpdateServerCooldown(ServerId, BanNumber - 1)
              continue
            self.AddAsyncTask(self.PostBanFailureInformation(DiscordServer, TargetId, ResultFlag, Action))
          elif (ResultFlag == BanResult.ServiceError):
            self.AddAsyncTask(self.PerformActionOnServer(DiscordServer, UserToWorkOn, BanReason, Action, True))
      else:
        # TODO: Potentially remove the server from the list?
        Logger.Log(LogLevel.Error, f"The server {ServerId} did not respond on a look up, does it still exist?")

    Logger.Log(LogLevel.Notice, f"Action execution on {TargetId} performed in {NumServersPerformed}/{NumServers} servers")
    
  # Checks if an account is already banned/unbanned
  async def CheckRawBanStatus(self, Server:discord.Guild, User:discord.Member|discord.User) -> BanResult:
    try:
      BanStatus = await Server.fetch_ban(User)
      return BanResult.Processed
    except discord.NotFound:
      return BanResult.NotBanned
    except discord.HTTPException:
      return BanResult.ServiceError
    except discord.Forbidden:
      return BanResult.LostPermissions

  # Handles moderation actions an user in each individual server
  async def PerformActionOnServer(self, Server:discord.Guild, User:discord.Member|discord.User, Reason:str, Action:ModerationAction, ShouldWait:bool=False) -> tuple[bool, BanResult]:        
    IsDevelopmentMode:bool = ConfigData.IsDevelopment()
    BanId:int = User.id
    ServerOwnerId:int = Server.owner_id or 0
    ServerInfo:str = self.GetServerInfoStr(Server)
    if (ShouldWait):
      await asyncio.sleep(ConfigData["SleepAmount"])
      Logger.Log(LogLevel.Notice, f"Attempting {Action} on {BanId} in {ServerInfo} again")

    try:
      Logger.Log(LogLevel.Verbose, f"Performing {Action} action on {BanId} in {ServerInfo} owned by {ServerOwnerId}")
      if (BanId == ServerOwnerId):
        Logger.Log(LogLevel.Warn, f"{Action} of {BanId} dropped for {ServerInfo} as it is the owner!")
        return (False, BanResult.ServerOwner)
      
      # Check if we should be banning or unbanning an user
      if (Action == ModerationAction.Ban or Action == ModerationAction.Unban):
        # Check what the raw status of the user's current ban is, this is to potentially optimize 
        UserStatus:BanResult = await self.CheckRawBanStatus(Server, User)
        # banning actions
        if (Action == ModerationAction.Ban):
          # if the user is not already banned and we're not in development, ban them
          if (IsDevelopmentMode == False and UserStatus is not BanResult.Processed):
            await Server.ban(User, reason=Reason)
          else:
            # otherwise, they're already handled, keep going
            return (True, BanResult.NoActionNeeded)
        # unban actions
        elif (Action == ModerationAction.Unban):
          # if the user is anything but not banned, 
          if (IsDevelopmentMode == False and UserStatus not in [BanResult.NotBanned, BanResult.LostPermissions]):
            await Server.unban(User, reason=Reason)
          else:
            return (True, BanResult.NoActionNeeded)
      elif (IsDevelopmentMode == False and Action == ModerationAction.Kick):
        await Server.kick(User, reason=Reason)
      
      if (IsDevelopmentMode == False):
        Logger.Log(LogLevel.Debug, "Action was dropped as we are currently in development mode")
      return (True, BanResult.Processed)
    except discord.NotFound:
      if (Action == ModerationAction.Unban):
        Logger.Log(LogLevel.Verbose, f"User {BanId} is not banned in server")
        return (True, BanResult.NotBanned)
      else:
        Logger.Log(LogLevel.Warn, f"User {BanId} is not a valid user while processing the ban")
        return (False, BanResult.InvalidUser)
    except discord.Forbidden as forbiddenEx:
      if (Action == ModerationAction.Kick):
        # We don't have the ability to kick (some instances)
        return (False, BanResult.Processed)
      else:
        Logger.Log(LogLevel.Error, f"We do not have ban/unban permissions in this server {ServerInfo} owned by {ServerOwnerId}! Err: {str(forbiddenEx)}")
        return (False, BanResult.LostPermissions)
    except discord.HTTPException as ex:
      if (ex.code == 30035):
        Logger.Log(LogLevel.Warn, f"Hit the bans exceeded error while trying to perform actions on server {ServerInfo}")
        return (False, BanResult.BansExceeded)
      if (ex.status == 503):
        # Retries are happened upstream, looking for the error BanResult.ServiceError
        Logger.Log(LogLevel.Warn, f"We encountered an 503 error while trying to perform actions on {BanId} for server {ServerInfo}, will retry")
        return (False, BanResult.ServiceError)
      
      Logger.Log(LogLevel.Warn, f"We encountered an error {(str(ex))} while trying to perform for server {ServerInfo} owned by {ServerOwnerId}!")
    return (False, BanResult.Error)
  
  # Handles messaging to server moderators if a ban fails.
  async def PostBanFailureInformation(self, Server:discord.Guild, UserId:int, Reason:BanResult, Action:ModerationAction):
    if (ConfigData["CanSendServerErrorMessages"] == False):
      return
    
    ChannelIDToPost = self.Database.GetChannelIdForServer(Server.id)
    if (ChannelIDToPost == None):
      return
    
    ServerIDStr:str = self.GetServerInfoStr(Server)
    DiscordChannel = self.get_channel(ChannelIDToPost)
    if (DiscordChannel is None):
      Logger.Log(LogLevel.Error, f"Could not resolve the channel {ChannelIDToPost} for server {ServerIDStr}")
      return
    
    ErrorMsg:str = ""
    ResolutionMsg:str = ""
    if (Reason == BanResult.LostPermissions):
      ErrorMsg = Messages["ban_failure"]["lost_perm"]["error"]
      ResolutionMsg = Messages["ban_failure"]["lost_perm"]["reason"]
    elif (Reason == BanResult.Error):
      ErrorMsg = Messages["ban_failure"]["gen_error"]["error"]
      ResolutionMsg = Messages["ban_failure"]["gen_error"]["reason"]
    elif (Reason == BanResult.BansExceeded):
      ErrorMsg =  Messages["ban_failure"]["bans_exceed"]["error"]
      ResolutionMsg = Messages["ban_failure"]["bans_exceed"]["reason"]
    else:
      return
    
    User:discord.User|discord.Member|None = await self.LookupUser(UserId, Server)
    FailureEmbed:discord.Embed = self.CreateBaseEmbed(f"WARNING: Failed to {Action} user!")
    FailureEmbed.color = discord.Colour.dark_red()
    if (User is not None):
      FailureEmbed.add_field(name="User", value=User.mention)
    
    FailureEmbed.add_field(name="User ID", value=f"{UserId}")
    FailureEmbed.add_field(name="Action Taken", value=f"{Action}")
    FailureEmbed.add_field(inline=False, name="Error Code", value=ErrorMsg)
    FailureEmbed.add_field(inline=False, name="Resolution", value=ResolutionMsg)
    FailureEmbed.add_field(inline=False, name="Help Links", value=Messages["ban_failure"]["help_links"])
    FailureEmbed.set_footer(text="scamguard.app")
    await DiscordChannel.send(embed=FailureEmbed) # type: ignore
    Logger.Log(LogLevel.Notice, f"A ban failure message was sent to {ServerIDStr} for the user id {UserId}")