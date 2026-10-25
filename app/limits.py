"""PostgreSQL/SQLite atomic shared fixed-window limits; no process-local counters."""
import hashlib
import time
from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session
from .models import RateLimit


def consume(session: Session, identity: str, limit: int, seconds: int = 60) -> bool:
    current = int(time.time())
    # A minute bucket is not used: window_end gives a full interval after first attempt.
    key = hashlib.sha256(identity.encode()).hexdigest()
    session.execute(delete(RateLimit).where(RateLimit.window_end < current - 86400))
    insert = pg_insert if session.bind is not None and session.bind.dialect.name == 'postgresql' else sqlite_insert
    expired = RateLimit.window_end <= current
    statement = insert(RateLimit).values(key=key, count=1, window_end=current + seconds)
    upsert = statement.on_conflict_do_update(index_elements=['key'], set_={
        'count': case((expired, 1), else_=RateLimit.count + 1),
        'window_end': case((expired, current + seconds), else_=RateLimit.window_end),
    }, where=expired | (RateLimit.count < limit)).returning(RateLimit.count)
    accepted = session.execute(upsert).scalar_one_or_none() is not None
    session.commit()
    return accepted
