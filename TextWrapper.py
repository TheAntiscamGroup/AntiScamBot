# A class that reads in a text.toml file that can be used to specify messages to an user.
# It works a lot like the Config class.
from functools import reduce
from operator import getitem
from typing import Any, cast

import tomllib

def get_str(input: Any) -> str:  # pyright: ignore[reportAny, reportExplicitAny]
  return cast(str, input)

class TextLibrary():
  __HasLoaded = False
  StrTable: Any = {}  # pyright: ignore[reportExplicitAny]
  def __new__(cls):
    if not hasattr(cls, 'instance'):
      cls.instance: TextLibrary = super(TextLibrary, cls).__new__(cls)
    return cls.instance

  def __init__(self):
    self.Load()

  def Load(self) -> None:
    if (self.__HasLoaded):
      return

    with open("TextStrings.toml", "rb") as strings_file:
      Data: dict[str, Any] = tomllib.load(strings_file)  # pyright: ignore[reportExplicitAny]
      self.StrTable = Data

    self.__HasLoaded = True

  def __getitem__(self, item: tuple[str, ...]) -> str:
    return reduce(getitem, item, self.StrTable) # pyright: ignore[reportAny]

if __name__ == '__main__':
  Messages:TextLibrary = TextLibrary()
  print(Messages["setup", "stats", "msg"].format(number=255))