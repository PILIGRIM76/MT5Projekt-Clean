import logging
import random
from datetime import datetime
from typing import Dict, List, Optional
from dataclasses import dataclass

# Импортируем интерфейс, чтобы наследовать его
from src.core.interfaces import ITerminalConnector
import MetaTrader5 as mt5  # Нужен для кодов возврата

logger = logging.getLogger(__name__)


@dataclass
class SimPosition:
    ticket: int
    symbol: str
    type: int  # 0 = BUY, 1 = SELL
    volume: float
    price_open: float
    sl: float
    tp: float
    time_open: datetime
    swap: float = 0.0
    commission: float = 0.0
    profit: float = 0.0

    @property
    def price_current(self): return 0.0


class SimulatedBroker(ITerminalConnector):
    def __init__(self, initial_balance: float = 10000.0, spread_pips: int = 2):
        self.balance = initial_balance
        self.equity = initial_balance
        self.positions: Dict[int, SimPosition] = {}
        self.history_deals: List[dict] = []
        self.current_time: datetime = datetime(2020, 1, 1)
        self.current_prices: Dict[str, dict] = {}
        self.spread_pips = spread_pips
        self.ticket_counter = 1000
        self.point = 0.00001

        # --- Настройки реализма ---
        self.commission_per_lot = 7.0  # $7 за лот (round turn)
        self.swap_per_lot_per_day = -1.0  # Отрицательный своп
        self.slippage_std_dev_pips = 0.5  # Проскальзывание

    def update_market_data(self, symbol: str, time: datetime, close_price: float):
        """Обновляет 'рынок' для симулятора."""
        if self.current_time.date() < time.date():
            self._apply_swaps()

        self.current_time = time
        spread_val = self.spread_pips * self.point

        self.current_prices[symbol] = {
            'bid': close_price - (spread_val / 2),
            'ask': close_price + (spread_val / 2),
            'time': time
        }
        self._check_stops(symbol)
        self._update_equity()

    def _apply_swaps(self):
        for ticket, pos in self.positions.items():
            pos.swap += self.swap_per_lot_per_day * pos.volume

    def _calculate_slippage(self) -> float:
        pips = random.gauss(0, self.slippage_std_dev_pips)
        return abs(pips) * self.point

    def _check_stops(self, symbol: str):
        prices = self.current_prices.get(symbol)
        if not prices: return

        for ticket in list(self.positions.keys()):
            pos = self.positions[ticket]
            if pos.symbol != symbol: continue

            close_price = None
            comment = ""
            slippage = self._calculate_slippage()

            if pos.type == 0:  # BUY
                if prices['bid'] <= pos.sl and pos.sl > 0:
                    close_price = pos.sl - abs(slippage)
                    comment = "sl"
                elif prices['bid'] >= pos.tp and pos.tp > 0:
                    close_price = pos.tp + slippage
                    comment = "tp"
            else:  # SELL
                if prices['ask'] >= pos.sl and pos.sl > 0:
                    close_price = pos.sl + abs(slippage)
                    comment = "sl"
                elif prices['ask'] <= pos.tp and pos.tp > 0:
                    close_price = pos.tp - slippage
                    comment = "tp"

            if close_price:
                self._close_position(ticket, close_price, comment)

    def _close_position(self, ticket: int, price: float, comment: str):
        if ticket not in self.positions: return
        pos = self.positions.pop(ticket)

        if pos.type == 0:  # BUY
            gross_profit = (price - pos.price_open) * pos.volume * 100000
        else:  # SELL
            gross_profit = (pos.price_open - price) * pos.volume * 100000

        net_profit = gross_profit + pos.swap - pos.commission

        self.balance += net_profit
        self.equity = self.balance

        deal = {
            'ticket': ticket,
            'position_id': ticket,
            'symbol': pos.symbol,
            'type': pos.type,
            'volume': pos.volume,
            'price': price,
            'profit': net_profit,
            'commission': pos.commission,
            'swap': pos.swap,
            'time': self.current_time.timestamp(),
            'comment': comment,
            'entry': 1
        }
        self.history_deals.append(deal)

    def _update_equity(self):
        floating_pl = 0.0
        for pos in self.positions.values():
            prices = self.current_prices.get(pos.symbol)
            if not prices: continue
            current_price = prices['bid'] if pos.type == 0 else prices['ask']
            if pos.type == 0:
                gross = (current_price - pos.price_open) * pos.volume * 100000
            else:
                gross = (pos.price_open - current_price) * pos.volume * 100000
            pos.profit = gross + pos.swap - pos.commission
            floating_pl += pos.profit
        self.equity = self.balance + floating_pl

    # --- Реализация интерфейса ITerminalConnector ---

    def initialize(self, path: str = None, login: int = None, password: str = None, server: str = None) -> bool:
        return True

    def shutdown(self):
        pass

    def get_account_info(self):
        class AccountInfoStub:
            def __init__(self, balance, equity):
                self.balance = balance
                self.equity = equity
                self.currency = "USD"

        return AccountInfoStub(self.balance, self.equity)

    def get_positions(self, symbol: str = None, ticket: int = None):
        if ticket: return [self.positions[ticket]] if ticket in self.positions else []
        if symbol: return [p for p in self.positions.values() if p.symbol == symbol]
        return list(self.positions.values())

    def get_history_deals(self, date_from: datetime = None, date_to: datetime = None, ticket: int = None):
        class DealStub:
            def __init__(self, data):
                for k, v in data.items(): setattr(self, k, v)

        if ticket:
            return [DealStub(d) for d in self.history_deals if d['ticket'] == ticket]

        ts_from = date_from.timestamp() if date_from else 0
        ts_to = date_to.timestamp() if date_to else 9999999999
        return [DealStub(d) for d in self.history_deals if ts_from <= d['time'] <= ts_to]

    # --- НОВЫЕ МЕТОДЫ (Исправление ошибки Abstract Class) ---
    def get_orders(self, ticket: int = None, symbol: str = None):
        """Возвращает активные ордера (в симуляторе их нет, т.к. исполнение мгновенное)."""
        return []

    def get_history_orders(self, ticket: int = None, position: int = None):
        """Возвращает историю ордеров (заглушка)."""
        return []

    # --------------------------------------------------------

    def symbol_info(self, symbol: str):
        class SymbolInfoStub:
            def __init__(self, name):
                self.name = name
                self.currency_profit = "USD"
                self.trade_tick_value = 1.0
                self.trade_tick_size = 0.00001
                self.volume_step = 0.01
                self.volume_min = 0.01
                self.volume_max = 100.0
                self.digits = 5
                self.point = 0.00001

        return SymbolInfoStub(symbol)

    def symbol_info_tick(self, symbol: str):
        prices = self.current_prices.get(symbol)
        if not prices: return None

        class TickStub:
            def __init__(self, bid, ask, time):
                self.bid = bid
                self.ask = ask
                self.time = int(time.timestamp())

        return TickStub(prices['bid'], prices['ask'], prices['time'])

    def order_check(self, request: dict):
        return type('Res', (), {'retcode': 0, 'comment': 'Done'})()

    def order_send(self, request: dict):
        self.ticket_counter += 1

        # Если это отложенный ордер (Limit), мы его отклоняем в симуляторе,
        # чтобы TradeExecutor сразу перешел к рыночному исполнению.
        if request['action'] == mt5.TRADE_ACTION_PENDING:
            return type('Res', (), {'retcode': 10013, 'comment': 'Simulator: Pending orders not supported'})()

        if request['action'] == mt5.TRADE_ACTION_DEAL:
            symbol = request['symbol']
            prices = self.current_prices.get(symbol)
            if not prices:
                return type('Res', (), {'retcode': 10004, 'comment': 'No price'})()

            slippage = self._calculate_slippage()
            base_price = prices['ask'] if request['type'] == 0 else prices['bid']
            exec_price = base_price + slippage
            commission = self.commission_per_lot * request['volume']

            new_pos = SimPosition(
                ticket=self.ticket_counter,
                symbol=symbol,
                type=request['type'],
                volume=request['volume'],
                price_open=exec_price,
                sl=request['sl'],
                tp=request['tp'],
                time_open=self.current_time,
                commission=commission
            )
            self.positions[self.ticket_counter] = new_pos

            deal_in = {
                'ticket': self.ticket_counter,
                'position_id': self.ticket_counter,
                'symbol': symbol,
                'type': request['type'],
                'volume': request['volume'],
                'price': exec_price,
                'profit': 0.0,
                'time': self.current_time.timestamp(),
                'comment': request.get('comment', ''),
                'entry': 0
            }
            self.history_deals.append(deal_in)

            class OrderResult:
                retcode = 10009
                deal = self.ticket_counter
                order = self.ticket_counter
                comment = "Executed by Simulator"

            return OrderResult()

        elif request['action'] == mt5.TRADE_ACTION_DEAL and 'position' in request:
            # Закрытие позиции
            pos_ticket = request['position']
            if pos_ticket in self.positions:
                prices = self.current_prices.get(request['symbol'])
                slippage = self._calculate_slippage()
                base_price = prices['bid'] if self.positions[pos_ticket].type == 0 else prices['ask']
                close_price = base_price + slippage

                self._close_position(pos_ticket, close_price, "closed by script")

                class OrderResult:
                    retcode = 10009
                    deal = self.ticket_counter
                    comment = "Closed by Simulator"

                return OrderResult()

        return type('Res', (), {'retcode': 10013, 'comment': 'Invalid request'})()