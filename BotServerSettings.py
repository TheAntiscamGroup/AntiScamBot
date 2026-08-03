from __future__ import annotations
from collections.abc import Awaitable
from discord import ui, ButtonStyle, Interaction, Permissions
from ModalHelpers import YesNoSelector, SelfDeletingView, ModChannelSelector
from BotDatabaseSchema import Server
from Logger import Logger, LogLevel
from TextWrapper import TextLibrary
from Config import Config
from typing import TYPE_CHECKING, Callable, cast, override
from Utils import GetBot
from Types import OptionalChannel

if TYPE_CHECKING:
  from Types import OptionalDiscordMember, OptionalDiscordPerson, OptionalGuild
  from BotBase import DiscordBot

Messages:TextLibrary = TextLibrary()
type ServerSettingsCallback = Callable[[BotSettingsPayload], Awaitable[None]]

class BotSettingsPayload:
  InteractiveUser:OptionalDiscordPerson = None
  WebHookRequired:bool = False
  KickSusRequired:bool = False

  # These settings should get pulled from the db
  Server:OptionalGuild = None
  MessageChannel:OptionalChannel = None
  WantsWebhooks:bool = False
  KickSusUsers:bool = False

  def GetServerID(self) -> int:
    if (self.Server is None):
      return 0

    return self.Server.id

  def GetUserID(self) -> int:
    if (self.InteractiveUser is None):
      return 0

    return self.InteractiveUser.id

  def HasMessageChannel(self) -> bool:
    return self.MessageChannel is not None

  def GetMessageID(self) -> int:
    if (self.MessageChannel is None):
      return 0

    return self.MessageChannel.id

  def LoadFromDB(self, BotInstance: DiscordBot):
    DB = BotInstance.Database
    ServerInfo:Server|None = DB.GetServerInfo(self.GetServerID())
    if (ServerInfo is None):
      Logger.Log(LogLevel.Warn, "ServerInfo was none while loading server settings")
      return

    if (int(ServerInfo.activation_state) == 0):
      self.KickSusRequired = self.WebHookRequired = True
    else:
      self.WantsWebhooks = bool(ServerInfo.has_webhooks)
      self.KickSusUsers = bool(ServerInfo.kick_sus_users)

    # Check to see what the setting is for messaging channel, if it's 0, leave MessageChannel as None
    # else load up the text channel value
    if (int(ServerInfo.message_channel) != 0):
      self.MessageChannel = BotInstance.GetChannelById(ServerInfo.message_channel)

class InstallWebhookSelector(YesNoSelector):
  @override
  def GetYesDescription(self) -> str:
    return Messages["selector"]["webhook"]["yes"]

  @override
  def GetNoDescription(self) -> str:
    return Messages["selector"]["webhook"]["no"]

  @override
  def GetPlaceholder(self) -> str:
    return Messages["selector"]["webhook"]["placeholder"]

  @override
  def SetNotRequiredIfValueSet(self) -> bool:
    return True

class KickSuspiciousUsersSelector(YesNoSelector):
  @override
  def GetYesDescription(self) -> str:
    return Messages["selector"]["kick"]["yes"]

  @override
  def GetNoDescription(self) -> str:
    return Messages["selector"]["kick"]["no"]

  @override
  def GetPlaceholder(self) -> str:
    return Messages["selector"]["kick"]["placeholder"]

  @override
  def SetNotRequiredIfValueSet(self) -> bool:
    return True

class ServerSettingsView(SelfDeletingView):
  ChannelSelect:ModChannelSelector
  WebhookSelector:InstallWebhookSelector|None = None
  SuspiciousUserKicks:KickSuspiciousUsersSelector|None = None
  CallbackFunction:ServerSettingsCallback
  Payload:BotSettingsPayload
  HasInteracted:bool=False

  def __init__(self, InCB:ServerSettingsCallback, interaction:Interaction):
    super().__init__()
    ConfigData:Config = Config()

    # Pull current data
    self.Payload = BotSettingsPayload()
    self.Payload.Server = interaction.guild
    self.Payload.InteractiveUser = interaction.user
    self.Payload.LoadFromDB(GetBot(interaction))

    self.ChannelSelect = ModChannelSelector(RowPos=0)
    # If we don't have a message channel selected, force this setting here.
    if (not self.Payload.HasMessageChannel()):
      self.ChannelSelect.SetRequired()

    self.add_item(self.ChannelSelect)

    if (ConfigData.get("AllowWebhookInstall", True)):
      self.WebhookSelector = InstallWebhookSelector(RowPos=1)
      if (not self.Payload.WebHookRequired):
        self.WebhookSelector.SetCurrentValue(self.Payload.WantsWebhooks)
      self.add_item(self.WebhookSelector)

    if (ConfigData.get("AllowSuspiciousUserKicks", False)):
      self.SuspiciousUserKicks = KickSuspiciousUsersSelector(RowPos=2)
      if (not self.Payload.KickSusRequired):
        self.SuspiciousUserKicks.SetCurrentValue(self.Payload.KickSusUsers)
      self.add_item(self.SuspiciousUserKicks)

    self.CallbackFunction = InCB

  @ui.button(label="Confirm Settings", style=ButtonStyle.success, row=4)
  async def setup(self, interaction: Interaction, button: ui.Button[ui.view.BaseView]):
    # Couple of quick reference settings
    Bot = GetBot(interaction)
    DB = Bot.Database
    ServerId:int = self.Payload.GetServerID()
    ConfigData:Config = Config()

    # State settings
    ChannelSelectRequired:bool = self.ChannelSelect.min_values == 1
    ChannelSelectChanged:bool = False

    # Check if we can install webhooks
    if (ConfigData.get("AllowWebhookInstall", True) and self.WebhookSelector is not None):
      MadeWebhookSelection:bool = self.WebhookSelector.HasValue()
      if (MadeWebhookSelection):
        self.Payload.WantsWebhooks = self.WebhookSelector.GetValue() or False
      elif self.WebhookSelector.IsRequired():
        await interaction.response.send_message(Messages["selector"]["choose"], ephemeral=True, delete_after=10.0)
        return

    # Check to see if the channel option has changed. This code specifically will allow it for the user
    # to not change the setting and still use the old values
    if (not ChannelSelectRequired):
      CurrentChannelSetting:int|None = DB.GetChannelIdForServer(ServerId)
      # Grab what the user selected if they have any selections
      NewChannelSetting:int|None = self.ChannelSelect.values[0].id if self.ChannelSelect.values else None

      # If this is not required, and the user has made a selection
      # and the selection is not the current setting, then do an update.
      if (NewChannelSetting is not None and CurrentChannelSetting != NewChannelSetting):
        Logger.Log(LogLevel.Debug, f"Channel Selection has changed from {CurrentChannelSetting} to {NewChannelSetting}")
        ChannelSelectRequired = True
        ChannelSelectChanged = True

    # Resolve the selected channel to send messages into
    if (ChannelSelectRequired):
      if (await self.ChannelSelect.IsValid(interaction, True) == False):
        return

      ChannelToHookInto:OptionalChannel = cast(OptionalChannel, self.ChannelSelect.values[0].resolve())
      if (self.Payload.WantsWebhooks):
        # If the channel selection option has changed from the original setting, delete the original webhook
        if (ChannelSelectChanged):
          Logger.Log(LogLevel.Debug, "Deleting old webhook reference")
          await Bot.DeleteWebhook(ServerId)

        if (interaction.client.user is None):
          Logger.Log(LogLevel.Error, "ScamGuard lost login during this interaction")
          return

        if (interaction.guild is None):
          Logger.Log(LogLevel.Error, "The guild for the server settings is invalid")
          return

        BotMember:OptionalDiscordMember = interaction.guild.get_member(interaction.client.user.id)
        if (BotMember is None):
          Logger.Log(LogLevel.Error, "Bot was invalid during setup somehow")
          return
        if (ChannelToHookInto is not None):
          PermissionsObj:Permissions = ChannelToHookInto.permissions_for(BotMember)

          # Check to see if we can manage webhooks in that channel, if the user wants us to add ban notifications
          if (not PermissionsObj.manage_webhooks):
            await interaction.response.send_message(
              Messages["selector"]["webhook"]["need_perm"].format(channel=ChannelToHookInto.mention),
              ephemeral=True, delete_after=100.0)
            return
        else:
          Logger.Log(LogLevel.Warn, "ChannelToHookInto was None, which should not be an accessible area?")
          await interaction.response.send_message(Messages["selector"]["webhook"]["text_channel"],
                                                  ephemeral=True, delete_after=20.0)
          return
      # The user wanted webhooks but doesn't want them any more, delete the webhook from the channel.
      elif (self.WebhookSelector is not None and self.WebhookSelector.HasValueChanged() and self.Payload.HasMessageChannel()):
        await Bot.DeleteWebhook(ServerId)

      self.Payload.MessageChannel = ChannelToHookInto

    self.HasInteracted = True

    # Push a message to the activation request channel
    await self.CallbackFunction(self.Payload)

    # Respond to the user and kill the interactions
    MessageResponse:str = ""
    if (not Bot.Database.IsActivatedInServer(ServerId)):
      MessageResponse = Messages["settings"]["set_activation"]
    else:
      MessageResponse = Messages["settings"]["set_settings"]

    if (not interaction.is_expired()):
      try:
        await interaction.response.send_message(MessageResponse, ephemeral=True, delete_after=30.0)
      except:
        # If the interaction response is gone somehow, ignore any errors, it doesn't really matter too much.
        pass

    await self.StopInteractions()