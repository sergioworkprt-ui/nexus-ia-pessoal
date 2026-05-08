from ibkr.strategies.base import BaseStrategy


class ExampleStrategy(BaseStrategy):
    """
    Example: prints AAPL price every 60s.
    Replace on_tick() with your own logic.
    """

    def __init__(self, nexus):
        super().__init__(nexus, name="example", interval=60)

    async def on_start(self):
        self.log.info("ExampleStrategy starting")

    async def on_tick(self):
        price = self.nexus.get_price("AAPL")
        pnl = self.nexus.get_pnl()
        self.log.info(f"AAPL={price:.2f} | daily_pnl={pnl['daily']:.2f}")

        # Example bracket order (commented out — paper test first)
        # trade = self.nexus.place_order(
        #     symbol="AAPL", action="BUY", qty=1,
        #     price=price, sl=price - 2, tp=price + 4,
        #     order_ref="example-001"
        # )

    async def on_stop(self):
        self.log.info("ExampleStrategy stopped")
