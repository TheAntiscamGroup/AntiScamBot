# Discord Modal for submitting scam reports from other servers
from __future__ import annotations
from typing import TYPE_CHECKING, override
from discord import ui, TextStyle, Interaction
from Logger import Logger, LogLevel
from ScamReportPayload import ScamReportPayload
from TextWrapper import TextLibrary
from Utils import GetBot

Messages:TextLibrary = TextLibrary()

if TYPE_CHECKING:
  from Types import OptionalDiscordPerson, DiscordPerson

type TextInputView = ui.TextInput[ui.view.BaseView]

class SubmitScamReport(ui.Modal):
  ReportedUser:OptionalDiscordPerson = None
  # TODO: Make this a dropdown selector to make it easier for others. This probably shouldn't be done until everything
  # moves over to the ui.Label stuff.
  TypeOfScam:TextInputView  = ui.TextInput(label=Messages["report"]["type"]["label"], required=True,
                    placeholder=Messages["report"]["type"]["msg"], max_length=50, min_length=10)

  Reasoning:TextInputView = ui.TextInput(label=Messages["report"]["details"]["label"],
                    placeholder=Messages["report"]["details"]["msg"],
                    style=TextStyle.paragraph,
                    max_length=700, required=False)

  ScamEvidence:TextInputView = ui.TextInput(label=Messages["report"]["evidence"]["label"],
                    placeholder=Messages["report"]["evidence"]["msg"],
                    style=TextStyle.paragraph,
                    min_length=1,
                    max_length=4000,
                    required=True)

  def __init__(self, InReportUser:DiscordPerson):
    self.ReportedUser = InReportUser
    TruncatedName:str = InReportUser.name[:19]
    ModalTitle:str=f"Report {TruncatedName}[{InReportUser.id}]"[:45]
    super().__init__(title=ModalTitle)

  @override
  async def on_submit(self, interaction: Interaction):
    Bot = GetBot(interaction)
    if (self.ReportedUser is None):
      Logger.Log(LogLevel.Error, "Failed to get reported user on scam submission, somehow none???")
      await interaction.response.send_message(Messages["report"]["failed_submit"], ephemeral=True)
      return

    # Check to see if already banned.
    if (Bot.Database.DoesBanExist(self.ReportedUser.id)):
      await interaction.response.send_message(Messages["cmds_error"]["already_banned"], ephemeral=True, delete_after=20.0)
      return

    # Log the original data so we don't lose it
    Logger.Log(LogLevel.Log, f"Given evidence for report for id {self.ReportedUser.id} is {self.ScamEvidence.value}")
    Payload:ScamReportPayload = ScamReportPayload(interaction, self.ReportedUser,
      EvidenceList=self.ScamEvidence.value.split(),
      ScamType=self.TypeOfScam.value, Reasoning=self.Reasoning.value)

    await interaction.response.defer(thinking=True)
    Bot.AddAsyncTask(Bot.PostScamReport(Payload))

  @override
  async def on_error(self, interaction: Interaction, exceptionError: Exception):
    Logger.Log(LogLevel.Error, f"Encountered Exception with the scam report modal: {str(exceptionError)}")
    ReportedUserId = 0
    if (self.ReportedUser is not None):
      ReportedUserId = self.ReportedUser.id
    await interaction.response.send_message(Messages["report"]["error"].format(user=ReportedUserId), ephemeral=True)