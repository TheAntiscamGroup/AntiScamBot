# A class that reads in a text.toml file that can be used to specify messages to an user.
# It works a lot like the Config class.
from __future__ import annotations
from typing import Any, Self, TypeVar, Union, cast
import tomllib

# The most unholy of pyright hacks that accomplish these lookups nicely
type NestedText = dict[str, Union['NestedText', str]]
type NestedStrDict = dict[str, 'str|NestedStrDict']
TextLibStrArg = TypeVar('TextLibStrArg', str,NestedStrDict,Any)

class TextLibrary():
  __HasLoaded: bool = False
  def __new__(cls) -> Self | 'TextLibrary':
    if not hasattr(cls, 'instance'):
      cls.instance:'TextLibrary' = super(TextLibrary, cls).__new__(cls)
    return cls.instance

  def __init__(self):
    self.Load()

  def Load(self):
    if (self.__HasLoaded):
      return

    Data:NestedText = {}

    with open("TextStrings.toml", "rb") as strings_file:
      Data = tomllib.load(strings_file)

    self.__dict__:NestedText = Data
    self.__HasLoaded = True

  def __getitem__(self, item: TextLibStrArg) -> TextLibStrArg:
    return cast(TextLibStrArg, self.__dict__[str(item)])

if __name__ == '__main__':
  Messages:TextLibrary = TextLibrary()
  print(Messages["setup"]["stats"]["msg"].format(number=255))