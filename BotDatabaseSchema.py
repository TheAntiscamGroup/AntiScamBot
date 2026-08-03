from datetime import datetime
from sqlalchemy import Integer, DateTime, String
from sqlalchemy.sql import func, null
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column

class Base(DeclarativeBase):
  pass

class Migration(Base):
  __tablename__:str = "migrations"

  id:MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  database_version:MappedColumn[int] = mapped_column(Integer, nullable=False)
  created_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now())
  updated_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())

class Ban(Base):
  __tablename__:str = "bans"

  id:MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  discord_user_id:MappedColumn[str] = mapped_column(String(32), unique=True, nullable=False)
  assigner_discord_user_id:MappedColumn[str] = mapped_column(String(32), nullable=False)
  assigner_discord_user_name:MappedColumn[str] = mapped_column(String(32), nullable=False)
  created_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now())
  updated_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  evidence_thread:MappedColumn[int|None] = mapped_column(Integer, nullable=True, server_default=null())

class Server(Base):
  __tablename__:str = "servers"

  id:MappedColumn[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
  bot_instance_id:MappedColumn[int] = mapped_column(Integer, nullable=False, server_default="0")
  discord_server_id:MappedColumn[str] = mapped_column(String(32), unique=True, nullable=False)
  owner_discord_user_id:MappedColumn[str] = mapped_column(String(32), nullable=False)
  activation_state:MappedColumn[int] = mapped_column(Integer, server_default="0")
  activator_discord_user_id:MappedColumn[str] = mapped_column(String(32), nullable=False, server_default='-1')
  created_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now())
  updated_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  message_channel:MappedColumn[int] = mapped_column(Integer, server_default="0")
  has_webhooks:MappedColumn[int] = mapped_column(Integer, server_default="0")
  kick_sus_users:MappedColumn[int] = mapped_column(Integer, server_default="0")
  can_report:MappedColumn[int] = mapped_column(Integer, server_default="1")
  should_ban_in:MappedColumn[int] = mapped_column(Integer, server_default="1")

class ExhaustedServer(Base):
  __tablename__:str = "exhausted_servers"

  discord_server_id:MappedColumn[str] = mapped_column(String(32), primary_key=True, unique=True, nullable=False)
  current_pos:MappedColumn[int] = mapped_column(Integer, nullable=False, server_default="0")
  last_run:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  is_processing:MappedColumn[int] = mapped_column(Integer, nullable=False, server_default="0")

# These are servers that the bot has been refused to be activated in
class DeniedServers(Base):
  __tablename__:str = "denied_servers"

  discord_server_id:MappedColumn[str] = mapped_column(String(32), unique=True, primary_key=True, nullable=False)
  adjudicar_handle:MappedColumn[str] = mapped_column(String(32), nullable=False)
  created_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now())
  updated_at:MappedColumn[datetime] = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())