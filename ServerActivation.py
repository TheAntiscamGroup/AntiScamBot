# A discord view for handling server activations
from __future__ import annotations
from discord import ui, ButtonStyle, Interaction, Colour, Embed, Guild
from Config import Config
from Logger import Logger, LogLevel
from BotServerSettings import ServerSettingsView, BotSettingsPayload
from ModalHelpers import SelfDeletingView
from TextWrapper import TextLibrary
from Utils import GetBot
from typing import TYPE_CHECKING, override

if TYPE_CHECKING:
  from BotBase import DiscordBot
  from Types import OptionalChannel, OptionalGuild

Messages:TextLibrary = TextLibrary()
ConfigData:Config = Config()

class ScamGuardServerSetup():
  BotInstance:DiscordBot

  def __init__(self, Bot:DiscordBot) -> None:
    self.BotInstance = Bot

  async def CheckForBotConflicts(self, InServer:OptionalGuild) -> bool:
    if (InServer is None):
      return False

    BotConflicts:list[int] = ConfigData.get("ConflictingBots", [0])
    for DiscordBotId in BotConflicts:
      if (await self.BotInstance.LookupMember(DiscordBotId, InServer) is not None):
        return True

    return False

  async def OpenServerSetupModel(self, interaction:Interaction):
    await interaction.response.defer(ephemeral=True, thinking=True)
    NumBans:int = self.BotInstance.Database.GetNumBans()

    InformationEmbed:Embed = self.BotInstance.CreateBaseEmbed(Messages["setup"]["title"])
    InformationEmbed.add_field(name=Messages["setup"]["info"]["title"], inline=False, value=Messages["setup"]["info"]["msg"])
    InformationEmbed.add_field(name=Messages["setup"]["stats"]["title"], inline=False,
                               value=Messages["setup"]["stats"]["msg"].format(number=NumBans))
    InformationEmbed.add_field(name=Messages["setup"]["report"]["title"], inline=False, value=Messages["setup"]["report"]["msg"])
    InformationEmbed.add_field(name="", value="", inline=False)
    self.BotInstance.AddSettingsEmbedInfo(InformationEmbed)
    InformationEmbed.add_field(name="", value="", inline=False)
    InformationEmbed.add_field(name="IMPORTANT:", value="", inline=False)
    InformationEmbed.add_field(name=Messages["setup"]["roles"]["title"], inline=False,
                               value=Messages["setup"]["roles"]["msg"])

    # Check to see if quarantine bots are in the server, and warn about it.
    if (await self.CheckForBotConflicts(interaction.guild)):
      InformationEmbed.add_field(name=Messages["setup"]["conflicts"]["title"], inline=False,
                                 value=Messages["setup"]["conflicts"]["msg"])

    InformationEmbed.add_field(name="", value="", inline=False)
    InformationEmbed.add_field(name=Messages["setup"]["important_links"]["title"], inline=False,
                               value=Messages["setup"]["important_links"]["msg"])
    InformationEmbed.set_footer(text="ScamGuard")

    NewSetupView:ServerSettingsView = ServerSettingsView(self.SendActivationRequest, interaction)
    await NewSetupView.Send(interaction, [InformationEmbed])

  async def PushActivation(self, Payload:BotSettingsPayload):
    ServerID:int = Payload.GetServerID()
    UserID:int = Payload.GetUserID()

    ServerInstance:int|None = self.BotInstance.Database.GetBotIdForServer(ServerID)
    if (ServerInstance is None):
      Logger.Log(LogLevel.Error, f"Failed to get bot id for the server {ServerID}")
      return

    if (self.BotInstance.ClientHandler is None):
      Logger.Log(LogLevel.Error, f"Client Handler was invalid while pushing activation for {ServerID}")
      return

    await self.BotInstance.ApplySettings(Payload)
    self.BotInstance.ClientHandler.SendActivationForServerInstance(UserID, ServerID, ServerInstance)
    await self.BotInstance.ActivateServerInstance(UserID, ServerID)

  async def SendActivationRequest(self, Payload:BotSettingsPayload):
    # If the server is already activated then do nothing more.
    if (self.BotInstance.Database.IsActivatedInServer(Payload.GetServerID())):
      Logger.Log(LogLevel.Warn,
          f"User {Payload.GetUserID()} attempted to activate {self.BotInstance.GetServerInfoStr(Payload.Server)} but it's already activated")
      return

    # If we don't require moderation for activation approval
    if (ConfigData.get("RequireActivationApproval", True) == False):
      Logger.Log(LogLevel.Notice, f"Attempting to activate a server without approval necessary!")
      await self.PushActivation(Payload)
      return

    # View actions for the server activation approval
    ActivationActions:ServerActivationApproval = ServerActivationApproval(self, Payload)
    if (Payload.Server is None):
      Logger.Log(LogLevel.Warn, "While processing approval, the payload server was none.")
      return

    # Request Embed for the Activation Server
    RequestServer:Guild = Payload.Server
    RequestEmbed:Embed = Embed(title="Activation Request", color = Colour.orange())
    RequestEmbed.add_field(name="Server Name", value=f"`{RequestServer.name}`", inline=False)
    if (Payload.InteractiveUser is not None):
      RequestEmbed.add_field(name="Requestor", value=f"`{Payload.InteractiveUser.display_name}`")
      RequestEmbed.add_field(name="Requestor Handle", value=Payload.InteractiveUser.mention)
      RequestEmbed.add_field(name="Requestor ID", value=f"`{Payload.GetUserID()}`")
    RequestEmbed.add_field(name="Num Members", value=RequestServer.member_count, inline=False)
    if (RequestServer.icon is not None):
      RequestEmbed.set_thumbnail(url=RequestServer.icon.url)
    RequestEmbed.set_footer(text=f"Server ID: {Payload.GetServerID()} | Requestor ID: {Payload.GetUserID()}")

    if (self.BotInstance.ActivationChannel is not None):
      await ActivationActions.SendToChannel(self.BotInstance.ActivationChannel, [RequestEmbed])

class ServerActivationApproval(SelfDeletingView):
  Parent:ScamGuardServerSetup
  Payload:BotSettingsPayload
  HasInteracted:bool = False

  def __init__(self, Parent:ScamGuardServerSetup, InPayload:BotSettingsPayload):
    self.Parent = Parent
    self.Payload = InPayload

    super().__init__(ViewTimeout=None)

  @ui.button(label="Approve", style=ButtonStyle.success, row=4)
  async def setup(self, interaction:Interaction, button:ui.Button[ui.view.BaseView]):
    self.HasInteracted = True
    Bot = GetBot(interaction)
    ServerID:int = self.Payload.GetServerID()
    if (Bot.Database.IsActivatedInServer(ServerID)):
      return

    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    await interaction.response.send_message(f"Enqueuing activation for server {ServerIDStr}")
    await self.Parent.PushActivation(self.Payload)
    await self.StopInteractions()

  @ui.button(label="Deny with Message", style=ButtonStyle.grey, row=4)
  async def deny_activation(self, interaction:Interaction, button:ui.Button[ui.view.BaseView]):
    self.HasInteracted = True
    ServerID:int = self.Payload.GetServerID()
    Bot = GetBot(interaction)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)

    await interaction.response.send_message(f"Activation denied for server {ServerIDStr}.")

    DiscordChannel:OptionalChannel = self.Payload.MessageChannel
    if (DiscordChannel is None):
      Logger.Log(LogLevel.Error, f"Could not resolve the channel {self.Payload.GetMessageID()} for server {ServerIDStr} to post activation deny message in")
      return

    # Do not send a message if the server admins sent the activation command a few times already and was approved.
    if (not Bot.Database.IsActivatedInServer(ServerID)):
      await DiscordChannel.send(Messages["setup"]["activation_error"])

    await self.StopInteractions()

  @ui.button(label="Silently Leave Server", style=ButtonStyle.danger, row=4)
  async def force_leave(self, interaction:Interaction, button:ui.Button[ui.view.BaseView]):
    self.HasInteracted = True
    ServerID:int = self.Payload.GetServerID()
    Bot = GetBot(interaction)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    if (Bot.Database.IsActivatedInServer(ServerID)):
      return

    await interaction.response.send_message(f"Activation leaving server {ServerIDStr}.")

    # force leave the server
    Bot.LeaveServer(ServerID)

    await self.StopInteractions()

  @ui.button(label="Forbid Forever", style=ButtonStyle.danger, row=4)
  async def forbid_activation(self, interaction:Interaction, button:ui.Button[ui.view.BaseView]):
    self.HasInteracted = True
    ServerID:int = self.Payload.GetServerID()
    Bot = GetBot(interaction)
    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    if (Bot.Database.IsActivatedInServer(ServerID)):
      return

    await interaction.response.send_message(f"Activation now forbidden for server {ServerIDStr}.")
    # add the server to the forbid list
    Bot.Database.ForbidServerActivation(ServerID, interaction.user.id)
    # force leave the server
    Bot.LeaveServer(ServerID)

    await self.StopInteractions()

  @override
  async def on_cancel(self, interaction:Interaction):
    self.HasInteracted = True
    Bot = GetBot(interaction)
    # Do not post anything else if the bot was already activated in the server, just delete and move on.
    if (Bot.Database.IsActivatedInServer(self.Payload.GetServerID())):
      return

    ServerIDStr:str = Bot.GetServerInfoStr(self.Payload.Server)
    await interaction.response.send_message(f"Activation skipped for server {ServerIDStr}.")