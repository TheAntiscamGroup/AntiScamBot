# An ipc messaging hub for communicating between different Discord bot instances
# via multiprocessing
from Logger import Logger, LogLevel
from multiprocessing.connection import Listener, Connection, Client, wait
from BotEnums import RelayMessageType
from Config import Config
import selectors, os, traceback
from typing import cast

__all__ = ["RelayMessage", "RelayServer", "RelayClient"]

ConfigData:Config=Config()

def UseUnixSockets() -> bool:
  # Posix sockets don't require the networking bus, thus are technically more secure.
  if (ConfigData["UsingPosixSockets"] and os.name == "posix"):
    return True
  return False

class RelayMessage:
  Type:RelayMessageType = None # pyright: ignore[reportAssignmentType]
  Sender:int = -1
  Destination:int = -1
  Data = None

  # Type of the message
  # The origin of the message
  # Target client to send to
  # Any additional data
  def __init__(self, InType:RelayMessageType, InSender:int, InInstance:int=-1, InData=None):
    self.Type = InType
    self.Sender = InSender
    self.Destination = InInstance
    self.Data = InData

  @staticmethod
  def IsValid(InType) -> bool:
    return InType != None and type(InType).__name__ == "RelayMessage"

class RelayServer:
  Connections=[]
  # A very dumb way to keep track of error'd connections
  DeadConnections=[]
  InstancesToConnections={}
  FileLocation:str = ""
  ShouldStop:bool = False
  HasPrintedStop:bool = False
  ControlBotId:int = -1
  BotInstance = None

  def __init__(self, InControlBotId:int, InBotInstance=None):
    self.ControlBotId = InControlBotId
    self.BotInstance = InBotInstance
    if (UseUnixSockets()):
      self.ListenSocket = Listener(None, "AF_UNIX", backlog=10)
      self.FileLocation = self.ListenSocket.address # pyright: ignore[reportAttributeAccessIssue]
    else:
      NeedsNTHack:bool = False
      # This is a really dumb hack to get around a bug (allow for address reuse)
      # that should probably be fixed in the multiprocessing listener system.
      # It's been fixed upstream in the main socket library since 2010.
      if (os.name == "nt"):
        NeedsNTHack = True
        os.name = "posix"

      # Create listener socket.
      self.ListenSocket = Listener(("localhost", ConfigData["RelayPort"]), "AF_INET", backlog=10)

      # Switch back above hack if we changed it.
      if (NeedsNTHack):
        os.name = "nt"

    self.AcceptListener = selectors.DefaultSelector()
    # This is probably the silliest thing that doesn't exist in the listener
    # It really should be something accessible in the Listener class (a way to poll)
    self.AcceptListener.register(self.ListenSocket._listener._socket, selectors.EVENT_READ) # pyright: ignore[reportAttributeAccessIssue]

  def __del__(self):
    Logger.Log(LogLevel.Debug, "Shutting down listener service")
    self.ShouldStop = True

  def GetFileLocation(self):
    return self.FileLocation

  def GetInstanceForConnection(self, Connection) -> int:
    for key, value in enumerate(self.InstancesToConnections):
      if (value == Connection):
        return key

    return -1

  async def RestartAllConnections(self):
    if (self.BotInstance is None):
      Logger.Log(LogLevel.Notice, "BotInstance is somehow none while restarting all connections")
      return

    Logger.Log(LogLevel.Notice, "Restarting all connections and instances.")
    self.Connections = []
    self.InstancesToConnections = {}
    self.DeadConnections = []
    await self.BotInstance.StartAllInstances(BypassCheck=True, RestartMainClient=True)

  async def TickRelay(self):
    if (self.ShouldStop):
      if (not self.HasPrintedStop):
        Logger.Log(LogLevel.Error, "Warning: Relay was told to stop")
        self.HasPrintedStop = True
      return

    # Restart any dirty connections
    if (len(self.DeadConnections) > 0):
      await self.RestartAllConnections()
      return

    try:
      self.ListenForConnections()
      self.HandleRecv()
    except Exception as ex:
      Logger.Log(LogLevel.Error, f"Encountered error while handling connections, stopping server! Exception type: {type(ex)} | message: {str(ex)} | trace: {traceback.format_stack()}")
      self.ShouldStop = True
      return

  def ListenForConnections(self):
    AcceptEvents = self.AcceptListener.select(0)
    # We just iterate through the objects in the list, each one is a
    # connection we need to accept.
    for i in AcceptEvents:
      NewConnection = self.ListenSocket.accept()
      Logger.Log(LogLevel.Verbose, "A new connection has been made!")
      self.Connections.append(NewConnection)

  def HandleRecv(self):
    # This will make us only get the sockets that have messages waiting for them
    # And ignore everything else. The blocking operation should be fairly short.
    ConnectionsReady = wait(self.Connections, timeout=0)
    for ConnectionItr in ConnectionsReady:
      CurrentConnection = cast(Connection, ConnectionItr)
      # Read through all messages that we have for this connection
      while (CurrentConnection.poll(0)):
        RawMessage = None
        # Check to see if we were suddenly disconnected for whatever reason
        try:
          RawMessage = CurrentConnection.recv()
        except EOFError:
          self.DeadConnections.append(CurrentConnection)
          break

        # Check to see if the message is valid.
        if (not RelayMessage.IsValid(RawMessage)):
          continue
        Message:RelayMessage = RawMessage
        match Message.Type:
          case RelayMessageType.Hello:
            if (not Message.Sender in self.InstancesToConnections):
              self.InstancesToConnections[Message.Sender] = CurrentConnection
              Logger.Log(LogLevel.Notice, f"Established connection for {Message.Sender}")
            else:
              Logger.Log(LogLevel.Warn, f"Got a hello message from an known sender {Message.Sender}")
          case RelayMessageType.BanUser | RelayMessageType.UnbanUser | RelayMessageType.ProcessServerActivation | RelayMessageType.Kick:
            Logger.Log(LogLevel.Log, f"Sending command {Message.Type} to {len(self.Connections)} instances...")
            # Resend this message to literally everyone
            for ClientConnection in self.Connections:
              # Skip the main bot instance, there's no reason for it to get messages.
              if (ClientConnection == self.InstancesToConnections[self.ControlBotId]):
                continue
              ClientConnection.send(Message)
          case _:
            if (Message.Destination < 0 or Message.Destination >= len(self.InstancesToConnections)):
              Logger.Log(LogLevel.Warn, f"Message went to a bad destination! {str(Message.Destination)}")
              continue

            DestConnection = self.InstancesToConnections[Message.Destination]
            DestConnection.send(Message)

class RelayClient:
  BotID:int = -1

  def __init__(self, InFileLocation, InBotID:int=-1):
    self.Connection = None
    self.SentHello = False
    self.FunctionRouter = {}

    if (UseUnixSockets()):
      self.Connection = Client(InFileLocation, "AF_UNIX")
    else:
      self.Connection = Client(('localhost', ConfigData["RelayPort"]), "AF_INET")
    self.BotID = InBotID

  def __del__(self):
    self.Disconnect()

  def Disconnect(self):
    if (self.Connection is not None):
      Logger.Log(LogLevel.Log, f"Closing connection for instance {self.BotID}")
      self.Connection.close()
      self.Connection = None

  def GenerateMessage(self, Type:RelayMessageType, Destination:int=-1, TargetServer:int=-1,
                      HandlingCooldown:bool=False, TargetUserId:int=-1, NumToRetry=-1, AuthName:str="") -> RelayMessage:
    DataPayload={}
    match Type:
      case RelayMessageType.BanUser | RelayMessageType.UnbanUser | RelayMessageType.Kick:
        DataPayload={"TargetUser": TargetUserId, "AuthName": AuthName}
      case RelayMessageType.ProcessServerActivation:
        DataPayload={"TargetUser": TargetUserId, "TargetServer": TargetServer}
      case RelayMessageType.LeaveServer:
        DataPayload={"TargetServer": TargetServer}
      case RelayMessageType.ReprocessInstance:
        DataPayload={"NumToRetry": NumToRetry}
      case RelayMessageType.ReprocessBans:
        DataPayload={"TargetServer": TargetServer, "NumToRetry": NumToRetry,
                     "HandlingCooldown": HandlingCooldown}

    return RelayMessage(Type, self.BotID, Destination, DataPayload)

  def RegisterFunction(self, OnMessageType:RelayMessageType, FunctionToExecute):
    if (not OnMessageType in self.FunctionRouter):
      Logger.Log(LogLevel.Verbose, f"Registering function type {str(OnMessageType)} for {str(self)}")
      self.FunctionRouter[OnMessageType] = FunctionToExecute
    else:
      Logger.Log(LogLevel.Warn, f"Attempted to re-register function for {str(OnMessageType)} for {str(self)}")

  def SendHello(self):
    if (self.SentHello or self.Connection is None):
      Logger.Log(LogLevel.Warn, f"Bot #{self.BotID} unable to start up!")
      return

    Logger.Log(LogLevel.Log, f"Bot #{self.BotID} sending hello!")
    NewMessage:RelayMessage = self.GenerateMessage(RelayMessageType.Hello)
    self.Connection.send(NewMessage)
    self.SentHello = True

  # TODO: Make these functions automatically generated.
  def SendBan(self, UserId:int, InAuthName:str):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.BanUser, TargetUserId=UserId, AuthName=InAuthName))

  def SendKick(self, UserId:int, InAuthName:str):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.Kick, TargetUserId=UserId, AuthName=InAuthName))

  def SendUnban(self, UserId:int, InAuthName:str):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.UnbanUser, TargetUserId=UserId, AuthName=InAuthName))

  def SendLeaveServer(self, ServerToLeave:int, InstanceId):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.LeaveServer, Destination=InstanceId, TargetServer=ServerToLeave))

  def SendReprocessBans(self, ServerToRetry:int, InstanceId, InNumToRetry:int=-1, InHandlingCooldown:bool=False):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.ReprocessBans, Destination=InstanceId,
                                              TargetServer=ServerToRetry, NumToRetry=InNumToRetry,
                                              HandlingCooldown=InHandlingCooldown))

  def SendReprocessInstanceBans(self, InstanceId, InNumToRetry:int=-1):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.ReprocessInstance, Destination=InstanceId, NumToRetry=InNumToRetry))

  def SendPing(self, InstanceToTarget):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.Ping, Destination=InstanceToTarget))

  def SendActivationForServerInstance(self, UserId, ServerId, InstanceToTarget):
    if (self.Connection is None or self.BotID != ConfigData["ControlBotID"]):
      return
    self.Connection.send(self.GenerateMessage(RelayMessageType.ProcessServerActivation, TargetUserId=UserId, TargetServer=ServerId, Destination=InstanceToTarget))

  async def RecvMessage(self):
    if (self.Connection is None):
      return

    # While we have active messages on this socket
    while (self.Connection.poll(0)):
      RawMessage = None
      try:
        RawMessage = self.Connection.recv()
      except Exception as recvex:
        Logger.Log(LogLevel.Error, f"Encountered an error with {self.BotID} recv! {type(recvex)} | message: {str(recvex)} | trace: {traceback.format_stack()}")
        break

      if (not RelayMessage.IsValid(RawMessage)):
        Logger.Log(LogLevel.Warn, f"Bot #{self.BotID} received relay message is not a type of RelayMessage")
        break

      RelayedMessage:RelayMessage = RawMessage
      # If the message doesn't have a handler
      if (not RelayedMessage.Type in self.FunctionRouter):
        Logger.Log(LogLevel.Warn, f"We do not have a message router for type {RelayedMessage.Type}")
        break
      else:
        Logger.Log(LogLevel.Log, f"Bot #{self.BotID} just got a message of type {RelayedMessage.Type}")

      # Rework the arguments in a way that we can explode map them programmatically
      Arguments = None
      if (RelayedMessage.Data is not None):
        match RelayedMessage.Type:
          case RelayMessageType.BanUser | RelayMessageType.UnbanUser | RelayMessageType.Kick:
            Arguments = {"TargetId": RelayedMessage.Data["TargetUser"], "AuthName":RelayedMessage.Data["AuthName"]}
          case RelayMessageType.ProcessServerActivation:
            Arguments = {"UserId": RelayedMessage.Data["TargetUser"], "ServerId": RelayedMessage.Data["TargetServer"]}
          case RelayMessageType.LeaveServer:
            Arguments = {"ServerId": RelayedMessage.Data["TargetServer"]}
          case RelayMessageType.ReprocessBans:
            Arguments = {"ServerId": RelayedMessage.Data["TargetServer"],
                         "LastActions": RelayedMessage.Data["NumToRetry"],
                         "HandlingCooldown": RelayedMessage.Data["HandlingCooldown"]}
          case RelayMessageType.ReprocessInstance:
            Arguments = {"LastActions": RelayedMessage.Data["NumToRetry"]}

      try:
        if (Arguments is None):
          self.FunctionRouter[RelayedMessage.Type]()
        else:
          self.FunctionRouter[RelayedMessage.Type](**Arguments)
      except Exception as ex:
        Logger.Log(LogLevel.Warn, f"Bot #{self.BotID} Failed to handle recv message, got exception type: {type(ex)} | message: {str(ex)} | trace: {traceback.format_stack()}")