from enum import IntEnum, auto

class CompareEnum(IntEnum):  
  def __lt__(self, other):
    if self.__class__ is other.__class__:
      return self.value < other.value
    return NotImplemented
      
  def __str__(self) -> str:
    return self.name

class ModerationAction(CompareEnum):
  Nothing=auto()
  Ban=auto()
  Unban=auto()
  Kick=auto()

# Enum that expresses Bans on a global bot level
class BanAction(CompareEnum):
  Banned=auto()
  Unbanned=auto()
  Duplicate=auto()
  NotExist=auto()
  DBError=auto()
  
# Enum that expresses bans on a server level based off discord returns
class BanResult(CompareEnum):
  Processed=auto()
  NotBanned=auto()
  InvalidUser=auto()
  LostPermissions=auto()
  BansExceeded=auto()
  ServerOwner=auto()
  ServiceError=auto()
  Error=auto()
  
class RelayMessageType(CompareEnum):
  Hello=auto()
  BanUser=auto()
  UnbanUser=auto()
  LeaveServer=auto()
  ReprocessBans=auto()
  ReprocessInstance=auto()
  # This activates specifically for one server
  ProcessServerActivation=auto()
  Ping=auto()
  Kick=auto()
  
class ChannelPostPermissions(CompareEnum):
  NoPerms=auto()
  PostDirectly=auto()
  CanThread=auto()
