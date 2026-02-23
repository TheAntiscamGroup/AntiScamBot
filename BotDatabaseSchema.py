from sqlalchemy import Integer, DateTime, String
from sqlalchemy.sql import func, null
from sqlalchemy.orm import DeclarativeBase, mapped_column

class Base(DeclarativeBase):
  pass

class Migration(Base):
  __tablename__ = "migrations"

  id = mapped_column(Integer, primary_key=True, autoincrement=True)
  database_version = mapped_column(Integer, nullable=False)
  created_at = mapped_column(DateTime(), server_default=func.now())
  updated_at = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())

class Ban(Base):
  __tablename__ = "bans"

  id = mapped_column(Integer, primary_key=True, autoincrement=True)
  discord_user_id = mapped_column(String(32), unique=True, nullable=False)
  assigner_discord_user_id = mapped_column(String(32), nullable=False)
  assigner_discord_user_name = mapped_column(String(32), nullable=False)
  created_at = mapped_column(DateTime(), server_default=func.now())
  updated_at = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  evidence_thread = mapped_column(Integer, nullable=True, server_default=null())

class Server(Base):
  __tablename__ = "servers"

  id = mapped_column(Integer, primary_key=True, autoincrement=True)
  bot_instance_id = mapped_column(Integer, nullable=False, server_default="0")
  discord_server_id = mapped_column(String(32), unique=True, nullable=False)
  owner_discord_user_id = mapped_column(String(32), nullable=False)
  activation_state = mapped_column(Integer, server_default="0")
  activator_discord_user_id = mapped_column(String(32), nullable=False, server_default='-1')
  created_at = mapped_column(DateTime(), server_default=func.now())
  updated_at = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  message_channel = mapped_column(Integer, server_default="0")
  has_webhooks = mapped_column(Integer, server_default="0")
  kick_sus_users = mapped_column(Integer, server_default="0")
  can_report = mapped_column(Integer, server_default="1")
  should_ban_in = mapped_column(Integer, server_default="1")

class ExhaustedServer(Base):
  __tablename__ = "exhausted_servers"

  discord_server_id = mapped_column(String(32), primary_key=True, unique=True, nullable=False)
  current_pos = mapped_column(Integer, nullable=False, server_default="0")
  last_run = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())
  is_processing = mapped_column(Integer, nullable=False, server_default="0")

# These are servers that the bot has been refused to be activated in
class DeniedServers(Base):
  __tablename__ = "denied_servers"

  discord_server_id = mapped_column(String(32), unique=True, primary_key=True, nullable=False)
  adjudicar_handle = mapped_column(String(32), nullable=False)
  created_at = mapped_column(DateTime(), server_default=func.now())
  updated_at = mapped_column(DateTime(), server_default=func.now(), onupdate=func.now())