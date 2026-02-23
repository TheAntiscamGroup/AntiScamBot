# ScamGuard application commands that are used on every server
from typing import cast
from CommandHelpers import TargetIdTransformer
from discord import app_commands, Interaction, Member, User, Embed
from ScamReportModal import SubmitScamReport
from BotServerSettings import ServerSettingsView
from TextWrapper import TextLibrary
from Config import Config

Messages:TextLibrary = TextLibrary()
ConfigData:Config = Config()

@app_commands.guild_only()
class GlobalScamCommands(app_commands.Group):
  def GetInstance(self):
    return self.extras["instance"]

  def IsActivated(self, InteractionId:int) -> bool:
    return (self.GetInstance().Database.IsActivatedInServer(InteractionId))

  def CanReport(self, InteractionId:int) -> bool:
    return (self.GetInstance().Database.CanServerReport(InteractionId))

  @app_commands.command(name="check", description="Checks to see if a Discord user id is banned")
  @app_commands.checks.has_permissions(ban_members=True)
  @app_commands.checks.cooldown(1, 2.0)
  async def ScamCheck_Global(self, interaction:Interaction, target:app_commands.Transform[int, TargetIdTransformer]):
    if (target <= -1):
      await interaction.response.send_message(Messages["cmds_error"]["invalid_id"], ephemeral=True, delete_after=5.0)
      return

    InteractionId:int|None = interaction.guild_id
    if (InteractionId is None):
      await interaction.response.send_message(Messages["cmds_error"]["only_in_server"])
      return

    if (self.IsActivated(InteractionId)):
      ResponseEmbed:Embed = await self.GetInstance().CreateBanEmbed(target)
      await interaction.response.send_message(embed = ResponseEmbed)
    else:
      await interaction.response.send_message(Messages["cmds_error"]["needs_activation"])

  @app_commands.command(name="report", description="Report an Discord User")
  @app_commands.checks.has_permissions(ban_members=True)
  @app_commands.checks.cooldown(1, 5.0)
  async def ReportScam_Global(self, interaction:Interaction, target:app_commands.Transform[int, TargetIdTransformer]):
    if (interaction.guild_id == ConfigData["ControlServer"]):
      await interaction.response.send_message(Messages["cmds_error"]["in_control_server"], ephemeral=True, delete_after=5.0)
      return

    InteractionId:int|None = interaction.guild_id
    if (InteractionId is None):
      await interaction.response.send_message(Messages["cmds_error"]["only_in_server"])
      return

    # Block any usages of the commands if the server is not activated.
    if (not self.IsActivated(InteractionId)):
      await interaction.response.send_message(Messages["cmds_error"]["needs_activation"], ephemeral=True, delete_after=10.0)
      return

    # Check if the server is barred from reporting
    if (not self.CanReport(InteractionId)):
      await interaction.response.send_message(Messages["cmds_error"]["remote_reports_banned"], ephemeral=True, delete_after=10.0)
      return

    # If it cannot be transformed, print an error
    if (target == -1):
      await interaction.response.send_message(Messages["cmds_error"]["invalid_id"], ephemeral=True)
      return

    UserToSend:Member|User|None = await self.GetInstance().LookupUser(target, ServerToInspect=interaction.guild)
    # If the user is no longer in said server, then do a global lookup
    if (UserToSend is None):
      UserToSend = await self.GetInstance().LookupUser(target)

    # If the user is still invalid, then ask for a manual report.
    if (UserToSend is None):
      await interaction.response.send_message(Messages["cmds_error"]["do_manual_report"], ephemeral=True)
      return

    # Check if the user is already banned
    if (self.GetInstance().Database.DoesBanExist(UserToSend.id)):
      await interaction.response.send_message(Messages["cmds_error"]["already_banned"], ephemeral=True, delete_after=20.0)

    await interaction.response.send_modal(SubmitScamReport(UserToSend))

  @app_commands.command(name="setup", description="Set up ScamGuard")
  @app_commands.checks.has_permissions(ban_members=True)
  @app_commands.checks.cooldown(1, 5.0)
  async def SetupScamGuard_Global(self, interaction:Interaction):
    if (interaction.guild_id == ConfigData["ControlServer"]):
      await interaction.response.send_message(Messages["cmds_error"]["in_control_server"], ephemeral=True, delete_after=5.0)
      return

    InteractionId:int|None = interaction.guild_id
    if (InteractionId is None):
      await interaction.response.send_message(Messages["cmds_error"]["only_in_server"])
      return

    # Block any usages of the setup command if the server is activated.
    if (not self.IsActivated(InteractionId)):
      await self.GetInstance().ServerSetupHelper.OpenServerSetupModel(interaction)
    else:
      await interaction.response.send_message(Messages["cmds_error"]["server_activated"], ephemeral=True, delete_after=15.0)

  @app_commands.command(name="tool", description="Provides a link to install the ScamGuard User Tool")
  @app_commands.describe(whisper='If the link should be not whispered (only changeable if you are a mod)')
  @app_commands.checks.cooldown(1, 2.0)
  async def InstallScamGuardUser_Global(self, interaction:Interaction, whisper:bool):
    # Always be a whisper unless you are an admin/mod
    ShouldEphermeral:bool = True
    # Was this in a server
    if (interaction.guild_id is not None and interaction.channel is not None):
      # Check to see if a moderator typed this command
      if (interaction.channel.permissions_for(cast(Member, interaction.user)).ban_members):
        ShouldEphermeral = whisper

    await interaction.response.send_message("https://discord.com/oauth2/authorize?client_id=1443130827662823557", delete_after=10.0, ephemeral=ShouldEphermeral)

  @app_commands.command(name="config", description="Set ScamGuard Settings")
  @app_commands.checks.has_permissions(ban_members=True)
  @app_commands.checks.cooldown(1, 5.0)
  async def ConfigScamGuard_Global(self, interaction:Interaction):
    if (interaction.guild_id == ConfigData["ControlServer"]):
      await interaction.response.send_message(Messages["cmds_error"]["in_control_server"], ephemeral=True, delete_after=5.0)
      return

    InteractionId:int|None = interaction.guild_id
    if (InteractionId is None):
      await interaction.response.send_message(Messages["cmds_error"]["only_in_server"])
      return

    if (not self.IsActivated(InteractionId)):
      await interaction.response.send_message(Messages["cmds_error"]["needs_activation"], ephemeral=True, delete_after=30.0)
    else:
      await interaction.response.defer(thinking=True)
      BotInstance = self.GetInstance()
      ResponseEmbed:Embed = BotInstance.CreateBaseEmbed(Messages["cmds"]["settings"])
      BotInstance.AddSettingsEmbedInfo(ResponseEmbed)

      SettingsView:ServerSettingsView = ServerSettingsView(self.GetInstance().ApplySettings, interaction)
      await SettingsView.Send(interaction, [ResponseEmbed])

  @app_commands.command(name="info", description="Info & Stats about ScamGuard")
  @app_commands.checks.cooldown(1, 5.0)
  async def HelpScamGuard_Global(self, interaction:Interaction):
    ResponseEmbed:Embed = self.GetInstance().CreateInfoEmbed()
    await interaction.response.send_message(embed=ResponseEmbed, silent=True)