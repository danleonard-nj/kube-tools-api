from datetime import datetime, time
from enum import Enum
from typing import Optional

import pytz

ET = pytz.timezone('America/New_York')

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)
PRE_MARKET_OPEN = time(4, 0)
AFTER_MARKET_CLOSE = time(20, 0)


class MarketSession(str, Enum):
    PRE = 'PRE'
    REGULAR = 'REGULAR'
    AFTER = 'AFTER'
    CLOSED = 'CLOSED'


class AlertType(str, Enum):
    SELL = 'SELL'
    FLOOR = 'FLOOR'
    SWING_UP = 'SWING_UP'
    SWING_DOWN = 'SWING_DOWN'


def get_market_session(now_et: datetime) -> MarketSession:
    """Determine market session from an ET-aware datetime."""
    weekday = now_et.weekday()
    if weekday >= 5:
        return MarketSession.CLOSED

    t = now_et.time()
    if MARKET_OPEN <= t < MARKET_CLOSE:
        return MarketSession.REGULAR
    elif PRE_MARKET_OPEN <= t < MARKET_OPEN:
        return MarketSession.PRE
    elif MARKET_CLOSE <= t < AFTER_MARKET_CLOSE:
        return MarketSession.AFTER
    else:
        return MarketSession.CLOSED
