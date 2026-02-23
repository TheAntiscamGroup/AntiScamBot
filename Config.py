# Config singleton for loading configuration data from a json file
import os, copy, json
from dotenv import load_dotenv
from Logger import LogLevel, Logger

load_dotenv()

class Config():
  __HasLoaded = False
  def __new__(cls):
    if not hasattr(cls, 'instance'):
      cls.instance = super(Config, cls).__new__(cls)
    return cls.instance

  def __init__(self):
    self.Load()

  def Load(self):
    if (self.__HasLoaded):
      return

    Data = {}

    with open(self.GetConfigFile(), "r") as config_file:
      Data = json.load(config_file)

    self.__dict__ = Data
    self.__HasLoaded = True
    Logger.Log(LogLevel.Notice, "Configuration Loaded!")

  def Save(self):
    StagingSave = copy.deepcopy(self.__dict__)
    with open(self.GetConfigFile(), "wt") as config_file:
      json.dump(StagingSave, config_file, indent=3)

  def __getitem__(self, item):
     return self.__dict__[item]

  def IsValid(self, Key:str, ExpectType) -> bool:
    try:
      EntryValue = self[Key]
      EntryValueType = type(EntryValue)
      if (EntryValueType != ExpectType):
        return False

      if (EntryValueType == int):
        if (EntryValue <= 0):
          return False
        else:
          return True
      elif (EntryValueType == str):
        if (len(EntryValue) == 0):
          return False

        return True
      return False
    except(Exception):
      return False

  @staticmethod
  def GetAllSubTokens():
    if (not os.path.exists(Config.GetAPIKeysFile())):
      return {}

    with open(Config.GetAPIKeysFile(), "r") as crypto_file:
      return json.load(crypto_file)

  @staticmethod
  def GetToken(ForInstance:int=-1) -> str:
    if (ForInstance <= 0):
      return os.getenv("DISCORD_TOKEN") or ""
    else:
      CryptoKeys = Config.GetAllSubTokens()
      InstanceStr:str = str(ForInstance)
      if (CryptoKeys[InstanceStr] is None):
        return ""
      return CryptoKeys[InstanceStr]

  @staticmethod
  def GetNumberOfInstances() -> int:
    CryptoKeys = Config.GetAllSubTokens()
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

  def __str__(self):
    return f"{str(self.__dict__)}"

  def Dump(self):
    print(self)