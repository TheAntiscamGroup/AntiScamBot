from discord import ui, Guild, ButtonStyle, Interaction, User, Member, TextChannel, Permissions
from ModalHelpers import YesNoSelector, SelfDeletingView, ModChannelSelector
from BotDatabaseSchema import Server
from Logger import Logger, LogLevel
from TextWrapper import TextLibrary
from Config import Config
from typing import cast

Messages:TextLibrary = TextLibrary()

class BotSettingsPayload:
  InteractiveUser:User|Member|None = None
  WebHookRequired:bool = False
  KickSusRequired:bool = False

  # These settings should get pulled from the db
  Server:Guild|None = None
  MessageChannel:TextChannel|None = None
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

  def LoadFromDB(self, BotInstance):
    DB = BotInstance.Database
    ServerInfo:Server = DB.GetServerInfo(self.GetServerID())
    if (int(ServerInfo.activation_state) == 0):
      self.KickSusRequired = self.WebHookRequired = True
    else:
      self.WantsWebhooks = bool(ServerInfo.has_webhooks)
      self.KickSusUsers = bool(ServerInfo.kick_sus_users)

    # Check to see what the setting is for messaging channel, if it's 0, leave MessageChannel as None
    # else load up the text channel value
    if (int(ServerInfo.message_channel) != 0):
      self.MessageChannel = BotInstance.get_channel(ServerInfo.message_channel)

class InstallWebhookSelector(YesNoSelector):
  def GetYesDescription(self) -> str:
    return Messages["selector"]["webhook"]["yes"]

  def GetNoDescription(self) -> str:
    return Messages["selector"]["webhook"]["no"]

  def GetPlaceholder(self) -> str:
    return Messages["selector"]["webhook"]["placeholder"]

  def SetNotRequiredIfValueSet(self) -> bool:
    return True

class KickSuspiciousUsersSelector(YesNoSelector):
  def GetYesDescription(self) -> str:
    return Messages["selector"]["kick"]["yes"]

  def GetNoDescription(self) -> str:
    return Messages["selector"]["kick"]["no"]

  def GetPlaceholder(self) -> str:
    return Messages["selector"]["kick"]["placeholder"]

  def SetNotRequiredIfValueSet(self) -> bool:
    return True

class ServerSettingsView(SelfDeletingView):
  ChannelSelect:ModChannelSelector = None # pyright: ignore[reportAssignmentType]
  WebhookSelector:InstallWebhookSelector = None # pyright: ignore[reportAssignmentType]
  SuspiciousUserKicks:KickSuspiciousUsersSelector = None # pyright: ignore[reportAssignmentType]
  CallbackFunction = None
  Payload:BotSettingsPayload = None # pyright: ignore[reportAssignmentType]

  def __init__(self, InCB, interaction: Interaction):
    super().__init__()
    ConfigData:Config = Config()

    # Pull current data
    self.Payload = BotSettingsPayload()
    self.Payload.Server = interaction.guild
    self.Payload.InteractiveUser = interaction.user
    self.Payload.LoadFromDB(interaction.client)

    self.ChannelSelect = ModChannelSelector(RowPos=0)
    # If we don't have a message channel selected, force this setting here.
    if (not self.Payload.HasMessageChannel()):
      self.ChannelSelect.SetRequired()

    self.add_item(self.ChannelSelect)

    if (ConfigData["AllowWebhookInstall"]):
      self.WebhookSelector = InstallWebhookSelector(RowPos=1)
      if (not self.Payload.WebHookRequired):
        self.WebhookSelector.SetCurrentValue(self.Payload.WantsWebhooks)
      self.add_item(self.WebhookSelector)

    if (ConfigData["AllowSuspiciousUserKicks"]):
      self.SuspiciousUserKicks = KickSuspiciousUsersSelector(RowPos=2)
      if (not self.Payload.KickSusRequired):
        self.SuspiciousUserKicks.SetCurrentValue(self.Payload.KickSusUsers)
      self.add_item(self.SuspiciousUserKicks)

    self.CallbackFunction = InCB

  @ui.button(label="Confirm Settings", style=ButtonStyle.success, row=4)
  async def setup(self, interaction: Interaction, button: ui.Button):
    # Couple of quick reference settings
    DB = interaction.client.Database # pyright: ignore[reportAttributeAccessIssue]
    ServerId:int = self.Payload.GetServerID()
    ConfigData:Config = Config()

    # State settings
    MadeWebhookSelection:bool = self.WebhookSelector.HasValue()
    ChannelSelectRequired:bool = self.ChannelSelect.min_values == 1
    ChannelSelectChanged:bool = False

    # Check if we can install webhooks
    if (ConfigData["AllowWebhookInstall"]):
      if (MadeWebhookSelection):
        self.Payload.WantsWebhooks = self.WebhookSelector.GetValue() or False
      elif self.WebhookSelector.IsRequired():
        await interaction.response.send_message(Messages["selector"]["choose"], ephemeral=True, delete_after=10.0)
        return

    # Check to see if the channel option has changed. This code specifically will allow it for the user to not change the setting and still
    # use the old values
    if (not ChannelSelectRequired):
      CurrentChannelSetting:int|None = DB.GetChannelIdForServer(ServerId)
      # Grab what the user selected if they have any selections
      NewChannelSetting:int|None = self.ChannelSelect.values[0].id if self.ChannelSelect.values else None
      # If this is not required, and the user has made a selection and the selection is not the current setting, then do an update.
      if (NewChannelSetting is not None and CurrentChannelSetting != NewChannelSetting):
        Logger.Log(LogLevel.Debug, f"Channel Selection has changed from {CurrentChannelSetting} to {NewChannelSetting}")
        ChannelSelectRequired = True
        ChannelSelectChanged = True

    # Resolve the selected channel to send messages into
    if (ChannelSelectRequired):
      if (await self.ChannelSelect.IsValid(interaction, True) == False):
        return

      ChannelToHookInto:TextChannel|None = cast(TextChannel|None, self.ChannelSelect.values[0].resolve())
      if (self.Payload.WantsWebhooks):
        # If the channel selection option has changed from the original setting, delete the original webhook
        if (ChannelSelectChanged):
          Logger.Log(LogLevel.Debug, "Deleting old webhook reference")
          await interaction.client.DeleteWebhook(ServerId) # pyright: ignore[reportAttributeAccessIssue]

        if (interaction.client.user is None):
          Logger.Log(LogLevel.Error, "ScamGuard lost login during this interaction")
          return

        BotMember:Member|None = cast(Guild, interaction.guild).get_member(interaction.client.user.id)
        if (BotMember is None):
          Logger.Log(LogLevel.Error, "Bot was invalid during setup somehow")
          return
        if (ChannelToHookInto is not None):
          PermissionsObj:Permissions = ChannelToHookInto.permissions_for(BotMember)

          # Check to see if we can manage webhooks in that channel, if the user wants us to add ban notifications
          if (not PermissionsObj.manage_webhooks):
            await interaction.response.send_message(Messages["selector"]["webhook"]["need_perm"].format(channel=ChannelToHookInto.mention), ephemeral=True, delete_after=100.0)
            return
        else:
          Logger.Log(LogLevel.Warn, "ChannelToHookInto was None, which should not be an accessible area?")
          await interaction.response.send_message(Messages["selector"]["webhook"]["text_channel"], ephemeral=True, delete_after=20.0)
          return
      # The user wanted webhooks but doesn't want them any more, delete the webhook from the channel.
      elif (self.WebhookSelector.HasValueChanged() and self.Payload.HasMessageChannel()):
        await interaction.client.DeleteWebhook(ServerId) # pyright: ignore[reportAttributeAccessIssue]

      self.Payload.MessageChannel = ChannelToHookInto

    self.HasInteracted = True

    # Push a message to the activation request channel
    if (self.CallbackFunction is None):
      Logger.Log(LogLevel.Error, "Somehow the callback function on the server settings is None...")
      return

    await self.CallbackFunction(self.Payload)

    # Respond to the user and kill the interactions
    MessageResponse:str = ""
    if (not interaction.client.Database.IsActivatedInServer(ServerId)): # pyright: ignore[reportAttributeAccessIssue]
      MessageResponse = Messages["settings"]["set_activation"]
    else:
      MessageResponse = Messages["settings"]["set_settings"]

    await interaction.response.send_message(MessageResponse, ephemeral=True, delete_after=30.0)
    await self.StopInteractions()