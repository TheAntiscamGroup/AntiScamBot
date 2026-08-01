from __future__ import annotations
from typing import cast, TYPE_CHECKING
from discord import Object, User, Interaction
from Types import OptionalDiscordMember, BotType

if TYPE_CHECKING:
  from Types import OptionalDiscordPerson

def GetBot(interaction:Interaction) -> BotType:
  return cast(BotType, interaction.client)

def GetDiscordUser(TargetId:int) -> User:
  return cast(User, Object(TargetId))

def GetDiscordMember(InUser:OptionalDiscordPerson) -> OptionalDiscordMember:
  return cast(OptionalDiscordMember, InUser)