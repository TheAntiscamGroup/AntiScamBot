from __future__ import annotations
from collections.abc import Coroutine
from typing import Any, Callable
from discord import Guild, TextChannel, User, Member, ForumChannel

type OptionalForum = ForumChannel|None
type OptionalChannel = TextChannel|None
type OptionalGuild = Guild|None
type DiscordPerson = User|Member
type OptionalDiscordMember = Member|None
type OptionalDiscordPerson = DiscordPerson|None
type AsyncTaskFunc = Coroutine[Any, Callable[..., Any], Any]
type InstanceCallable = Callable[..., None|bool]
type InstanceCallableArguments = dict[str, int|str|bool]