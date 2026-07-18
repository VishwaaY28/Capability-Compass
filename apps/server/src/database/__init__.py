from tortoise import Tortoise
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# SQLite file lives next to the server src package
_DB_PATH = Path(__file__).resolve().parent.parent / "db.sqlite3"
DB_URL = f"sqlite://{_DB_PATH.as_posix()}"


async def init_db():
    await Tortoise.init(
        db_url=DB_URL,
        modules={"models": ["database.models"]},
        _create_db=True,
    )
    await Tortoise.generate_schemas()
    logger.info(f"✓ SQLite (Tortoise) initialized at {_DB_PATH}")


async def close_db():
    await Tortoise.close_connections()
    logger.info("✓ SQLite (Tortoise) connections closed")
