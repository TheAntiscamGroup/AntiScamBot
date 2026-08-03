from __future__ import annotations
from typing import cast, TYPE_CHECKING

if TYPE_CHECKING:
  from discord import Interaction, Webhook
  from Types import DiscordPerson

class ScamReportPayload():
  ReportingUserName:str
  ReportingUserId:int
  ReportedServer:str
  ReportedServerId:int
  ReportedUserGlobalName:str
  ReportedUserName:str
  ReportedUserId:int
  TypeOfScam:str
  Reasoning:str
  Evidence:list[str]
  ReportWebhook:Webhook

  def __init__(self, interaction:Interaction, ReportedUser:DiscordPerson, EvidenceList:list[str], ScamType:str, Reasoning:str) -> None:
    self.ReportingUserName = interaction.user.name
    self.ReportingUserId = interaction.user.id
    self.ReportedServerId = cast(int, interaction.guild_id)
    self.ReportWebhook = interaction.followup
    self.ReportedUserGlobalName = ReportedUser.display_name
    self.ReportedUserName = ReportedUser.name
    self.ReportedUserId = ReportedUser.id
    self.Evidence = EvidenceList
    self.ReportedServer = interaction.guild.name if interaction.guild is not None else ""
    self.Reasoning = Reasoning
    self.TypeOfScam = ScamType
