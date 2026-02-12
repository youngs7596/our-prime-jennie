# tests/e2e/mock_server/scenarios.py
"""
Test Scenario Management for E2E Tests

Provides predefined test scenarios and dynamic scenario configuration
for simulating various market conditions and system states.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any


class ResponseMode(Enum):
    """Response behavior modes for mock server"""
    NORMAL = "normal"
    ERROR_500 = "error_500"
    ERROR_400 = "error_400"
    TIMEOUT = "timeout"
    PARTIAL_FAILURE = "partial_failure"


@dataclass
class StockState:
    """State for a single stock in the mock server"""
    code: str
    name: str
    price: float
    open_price: float
    high_price: float
    low_price: float
    volume: int = 100000
    change_pct: float = 0.0

    def to_snapshot(self) -> dict:
        return {
            'price': self.price,
            'open': self.open_price,
            'high': self.high_price,
            'low': self.low_price,
            'volume': self.volume,
            'change_pct': self.change_pct
        }


@dataclass
class PortfolioItem:
    """A single item in the mock portfolio"""
    code: str
    name: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    sector: str = ""

    def to_dict(self) -> dict:
        return {
            'code': self.code,
            'name': self.name,
            'quantity': self.quantity,
            'avg_price': self.avg_price,
            'current_price': self.current_price or self.avg_price
        }


@dataclass
class Scenario:
    """Test scenario configuration"""
    name: str
    description: str = ""

    # Account state
    cash_balance: float = 10_000_000
    portfolio: List[PortfolioItem] = field(default_factory=list)

    # Stock prices
    stocks: Dict[str, StockState] = field(default_factory=dict)

    # Market state
    market_open: bool = True
    market_regime: str = "BULL"

    # Response behavior
    response_mode: ResponseMode = ResponseMode.NORMAL
    response_delay_ms: int = 0

    # Order behavior
    order_counter: int = 0
    order_success_rate: float = 1.0  # 1.0 = 100% success

    # Trading limits
    max_buy_count_per_day: int = 5
    today_buy_count: int = 0

    # Emergency flags
    emergency_stop: bool = False
    trading_paused: bool = False

    # Per-stock snapshot errors: stock_code → {"status": int, "message": str}
    snapshot_errors: Dict[str, Dict] = field(default_factory=dict)

    # Cancel order results: order_no → True(미체결/취소 성공) | False(이미 체결)
    cancel_results: Dict[str, bool] = field(default_factory=dict)

    # Tick size validation mode
    validate_tick_size: bool = False

    def get_stock(self, code: str) -> Optional[StockState]:
        """Get stock state by code"""
        return self.stocks.get(code)

    def set_stock_price(self, code: str, price: float):
        """Update stock price"""
        if code in self.stocks:
            stock = self.stocks[code]
            stock.price = price
            stock.high_price = max(stock.high_price, price)
            stock.low_price = min(stock.low_price, price)

    def add_stock(self, code: str, name: str, price: float):
        """Add a stock to the scenario"""
        self.stocks[code] = StockState(
            code=code,
            name=name,
            price=price,
            open_price=price,
            high_price=price,
            low_price=price
        )

    def get_next_order_no(self, prefix: str = "ORD") -> str:
        """Generate next order number"""
        self.order_counter += 1
        return f"{prefix}_{self.order_counter:05d}"

    def add_to_portfolio(self, code: str, name: str, quantity: int, price: float):
        """Add position to portfolio"""
        # Check if already exists
        for item in self.portfolio:
            if item.code == code:
                # Average up/down
                total_qty = item.quantity + quantity
                item.avg_price = ((item.avg_price * item.quantity) + (price * quantity)) / total_qty
                item.quantity = total_qty
                return

        self.portfolio.append(PortfolioItem(
            code=code,
            name=name,
            quantity=quantity,
            avg_price=price
        ))

    def remove_from_portfolio(self, code: str, quantity: int) -> bool:
        """Remove position from portfolio"""
        for i, item in enumerate(self.portfolio):
            if item.code == code:
                if item.quantity <= quantity:
                    self.portfolio.pop(i)
                else:
                    item.quantity -= quantity
                return True
        return False

    def get_portfolio_item(self, code: str) -> Optional[PortfolioItem]:
        """Get portfolio item by code"""
        for item in self.portfolio:
            if item.code == code:
                return item
        return None

    def reset(self):
        """Reset to initial state"""
        self.order_counter = 0
        self.today_buy_count = 0
        self.portfolio.clear()
        self.snapshot_errors.clear()
        self.cancel_results.clear()


class ScenarioManager:
    """
    Manages test scenarios and provides preset scenarios
    """

    def __init__(self):
        self._scenarios: Dict[str, Scenario] = {}
        self._current_scenario: Optional[Scenario] = None
        self._register_default_scenarios()

    def _register_default_scenarios(self):
        """Register built-in test scenarios"""

        # Empty portfolio - basic buy test
        self.register(Scenario(
            name="empty_portfolio",
            description="Empty portfolio for testing buy flows",
            cash_balance=10_000_000,
            portfolio=[],
            stocks={
                "005930": StockState("005930", "삼성전자", 70000, 69000, 71000, 69000),
                "000660": StockState("000660", "SK하이닉스", 150000, 148000, 152000, 147000),
                "035720": StockState("035720", "카카오", 50000, 49000, 51000, 48000),
            },
            market_open=True,
            market_regime="BULL"
        ))

        # With holdings - for sell tests
        self.register(Scenario(
            name="with_holdings",
            description="Portfolio with existing holdings for sell tests",
            cash_balance=5_000_000,
            portfolio=[
                PortfolioItem("005930", "삼성전자", 10, 70000, 72000),
                PortfolioItem("000660", "SK하이닉스", 5, 150000, 145000),
            ],
            stocks={
                "005930": StockState("005930", "삼성전자", 72000, 69000, 73000, 69000),
                "000660": StockState("000660", "SK하이닉스", 145000, 148000, 152000, 143000),
            },
            market_open=True,
            market_regime="BULL"
        ))

        # Stop loss scenario
        self.register(Scenario(
            name="stop_loss_scenario",
            description="Price dropped below stop loss threshold",
            cash_balance=5_000_000,
            portfolio=[
                PortfolioItem("005930", "삼성전자", 10, 70000, 63000),  # -10%
            ],
            stocks={
                "005930": StockState("005930", "삼성전자", 63000, 70000, 70500, 62000, change_pct=-10.0),
            },
            market_open=True,
            market_regime="BEAR"
        ))

        # Take profit scenario
        self.register(Scenario(
            name="take_profit_scenario",
            description="Price reached take profit threshold",
            cash_balance=5_000_000,
            portfolio=[
                PortfolioItem("005930", "삼성전자", 10, 70000, 84000),  # +20%
            ],
            stocks={
                "005930": StockState("005930", "삼성전자", 84000, 70000, 85000, 69000, change_pct=20.0),
            },
            market_open=True,
            market_regime="STRONG_BULL"
        ))

        # Market closed
        self.register(Scenario(
            name="market_closed",
            description="Market is closed",
            cash_balance=10_000_000,
            market_open=False
        ))

        # Daily limit reached
        self.register(Scenario(
            name="daily_limit_reached",
            description="Daily buy limit reached",
            cash_balance=10_000_000,
            max_buy_count_per_day=5,
            today_buy_count=5,
            stocks={
                "005930": StockState("005930", "삼성전자", 70000, 69000, 71000, 69000),
            }
        ))

        # Emergency stop
        self.register(Scenario(
            name="emergency_stop",
            description="Emergency stop is active",
            cash_balance=10_000_000,
            emergency_stop=True
        ))

        # Server error simulation
        self.register(Scenario(
            name="server_error",
            description="Server returns 500 errors",
            response_mode=ResponseMode.ERROR_500
        ))

        # Timeout simulation
        self.register(Scenario(
            name="timeout",
            description="Server responses timeout",
            response_mode=ResponseMode.TIMEOUT,
            response_delay_ms=5000
        ))

        # Low cash balance
        self.register(Scenario(
            name="low_cash",
            description="Insufficient cash for trading",
            cash_balance=50000,  # Only 50K
            stocks={
                "005930": StockState("005930", "삼성전자", 70000, 69000, 71000, 69000),
            }
        ))

        # Full portfolio
        self.register(Scenario(
            name="full_portfolio",
            description="Portfolio at maximum size",
            cash_balance=1_000_000,
            portfolio=[
                PortfolioItem(f"00{i:04d}", f"Stock{i}", 10, 10000)
                for i in range(10)  # 10 holdings
            ]
        ))

        # Bull market with momentum
        self.register(Scenario(
            name="bull_momentum",
            description="Strong bull market with momentum signals",
            cash_balance=10_000_000,
            stocks={
                "005930": StockState("005930", "삼성전자", 75000, 70000, 76000, 69500, volume=2000000, change_pct=7.0),
                "000660": StockState("000660", "SK하이닉스", 160000, 150000, 162000, 149000, volume=1500000, change_pct=6.5),
            },
            market_regime="STRONG_BULL"
        ))

        # Momentum limit order — various price tiers for tick size testing
        self.register(Scenario(
            name="momentum_limit_order",
            description="Momentum limit order with diverse price tiers",
            cash_balance=20_000_000,
            stocks={
                "383220": StockState("383220", "F&F", 384200, 380000, 386000, 379000, volume=500000, change_pct=1.1),
                "068270": StockState("068270", "셀트리온", 298000, 295000, 300000, 294000, volume=800000, change_pct=1.0),
                "006400": StockState("006400", "삼성SDI", 550000, 545000, 555000, 540000, volume=300000, change_pct=0.9),
                "004990": StockState("004990", "롯데지주", 34300, 33800, 34800, 33500, volume=200000, change_pct=1.5),
                "001740": StockState("001740", "SK네트웍스", 4800, 4750, 4900, 4700, volume=400000, change_pct=1.0),
            },
            market_regime="BULL",
            validate_tick_size=True,
        ))

        # Sector concentrated portfolio — 금융 3종목 보유
        self.register(Scenario(
            name="sector_concentrated",
            description="Portfolio concentrated in financial sector (3 stocks)",
            cash_balance=5_000_000,
            portfolio=[
                PortfolioItem("105560", "KB금융", 20, 70000, 72000, sector="금융"),
                PortfolioItem("055550", "신한지주", 30, 45000, 46000, sector="금융"),
                PortfolioItem("086790", "하나금융지주", 25, 52000, 53000, sector="금융"),
            ],
            stocks={
                "105560": StockState("105560", "KB금융", 72000, 70000, 73000, 69000),
                "055550": StockState("055550", "신한지주", 46000, 44000, 47000, 44000),
                "086790": StockState("086790", "하나금융지주", 53000, 51000, 54000, 51000),
                "316140": StockState("316140", "우리금융지주", 15000, 14500, 15500, 14000),
                "005930": StockState("005930", "삼성전자", 72000, 70000, 73000, 69000),
            },
            market_regime="BULL",
        ))

    def register(self, scenario: Scenario):
        """Register a scenario"""
        self._scenarios[scenario.name] = scenario

    def get(self, name: str) -> Optional[Scenario]:
        """Get a scenario by name"""
        return self._scenarios.get(name)

    def activate(self, name: str) -> Scenario:
        """Activate a scenario by name"""
        scenario = self.get(name)
        if not scenario:
            raise ValueError(f"Scenario not found: {name}")
        self._current_scenario = scenario
        return scenario

    @property
    def current(self) -> Optional[Scenario]:
        """Get currently active scenario"""
        return self._current_scenario

    def create_custom(self, name: str, **kwargs) -> Scenario:
        """Create a custom scenario"""
        scenario = Scenario(name=name, **kwargs)
        self.register(scenario)
        return scenario

    def list_scenarios(self) -> List[str]:
        """List all registered scenario names"""
        return list(self._scenarios.keys())

    def reset_current(self):
        """Reset current scenario to initial state"""
        if self._current_scenario:
            self._current_scenario.reset()
