from dataclasses import dataclass
from pathlib import Path

OKX_BASE_URL = "https://www.okx.com"
PAIR_START_MS = 1_783_699_800_000  # 2026-07-10 16:10:00 UTC
ADR_RATIO = 10.0
DEFAULT_Z_WINDOW = 288
DATABASE_PATH = Path("data/hynix_basis.sqlite3")


@dataclass(frozen=True)
class Instrument:
    key: str
    label: str
    inst_id: str
    index_id: str | None = None
    proxy_note: str | None = None


@dataclass(frozen=True)
class ExternalIndex:
    key: str
    label: str
    symbol: str


KOREAN = Instrument(
    key="korean",
    label="SK hynix ordinary",
    inst_id="SKHYNIX-USDT-SWAP",
    index_id="SKHYNIX-USDT",
)
ADR = Instrument(
    key="adr",
    label="SKHY ADR",
    inst_id="SKHY-USDT-SWAP",
    index_id="SKHY-USDT",
)

PAIR_INSTRUMENTS = (KOREAN, ADR)

CONTEXT_INSTRUMENTS = (
    Instrument(key="spy", label="SPY", inst_id="SPY-USDT-SWAP"),
    Instrument(key="qqq", label="QQQ", inst_id="QQQ-USDT-SWAP"),
)

KOREA_INDEXES = (
    ExternalIndex(key="kospi", label="KOSPI", symbol="^KS11"),
    ExternalIndex(key="kosdaq", label="KOSDAQ", symbol="^KQ11"),
)
