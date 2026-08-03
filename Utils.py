from __future__ import annotations
from typing import cast, TYPE_CHECKING
from discord import Object, User, Interaction
from Types import OptionalDiscordMember
from BotBase import DiscordBot

if TYPE_CHECKING:
  from Types import OptionalDiscordPerson

def GetBot(interaction:Interaction) -> DiscordBot:
  return cast(DiscordBot, interaction.client)

def GetDiscordUser(TargetId:int) -> User:
  return cast(User, Object(TargetId))  # pyright: ignore[reportInvalidCast]

def GetDiscordMember(InUser:OptionalDiscordPerson) -> OptionalDiscordMember:
  return cast(OptionalDiscordMember, InUser)