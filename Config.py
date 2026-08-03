# Config singleton for loading configuration data from a json file
from __future__ import annotations
import os, copy, json
from typing import Any, Self, TypeVar, cast, get_args, override
from dotenv import load_dotenv
from Logger import LogLevel, Logger

load_dotenv()

type ConfigValues = int|bool|str|float|list[int]
SafeGetRet = TypeVar('SafeGetRet', str,list[int],float,bool,int)
type SubInstanceValues = dict[str, str|None]|None

class Config():
  __HasLoaded:bool = False
  __InternalData:dict[str, ConfigValues] = {}
  def __new__(cls) -> Self|'Config':
    if not hasattr(cls, 'instance'):
      cls.instance:'Config' = super(Config, cls).__new__(cls)
    return cls.instance

  def __init__(self):
    self.Load()

  def Load(self):
    if (self.__HasLoaded):
      return

    with open(self.GetConfigFile(), "r") as config_file:
      self.__InternalData = json.load(config_file)

    self.__HasLoaded = True
    Logger.Log(LogLevel.Notice, "Configuration Loaded!")

  def Save(self):
    StagingSave = copy.deepcopy(self.__dict__)
    with open(self.GetConfigFile(), "wt") as config_file:
      json.dump(StagingSave, config_file, indent=3)

  def get(self, item:str, default:SafeGetRet) -> SafeGetRet:
    if (self.IsValid(item, ExpectType=get_args(type)[0])):
      return cast(SafeGetRet, self.__InternalData[item])

    return default

  def IsValid(self, Key:str, ExpectType:type[Any]) -> bool:
    try:
      EntryValue:Any = self.__InternalData[Key]
      if (not isinstance(EntryValue, ExpectType)):
        return False

      if (type(EntryValue) is int):
        if (EntryValue <= 0):
          return False
        else:
          return True
      elif (type(EntryValue) is str):
        if (len(EntryValue) == 0):
          return False

        return True
      return False
    except(Exception):
      return False

  @staticmethod
  def GetAllSubTokens() -> SubInstanceValues:
    if (not os.path.exists(Config.GetAPIKeysFile())):
      return None

    with open(Config.GetAPIKeysFile(), "r") as crypto_file:
      return json.load(crypto_file)

  @staticmethod
  def GetToken(ForInstance:int=-1) -> str:
    if (ForInstance <= 0):
      return os.getenv("DISCORD_TOKEN") or ""
    else:
      CryptoKeys:SubInstanceValues = Config.GetAllSubTokens()
      if (CryptoKeys is None):
        return ""
      InstanceStr:str = str(ForInstance)
      InstanceVal:str|None = CryptoKeys[InstanceStr]
      if (InstanceVal is None):
        return ""
      return InstanceVal

  @staticmethod
  def GetNumberOfInstances() -> int:
    CryptoKeys: SubInstanceValues = Config.GetAllSubTokens()
    if (CryptoKeys is None):
      return 0
    return len(CryptoKeys)

  @staticmethod
  def GetDBFile() -> str:
    return os.getenv("DATABASE_FILE") or ""

  @staticmethod
  def GetConfigFile() -> str:
    return os.getenv("CONFIG_FILE") or ""

  @staticmethod
  def GetAPIKeysFile() -> str:
    return os.getenv("API_KEYS") or ""

  @staticmethod
  def GetBackupLocation() -> str:
    return os.getenv("BACKUP_LOCATION") or ""

  # In this mode, bans do not actually process, nor do they send out to any users.
  @staticmethod
  def IsDevelopment() -> bool:
    DevOption = os.getenv("DEVELOPMENT_MODE")
    if (DevOption is None):
      return False

    if (DevOption.lower() == "false"):
      return False
    else:
      return True

  @override
  def __str__(self) -> str:
    return f"{str(self.__dict__)}"

  def Dump(self):
    print(self)

if __name__ == '__main__':
  ConfigData:Config=Config()
  ConfigData.Dump()
  print(ConfigData.IsValid("NotificationChannel", int))
  print(ConfigData.IsValid("ReportChannelTag", str))