from dataclasses import dataclass, field
import os

@dataclass
class IBKRConfig:
    host: str = os.getenv("IBKR_HOST", "127.0.0.1")
    paper_port: int = 7497
    live_port: int = 7496
    client_id: int = 1
    use_paper: bool = os.getenv("IBKR_PAPER", "true").lower() == "true"
    timeout: int = 10

    @property
    def port(self) -> int:
        return self.paper_port if self.use_paper else self.live_port


@dataclass
class RiskConfig:
    max_order_value: float = float(os.getenv("RISK_MAX_ORDER", "5000"))    # USD per trade
    max_daily_loss: float = float(os.getenv("RISK_MAX_LOSS", "500"))       # USD
    max_daily_gain: float = float(os.getenv("RISK_MAX_GAIN", "2000"))      # USD
    require_sl: bool = os.getenv("RISK_REQUIRE_SL", "true").lower() == "true"
    require_tp: bool = False


@dataclass
class Config:
    ibkr: IBKRConfig = field(default_factory=IBKRConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    log_dir: str = "logs/ibkr"
    log_max_bytes: int = 10 * 1024 * 1024
    log_backup_count: int = 7
    heartbeat_interval: int = 30


config = Config()
