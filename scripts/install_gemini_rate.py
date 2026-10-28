"""Insert one reviewed immutable rate using the existing migration role; no schema changes."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from app.gemini_provider import CARD,MODEL_ID
from app.models import RateVersion
from app.providers import rate_id


def install() -> None:
    engine=create_engine(os.environ.get('MIGRATION_DATABASE_URL') or os.environ['DATABASE_URL'],hide_parameters=True)
    with Session(engine) as s:
        old=s.get(RateVersion,rate_id(CARD))
        if old:
            if old.snapshot!=CARD:raise RuntimeError('GEMINI_RATE_SNAPSHOT_MISMATCH')
        else:
            s.add(RateVersion(id=rate_id(CARD),provider='google',model=MODEL_ID,effective_date=CARD['price_effective_date'],source_url=CARD['pricing_source_url'],snapshot=dict(CARD)))
            s.commit()
    engine.dispose()


if __name__=='__main__':
    install();print('GEMINI_RATE_INSTALLED_NO_SCHEMA_CHANGE')
