from typing import Any, Callable, Coroutine, Self, cast, TYPE_CHECKING, override

if TYPE_CHECKING:
  from asyncio import Task
  from discord.guild import GuildChannel
  from discord.threads import Thread
  from discord.abc import PrivateChannel
  from discord.types.channel import NewsChannel
  from discord import TextChannel, User, Member, ui
  from BotBase import DiscordBot
  from ScamGuard import ScamGuard
  type DiscordChannels = TextChannel|GuildChannel|Thread|PrivateChannel|NewsChannel
  type AsyncCall = Coroutine[Any, Any, Any]
  type AsyncTask = Task[AsyncCall]
  type ValidUser = User|Member
  type DiscordUser = ValidUser|None
  type ValidBot = DiscordBot|ScamGuard
  type BotType = DiscordBot|ScamGuard|None
  type ViewButton = ui.Button[ui.view.BaseView]