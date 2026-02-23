# A class that reads in a text.toml file that can be used to specify messages to an user.
# It works a lot like the Config class.
import tomllib

class TextLibrary():
  __HasLoaded = False
  def __new__(cls):
    if not hasattr(cls, 'instance'):
      cls.instance = super(TextLibrary, cls).__new__(cls)
    return cls.instance

  def __init__(self):
    self.Load()

  def Load(self):
    if (self.__HasLoaded):
      return

    Data = {}

    with open("TextStrings.toml", "rb") as strings_file:
      Data = tomllib.load(strings_file)

    self.__dict__ = Data
    self.__HasLoaded = True

  def __getitem__(self, item):
    return self.__dict__[item]

if __name__ == '__main__':
  Messages:TextLibrary = TextLibrary()
  print(Messages["setup"]["stats"]["msg"].format(number=255))