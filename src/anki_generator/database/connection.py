"""SQLite connections and Alembic upgrades for both GUI and worker sessions."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def open_database(data_root: Path, *, migrate: bool = True) -> sessionmaker:
    data_root.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{data_root / 'application.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection: object, record: object) -> None:
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    if migrate:
        config = migration_config()
        with engine.begin() as connection:
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
    return sessionmaker(engine, expire_on_commit=False)


def migration_config() -> Config:
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).parent / "migrations"))
    config.set_main_option("sqlalchemy.url", "sqlite://")
    return config
