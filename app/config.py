"""Central configuration — everything overridable via environment variables."""
import os
from dataclasses import dataclass, field


def _f(name: str, default: float) -> float:
    return float(os.getenv(name, default))


def _i(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _b(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(s.strip() for s in os.getenv(name, default).split(",") if s.strip())


def _impact_csv(name: str, default: str) -> tuple[str, ...]:
    return tuple(s.lower() for s in _csv(name, default))


@dataclass
class SessionWindow:
    """A tradeable session: pre-open range window + post-open entry window (UTC)."""
    name: str
    open_hour_utc: int        # session open, UTC
    range_hours: int          # hours BEFORE open used to build the breakout range
    entry_hours: int          # hours AFTER open during which breakouts may be taken


@dataclass
class Settings:
    # --- OANDA -----------------------------------------------------------
    oanda_env: str = os.getenv("OANDA_ENV", "practice")           # practice | live
    oanda_token: str = os.getenv("OANDA_API_TOKEN", "")
    oanda_account_id: str = os.getenv("OANDA_ACCOUNT_ID", "")

    # --- Universe --------------------------------------------------------
    instruments: tuple = field(default_factory=lambda: _csv(
        "INSTRUMENTS", "EUR_USD,GBP_USD,USD_JPY,AUD_USD,USD_CAD"
    ))
    granularity: str = os.getenv("GRANULARITY", "M15")
    candle_count: int = _i("CANDLE_COUNT", 400)

    # --- Sessions (UTC; adjust for DST if you care about exact opens) -----
    # LONNY = the London/New York overlap (~13:00-16:00 UTC), the deepest
    # liquidity window of the day. Its pre-open range is the London morning.
    # Note: sessions are matched in order and only one is active at a time,
    # so if NEWYORK and LONNY are both enabled, NEWYORK wins 13:00-16:00.
    # Typical pairings: "LONDON,LONNY" or "LONDON,NEWYORK".
    sessions: tuple = (
        SessionWindow("LONDON", _i("LONDON_OPEN_UTC", 7), _i("LONDON_RANGE_H", 5), _i("LONDON_ENTRY_H", 4)),
        SessionWindow("NEWYORK", _i("NY_OPEN_UTC", 12), _i("NY_RANGE_H", 4), _i("NY_ENTRY_H", 4)),
        SessionWindow("LONNY", _i("OVERLAP_OPEN_UTC", 13), _i("OVERLAP_RANGE_H", 4), _i("OVERLAP_ENTRY_H", 3)),
    )
    enabled_sessions: tuple = field(default_factory=lambda: _csv("ENABLED_SESSIONS", "LONDON,NEWYORK"))
    disabled_weekdays: tuple = field(default_factory=lambda: _csv("DISABLED_WEEKDAYS", ""))
    disabled_utc_hours: tuple = field(default_factory=lambda: tuple(
        int(h) for h in _csv("DISABLED_UTC_HOURS", "") if h.isdigit()
    ))

    # --- Confluence approval layer ----------------------------------------
    ema_fast: int = _i("EMA_FAST", 50)
    ema_slow: int = _i("EMA_SLOW", 200)
    rsi_period: int = _i("RSI_PERIOD", 14)
    rsi_long_min: float = _f("RSI_LONG_MIN", 55.0)
    rsi_short_max: float = _f("RSI_SHORT_MAX", 45.0)
    atr_period: int = _i("ATR_PERIOD", 14)
    # Range height must sit between these ATR multiples (too tight = noise,
    # too wide = move already exhausted).
    range_atr_min: float = _f("RANGE_ATR_MIN", 0.8)
    range_atr_max: float = _f("RANGE_ATR_MAX", 4.0)
    # Breakout close must not be further than this many ATRs beyond the range
    # edge — protects against chasing an extended candle.
    max_extension_atr: float = _f("MAX_EXTENSION_ATR", 1.0)
    max_spread_atr: float = _f("MAX_SPREAD_ATR", 0.15)   # spread <= 15% of ATR

    # --- Trade construction ------------------------------------------------
    sl_atr_mult: float = _f("SL_ATR_MULT", 1.5)
    tp_r_mult: float = _f("TP_R_MULT", 2.0)              # take-profit at 2R

    # --- Risk management ---------------------------------------------------
    risk_per_trade_pct: float = _f("RISK_PER_TRADE_PCT", 0.5)   # % of NAV
    max_open_trades: int = _i("MAX_OPEN_TRADES", 2)
    max_daily_loss_pct: float = _f("MAX_DAILY_LOSS_PCT", 3.0)   # halt for the day
    max_units: int = _i("MAX_UNITS", 100_000)                   # hard cap per order
    one_trade_per_session: bool = _b("ONE_TRADE_PER_SESSION", True)

    # --- Engine -------------------------------------------------------------
    poll_seconds: int = _i("POLL_SECONDS", 60)
    trading_enabled: bool = _b("TRADING_ENABLED", True)
    data_dir: str = os.getenv("DATA_DIR", "./data")

    # --- News / macro-event filter ----------------------------------------
    news_filter_enabled: bool = _b("NEWS_FILTER_ENABLED", False)
    news_provider: str = os.getenv("NEWS_PROVIDER", "finnhub").strip().lower()
    news_api_key: str = os.getenv("NEWS_API_KEY", os.getenv("FINNHUB_API_KEY", ""))
    news_calendar_url: str = os.getenv("NEWS_CALENDAR_URL", "")
    news_block_before_min: int = _i("NEWS_BLOCK_BEFORE_MIN", 60)
    news_block_after_min: int = _i("NEWS_BLOCK_AFTER_MIN", 30)
    news_min_impacts: tuple = field(default_factory=lambda: _impact_csv("NEWS_MIN_IMPACTS", "high"))
    news_fail_closed: bool = _b("NEWS_FAIL_CLOSED", True)
    news_cache_seconds: int = _i("NEWS_CACHE_SECONDS", 900)

    @property
    def api_base(self) -> str:
        return ("https://api-fxtrade.oanda.com" if self.oanda_env == "live"
                else "https://api-fxpractice.oanda.com")

    def validate(self) -> list[str]:
        problems = []
        if not self.oanda_token:
            problems.append("OANDA_API_TOKEN is not set")
        if not self.oanda_account_id:
            problems.append("OANDA_ACCOUNT_ID is not set")
        if self.oanda_env not in ("practice", "live"):
            problems.append(f"OANDA_ENV must be practice|live, got {self.oanda_env}")
        return problems


settings = Settings()
