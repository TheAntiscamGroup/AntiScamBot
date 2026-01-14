# A discord view for handling server activations
from discord import ui, ButtonStyle, Interaction, Colour, Embed, Guild, TextChannel
from BotBase import DiscordBot
from Config import Config
from Logger import Logger, LogLevel
from BotServerSettings import ServerSettingsView, BotSettingsPayload
from ModalHelpers import SelfDeletingView
from TextWrapper import TextLibrary
from typing import cast

Messages:TextLibrary = TextLibrary()
ConfigData:Config = Config()

class ScamGuardServerSetup():
  BotInstance = None
  
  def __init__(self, Bot) -> None:
    self.BotInstance = Bot
    
  async def CheckForBotConflicts(self, InServer:None|Guild) -> bool:
    if (InServer is None):
      return False
    
    BotConflicts = ConfigData["ConflictingBots"]
    for DiscordBotId in BotConflicts:
      if (await self.BotInstance.LookupMember(DiscordBotId, InServer) is not None): # pyright: ignore[reportOptionalMemberAccess]
        return True
      
    return False
  
  async def OpenServerSetupModel(self, interaction:Interaction):
    if (self.BotInstance is None):
      Logger.Log(LogLevel.Error, "Failed to get the bot instance during ScamGuard setup")
      return
    
    await interaction.response.defer(ephemeral=True, thinking=True)
    NumBans:int = self.BotInstance.Database.GetNumBans()
    
    InformationEmbed:Embed = self.BotInstance.CreateBaseEmbed(Messages["setup"]["title"])
    InformationEmbed.add_field(name=Messages["setup"]["info"]["title"], inline=False, value=Messages["setup"]["info"]["msg"])
    InformationEmbed.add_field(name=Messages["setup"]["stats"]["title"], inline=False, value=Messages["setup"]["stats"]["msg"].format(number=NumBans))
    InformationEmbed.add_field(name=Messages["setup"]["report"]["title"], inline=False, value=Messages["setup"]["report"]["msg"])
    InformationEmbed.add_field(name="", value="", inline=False)
    self.BotInstance.AddSettingsEmbedInfo(InformationEmbed)
    InformationEmbed.add_field(name="", value="", inline=False)
    InformationEmbed.add_field(name="IMPORTANT:", value="", inline=False)
    InformationEmbed.add_field(name=Messages["setup"]["roles"]["title"], inline=False, value=Messages["setup"]["roles"]["msg"])
    
    # Check to see if quarantine bots are in the server, and warn about it.
    if (await self.CheckForBotConflicts(interaction.guild)):
      InformationEmbed.add_field(name=Messages["setup"]["conflicts"]["title"], inline=False, value=Messages["setup"]["conflicts"]["msg"])
    
    InformationEmbed.add_field(name="", value="", inline=False)
    InformationEmbed.add_field(name=Messages["setup"]["important_links"]["title"], inline=False, value=Messages["setup"]["important_links"]["msg"])
    InformationEmbed.set_footer(text="ScamGuard")
    
    NewSetupView:ServerSettingsView = ServerSettingsView(self.SendActivationRequest, interaction)
    await NewSetupView.Send(interaction, [InformationEmbed])

  async def PushActivation(self, Payload:BotSettingsPayload):
    ServerID:int = Payload.GetServerID()
    UserID:int = Payload.GetUserID()
    if (self.BotInstance is None):
      Logger.Log(LogLevel.Error, "Failed to get the bot instance during ScamGuard setup")
      return
    ServerInstance:int = self.BotInstance.Database.GetBotIdForServer(ServerID)
    await self.BotInstance.ApplySettings(Payload)
    
    self.BotInstance.ClientHandler.SendActivationForServerInstance(UserID, ServerID, ServerInstance)
    await self.BotInstance.ActivateServerInstance(UserID, ServerID)
    
  async def SendActivationRequest(self, Payload:BotSettingsPayload):
    if (self.BotInstance is None):
      Logger.Log(LogLevel.Error, "Somehow we do not know what our bot instance is...")
      return
    
    # If the server is already activated then do nothing more.
    if (self.BotInstance.Database.IsActivatedInServer(Payload.GetServerID())):
      Logger.Log(LogLevel.Warn, f"User {Payload.GetUserID()} attempted to activate {self.BotInstance.GetServerInfoStr(Payload.Server)} but it's already activated")
      return
    
    # If we don't require moderation for activation approval
    if (ConfigData["RequireActivationApproval"] == False):
      Logger.Log(LogLevel.Notice, f"Attempting to activate a server without approval necessary!")
      await self.PushActivation(Payload)
      return
    
    # View actions for the server activation approval
    ActivationActions:ServerActivationApproval = ServerActivationApproval(self, Payload)
    
    # Request Embed for the Activation Server
    RequestServer:Guild = cast(Guild, Payload.Server)
    RequestEmbed:Embed = Embed(title="Activation Request", color = Colour.orange())
    RequestEmbed.add_field(name="Server Name", value=f"`{RequestServer.name}`", inline=False)
    if (Payload.InteractiveUser is not None):
      RequestEmbed.add_field(name="Requestor", value=f"`{Payload.InteractiveUser.display_name}`")
      RequestEmbed.add_field(name="Requestor Handle", value=Payload.InteractiveUser.mention)
    RequestEmbed.add_field(name="Num Members", value=RequestServer.member_count, inline=False)
    if (RequestServer.icon is not None):
      RequestEmbed.set_thumbnail(url=RequestServer.icon.url)
    RequestEmbed.set_footer(text=f"Server ID: {Payload.GetServerID()} | Requestor ID: {Payload.GetUserID()}")
    
    await ActivationActions.SendToChannel(self.BotInstance.ActivationChannel, [RequestEmbed])
  
class ServerActivationApproval(SelfDeletingView):
  Parent = None
  Payload:BotSettingsPayload = None # pyright: ignore[reportAssignmentType]
  
  def __init__(self, Parent, InPayload:BotSettingsPayload):
    self.Parent = Parent
    self.Payload = InPayload
    
    super().__init__(ViewTimeout=None)
    
  @ui.button(label="Approve", style=ButtonStyle.success, row=4)
  async def setup(self, interaction: Interaction, button: ui.Button):
    self.HasInteracted = True
    Bot = cast(DiscordBot, interaction.client)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    await interaction.response.send_message(f"Enqueuing activation for server {ServerIDStr}")
    await cast(ScamGuardServerSetup, self.Parent).PushActivation(self.Payload)
    await self.StopInteractions()
    
  @ui.button(label="Deny with Message", style=ButtonStyle.grey, row=4)
  async def deny_activation(self, interaction:Interaction, button:ui.Button):
    self.HasInteracted = True
    ServerID:int = self.Payload.GetServerID()
    Bot = cast(DiscordBot, interaction.client)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    
    await interaction.response.send_message(f"Activation denied for server {ServerIDStr}.")
    
    DiscordChannel:TextChannel|None = self.Payload.MessageChannel
    if (DiscordChannel is None):
      Logger.Log(LogLevel.Error, f"Could not resolve the channel {self.Payload.GetMessageID()} for server {ServerIDStr} to post activation deny message in")
      return
    
    # Do not send a message if the server admins sent the activation command a few times alread and was approved.
    if (not Bot.Database.IsActivatedInServer(ServerID)):
      await DiscordChannel.send(Messages["setup"]["activation_error"])
      
    await self.StopInteractions()
      
  @ui.button(label="Forbid Forever", style=ButtonStyle.danger, row=4)
  async def forbid_activation(self, interaction:Interaction, button:ui.Button):
    self.HasInteracted = True
    ServerID: int = self.Payload.GetServerID()
    Bot = cast(DiscordBot, interaction.client)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    
    await interaction.response.send_message(f"Activation now forbidden for server {ServerIDStr}.")
    # add the server to the forbid list
    Bot.Database.ForbidServerActivation(ServerID, interaction.user.id)
    # force leave the server
    Bot.LeaveServer(ServerID)
    
    await self.StopInteractions()
      
  async def on_cancel(self, interaction:Interaction):
    self.HasInteracted = True
    Bot = cast(DiscordBot, interaction.client)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    await interaction.response.send_message(f"Activation skipped for server {ServerIDStr}.")