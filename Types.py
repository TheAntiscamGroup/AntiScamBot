from __future__ import annotations
from typing import TYPE_CHECKING
from discord import TextChannel, User, Member

if TYPE_CHECKING:
  from ScamGuard import ScamGuard
  from BotBase import DiscordBot

# this is hilariously valid because it uses annotations
# we could probably just have it be of DiscordBot since ScamGuard inherits
# but typing is silly.
type BotType = 'DiscordBot|ScamGuard'
type OptionalChannel = TextChannel|None
type DiscordPerson = User|Member
type OptionalDiscordMember = Member|None
type OptionalDiscordPerson = DiscordPerson|None