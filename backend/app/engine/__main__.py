"""python -m app.engine — run the signal engine."""

import asyncio
import logging

from .. import db, log
from ..config import get_settings
from .factory import build_engine


def main() -> None:
    settings = get_settings()
    log.setup(settings.log_level)
    db.configure(settings.database_url)
    engine = build_engine(settings)
    logging.getLogger(__name__).info("starting engine: source=%s symbols=%s", settings.market_data_source,
                                     ",".join(settings.symbols))
    asyncio.run(engine.run())


if __name__ == "__main__":
    main()
