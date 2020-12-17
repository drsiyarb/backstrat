import abc
import requests
import logging
import dateutil.parser
from datetime import datetime, timedelta
from enum import Enum
import cProfile

import numpy
import pandas
import talib
import pymongo
import matplotlib.pyplot as plt

logging.basicConfig(level=logging.DEBUG)


class CandlestickGranularity(Enum):
    S5 = timedelta(seconds=5)
    S10 = timedelta(seconds=10)
    S15 = timedelta(seconds=15)
    S30 = timedelta(seconds=30)
    M1 = timedelta(minutes=1)
    M2 = timedelta(minutes=2)
    M4 = timedelta(minutes=4)
    M5 = timedelta(minutes=5)
    M10 = timedelta(minutes=10)
    M15 = timedelta(minutes=15)
    M30 = timedelta(minutes=30)
    H1 = timedelta(hours=1)
    H2 = timedelta(hours=2)
    H3 = timedelta(hours=3)
    H4 = timedelta(hours=4)
    H6 = timedelta(hours=6)
    H8 = timedelta(hours=8)
    H12 = timedelta(hours=12)
    D = timedelta(days=1)
    W = timedelta(days=7)
    M = timedelta(days=30)


class HistoryProvider(metaclass=abc.ABCMeta):
    @property
    @abc.abstractmethod
    def max_candles(self):
        pass

    @property
    @abc.abstractmethod
    def source_name(self):
        pass

    def fetch(self, instrument, granularity: CandlestickGranularity, start_time, end_time):
        delta = end_time - start_time
        maximum_fetchable_delta = granularity.value * self.max_candles

        if delta <= maximum_fetchable_delta:
            return self._execute_fetch_call(instrument, granularity, start_time, end_time)

        result = []
        advancing_start_time = start_time
        while advancing_start_time < end_time:
            result.extend(self._execute_fetch_call(instrument, granularity, advancing_start_time, advancing_start_time + maximum_fetchable_delta))
            advancing_start_time += maximum_fetchable_delta

        return result

    @abc.abstractmethod
    def _execute_fetch_call(self, instrument, granularity: CandlestickGranularity, start_time, end_time):
        pass


class OandaHistoryProvider(HistoryProvider):
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.token = token

    @property
    def max_candles(self):
        return 1440

    @property
    def source_name(self):
        return 'oanda'

    def _execute_fetch_call(self, instrument, granularity: CandlestickGranularity, start_time, end_time):
        headers = {'Authorization': 'Bearer ' + self.token}
        params = {'granularity': granularity.name, 'from': start_time.isoformat(), 'end': end_time.isoformat(), 'count': self.max_candles}
        url = self.base_url + '/v3/instruments/' + instrument + '/candles'

        logging.info('Making a call to ' + self.source_name)
        returned = requests.get(url, headers=headers, params=params).json()
        logging.info('Call returned ' + str(len(returned['candles'])) + ' candles')
        return [{'t': dateutil.parser.parse(item['time']),
                 'o': item['mid']['o'],
                 'h': item['mid']['h'],
                 'l': item['mid']['l'],
                 'c': item['mid']['c'],
                 'v': item['volume']}
                for item in returned['candles']]


class HistoryManager:
    def __init__(self, history_provider: HistoryProvider, mongo_url, db_name):
        self.history_provider = history_provider
        self.mongo_url = mongo_url
        self.db_name = db_name
        self.mongo = pymongo.MongoClient(mongo_url)
        self.db = self.mongo[db_name]

    def _get_collection_name(self, instrument, granularity: CandlestickGranularity):
        return self.history_provider.source_name + '-' + instrument + '-' + granularity.name

    def _get_meta_collection_name(self, instrument, granularity: CandlestickGranularity):
        return self._get_collection_name(instrument, granularity) + '-meta'

    def _daterange(self, start_date, end_date):
        for n in range(int((end_date - start_date).days)):
            yield start_date + timedelta(n)

    def _store(self, instrument, granularity, day, items):
        self.db[self._get_collection_name(instrument, granularity)].insert_many(items)
        self.db[self._get_meta_collection_name(instrument, granularity)].insert_one({'day': day})

    def _is_in_store(self, instrument, granularity, day):
        return True if self.db[self._get_meta_collection_name(instrument, granularity)].find({'day': day}).count() > 0 else False

    def _fetch_from_store(self, instrument, granularity: CandlestickGranularity, day):
        return self.db[self._get_collection_name(instrument, granularity)].find({'t': {'$gte': day, '$lt': day + timedelta(days=1)}})

    def _fetch_from_provider(self, instrument, granularity: CandlestickGranularity, day):
        fetched = self.history_provider.fetch(instrument, granularity, day, day + timedelta(days=1))
        self._store(instrument, granularity, day, fetched)
        return fetched

    def _filter_repeated_history(self, history):
        to_return = []
        seen_times = set([])
        for item in history:
            if item['t'] in seen_times:
                continue
            to_return.append(item)
            seen_times.add(item['t'])
        return to_return

    def fetch(self, instrument, granularity: CandlestickGranularity, start_time, end_time):
        logging.info('Fetching history for instrument ' + instrument + ' for granularity ' + granularity.name + ' from ' + str(start_time) + ' to ' + str(end_time))
        to_return = []
        for day in self._daterange(start_time, end_time):
            if self._is_in_store(instrument, granularity, day):
                to_return.extend(self._fetch_from_store(instrument, granularity, day))
            else:
                to_return.extend(self._fetch_from_provider(instrument, granularity, day))
        processed = self._filter_repeated_history(sorted(to_return, key=lambda x: x['t']))
        logging.info('History fetched, ' + str(len(processed)) + ' ticks')
        return processed


class StrategyDecision(Enum):
    NOTHING = 0
    BUY = 1
    SELL = 2
    BUY_CLOSE = 3
    SELL_CLOSE = 4


class Strategy:
    close_on_opposite_signal = True
    required_bars = 100

    @abc.abstractmethod
    def on_tick(self, history):
        pass


class RSIStrategy(Strategy):
    required_bars = 20

    def on_tick(self, history):
        rsi = talib.RSI(history['c'], timeperiod=14)
        if (rsi.iloc[-1] < 30):
            return StrategyDecision.BUY
        if (rsi.iloc[-1] > 70):
            return StrategyDecision.SELL
        return StrategyDecision.NOTHING


class EMACrossoverStrategy(Strategy):
    required_bars = 60

    def on_tick(self, history):
        fastma = talib.EMA(history['c'], timeperiod=14)
        slowma = talib.EMA(history['c'], timeperiod=56)
        if (fastma.iloc[-1] > slowma.iloc[-1]):
            return StrategyDecision.BUY
        if (slowma.iloc[-1] > fastma.iloc[-1]):
            return StrategyDecision.SELL
        return StrategyDecision.NOTHING


class EMARSIStrategy(Strategy):
    required_bars = 60

    def on_tick(self, history):
        fastma = talib.EMA(history['close'], timeperiod=14)
        slowma = talib.EMA(history['close'], timeperiod=56)
        rsi = talib.RSI(history['close'], timeperiod=14)
        if (rsi.iloc[-1] < 30 and fastma.iloc[-1] > slowma.iloc[-1]):
            return StrategyDecision.BUY
        if (rsi.iloc[-1] > 70 and slowma.iloc[-1] > fastma.iloc[-1]):
            return StrategyDecision.SELL
        return StrategyDecision.NOTHING


class EMARSIDataframeStrategy(Strategy):
    def get_dataframe(self, history):
        fastma = talib.EMA(history['c'], timeperiod=14)
        slowma = talib.EMA(history['c'], timeperiod=56)
        rsi = talib.RSI(history['c'], timeperiod=14)
        result = pandas.DataFrame()
        result['rsiBelow30'] = numpy.where(rsi < 30, True, False)
        result['fastAboveSlow'] = numpy.where(fastma > slowma, True, False)
        result['rsiAbove70'] = numpy.where(rsi > 70, True, False)
        return result


class IchimokuStrategy(Strategy):
    required_bars = 60

    def ichimoku(self, dataframe, conversion_line_period=9, base_line_period=26, laggin_span=52, displacement=26):
        tenkan_sen = (dataframe['high'].rolling(window=conversion_line_period).max() + dataframe['low'].rolling(window=conversion_line_period).min()) / 2
        kijun_sen = (dataframe['high'].rolling(window=base_line_period).max() + dataframe['low'].rolling(window=base_line_period).min()) / 2
        leading_senkou_span_a = (tenkan_sen + kijun_sen) / 2
        leading_senkou_span_b = (dataframe['high'].rolling(window=laggin_span).max() + dataframe['low'].rolling(window=laggin_span).min()) / 2
        senkou_span_a = leading_senkou_span_a.shift(displacement)
        senkou_span_b = leading_senkou_span_b.shift(displacement)
        chikou_span = dataframe['close'].shift(-displacement)
        cloud_green = (senkou_span_a > senkou_span_b)
        cloud_red = (senkou_span_b > senkou_span_a)
        return {
            'tenkan_sen': tenkan_sen,
            'kijun_sen': kijun_sen,
            'senkou_span_a': senkou_span_a,
            'senkou_span_b': senkou_span_b,
            'leading_senkou_span_a': leading_senkou_span_a,
            'leading_senkou_span_b': leading_senkou_span_b,
            'chikou_span': chikou_span,
            'cloud_green': cloud_green,
            'cloud_red': cloud_red,
        }

    def on_tick(self, history):
        ichimoku = self.ichimoku(history, conversion_line_period=20, base_line_period=40, laggin_span=80, displacement=50)
        tenkan = ichimoku['tenkan_sen']
        kijun = ichimoku['kijun_sen']
        senkou_a = ichimoku['senkou_span_a']
        senkou_b = ichimoku['senkou_span_b']
        if (tenkan.iloc[-1] > kijun.iloc[-1] and tenkan.iloc[-1] > senkou_a.iloc[-1] and tenkan.iloc[-1] > senkou_b.iloc[-1]):
            return StrategyDecision.BUY
        if (tenkan.iloc[-1] < kijun.iloc[-1] and kijun.iloc[-1] < senkou_a.iloc[-1] and kijun.iloc[-1] < senkou_b.iloc[-1]):
            return StrategyDecision.SELL
        return StrategyDecision.NOTHING


class OrderType(Enum):
    BUY = 1
    SELL = 2


class Backtester:
    def __init__(self, strategy: Strategy, history_manager: HistoryManager, instrument, granularity: CandlestickGranularity, spread, start_time, end_time):
        self.strategy = strategy
        self.history_manager = history_manager
        self.instrument = instrument
        self.granularity = granularity
        self.spread = spread
        self.start_time = start_time
        self.end_time = end_time


class GenericBacktester(Backtester):
    def __init__(self, strategy: Strategy, history_manager: HistoryManager, instrument, granularity: CandlestickGranularity, spread, start_time, end_time):
        super().__init__(strategy, history_manager, instrument, granularity, spread, start_time, end_time)
        self.history = pandas.DataFrame(self.history_manager.fetch(self.instrument, self.granularity, self.start_time, self.end_time))
        self.current_order = None
        self.trades = []

    def _open_order(self, order_type: OrderType, price):
        if not self.current_order:
            self.current_order = {'type': order_type, 'open_price': price}

    def _close_order(self, order_type: OrderType, price):
        if self.current_order and self.current_order['type'] == order_type:
            closed_order = self.current_order
            self.current_order = None
            closed_order.update({'close_price': price})
            self._register_closed_order(closed_order)

    def _register_closed_order(self, order):
        if order['type'] == OrderType.BUY:
            order.update({'profit': order['close_price'] - order['open_price'] - self.spread * 2})
        if order['type'] == OrderType.SELL:
            order.update({'profit': order['open_price'] - order['close_price'] - self.spread * 2})
        self.trades.append(order)

    def run(self):
        logging.info('Running backtesting on instrument ' + self.instrument)
        self.trades = []
        total_ticks = len(self.history.index)
        current_tick = 1
        while current_tick != total_ticks:
            strategy_decision = self.strategy.on_tick(self.history.head(current_tick).tail(self.strategy.required_bars))
            if strategy_decision == StrategyDecision.BUY:
                self._open_order(OrderType.BUY, pandas.to_numeric(self.history.iloc[[current_tick - 1]]['close']).iloc[0])
                if self.strategy.close_on_opposite_signal:
                    self._close_order(OrderType.SELL, pandas.to_numeric(self.history.iloc[[current_tick - 1]]['close']).iloc[0])
            if strategy_decision == StrategyDecision.SELL:
                self._open_order(OrderType.SELL, pandas.to_numeric(self.history.iloc[[current_tick - 1]]['close']).iloc[0])
                if self.strategy.close_on_opposite_signal:
                    self._close_order(OrderType.BUY, pandas.to_numeric(self.history.iloc[[current_tick - 1]]['close']).iloc[0])
            current_tick += 1


class TradeStatistics:
    def __init__(self, trades):
        self.trades = trades

    @property
    def count(self):
        return len(self.trades)

    @property
    def win(self):
        win = 0
        for trade in self.trades:
            if trade['profit'] > 0:
                win += 1
        return win

    @property
    def loss(self):
        return len(self.trades) - self.win

    @property
    def profit(self):
        profit = 0.0
        for trade in self.trades:
            profit += trade['profit']
        return profit


#from mt4forexparser.MT4ForexParser import MT4ParseToPD

if __name__ == '__main__':
    #history_provider = OandaHistoryProvider('https://api-fxpractice.oanda.com', '')
    #history_manager = HistoryManager(history_provider, 'mongodb://localhost:27017/', 'backstrat')
    #strategy = EMARSIStrategy()
    #backtester = GenericBacktester(strategy, history_manager, 'EUR_USD', CandlestickGranularity.M1, 0.00015, datetime(2020, 1, 1), datetime(2020, 7, 30))
    #cProfile.run('backtester.run()')
    #backtester.run()
    #stats = TradeStatistics(backtester.trades)
    #print('Total: ' + str(stats.count) + '; Win: ' + str(stats.win) + '; Loss: ' + str(stats.loss) + '; Profit: ' + str(stats.profit) + ';')
    #history = pandas.DataFrame(history_manager.fetch('EUR_USD', CandlestickGranularity.M1, datetime(2020, 5, 1), datetime(2020, 7, 30)))
    #result = EMARSIDataframeStrategy().get_dataframe(history)
    #print(result)
    #history = pandas.DataFrame(history_manager.fetch('EUR_USD', CandlestickGranularity.M1, datetime(2020, 7, 1), datetime(2020, 7, 30)))
    #history.plot(x='t', y='c')
    #plt.show()
    #df = MT4ParseToPD(historyFile="/home/user/shared/GBPUSD30.hst").tail(50000)
    #strategy = IchimokuStrategy()
    #backtester = GenericBacktester(strategy, df, 'EUR_USD', CandlestickGranularity.M1, 0.00015, datetime(2020, 1, 1), datetime(2020, 7, 30))
    #backtester.run()
    #stats = TradeStatistics(backtester.trades)
    #print('Total: ' + str(stats.count) + '; Win: ' + str(stats.win) + '; Loss: ' + str(stats.loss) + '; Profit: ' + str(stats.profit) + ';')

