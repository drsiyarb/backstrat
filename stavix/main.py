import time

from scipy.stats import kurtosis
from pymongo import MongoClient


class Stavix:

    def __init__(self, max_interval, ohlc_collection_name, run_collection_name):
        self.max_interval = max_interval
        self.ohlc_collection_name = ohlc_collection_name
        self.run_collection_name = run_collection_name
        self.history = []
        self.percents = []
        self.mongo_client = MongoClient()
        self.mongo_db = self.mongo_client.stavix
        self.ohlc_collection = self.mongo_db[self.ohlc_collection_name]
        self.run_collection = self.mongo_db[self.run_collection_name]

    @staticmethod
    def get_change(current, previous):
        if current == previous:
            return 0
        try:
            return ((float(current) - float(previous)) / float(previous)) * 100.0
        except ZeroDivisionError:
            return float('inf')

    def initialize_percents(self):
        self.history = [data['open'] for data in self.ohlc_collection.find().sort('timestamp', 1)]

        for n in range(0, self.max_interval):
            _percents = []
            prev_datum = None
            for datum in self.history[::n + 1]:
                if prev_datum is not None:
                    _percents.append(round(Stavix.get_change(datum, prev_datum), 1))
                prev_datum = datum
            self.percents.append(_percents)

    def get_run_analysis(self, identity, run_length, interval):
        cursor = self.run_collection.find({'interval': str(interval * 60), 'run': identity})
        if cursor.count() != 0:
            return cursor[0]

        instance_count = 0
        following_average = 0
        followers = []
        for i in range(0, len(self.percents[interval - 1])):
            if i + run_length + 1 == len(self.percents[interval - 1]):
                break
            if repr(self.percents[interval - 1][i:i + run_length]) == identity:
                instance_count += 1
                following_average += self.percents[interval - 1][i + run_length]
                followers.append(self.percents[interval - 1][i + run_length])
        if instance_count > 0:
            following_average /= instance_count
        run_analysis = {'interval': str(interval * 60),
                        'data': self.ohlc_collection_name,
                        'run': identity,
                        'instance_count': instance_count,
                        'following_average': following_average,
                        'kurtosis': kurtosis(followers),
                        'followers': followers}
        self.run_collection.insert_one(run_analysis)
        return run_analysis


class Emulator:

    def __init__(self, stavix, after_timestamp, max_interval, run_length):
        self.stavix = stavix
        self.after_timestamp = after_timestamp
        self.max_interval = max_interval
        self.run_length = run_length
        self.data = []

    def initialize(self):
        mongo_client = MongoClient()
        mongo_db = mongo_client.stavix
        ohlc_collection = mongo_db['bitstamp-one-minute-1602922620']

        self.data = [data['open'] for data in ohlc_collection.find({'timestamp': {'$gte': self.after_timestamp}}).sort('timestamp', 1)]
        print('Fetched ' + str(len(self.data)) + ' entries for timestamp after ' + str(self.after_timestamp))

    def run(self):
        ticks_seen = 0
        seen = []
        holding = False
        for i in range(0, len(self.data)):
            seen.append(self.data[i])

            ticks_seen += 1
            print('At tick ' + str(ticks_seen))
            analysis = []

            for interval in range(0, self.max_interval):
                if not len(seen) >= (interval + 1) * (self.run_length + 1):
                    break
                run_open = [open_datum for open_datum in seen[::-interval - 1]][:self.run_length + 1]
                run_open.reverse()
                run_percents = [round(Stavix.get_change(v1, v2), 1) for v1, v2 in zip(run_open, run_open[1:])]
                run_analysis = self.stavix.get_run_analysis(repr(run_percents), self.run_length, interval + 1)

                analysis.append(run_analysis)

            average = 0
            count = 0
            for anal in analysis:
                average += anal['following_average']
                count += 1
            if count > 0:
                average /= count

            if average > 0.01 and not holding:
                print('Bought at ' + str(seen[-1]))
                holding = True
            if average < -0.01 and holding:
                print('Sold at ' + seen[-1])
                holding = False


if __name__ == '__main__':
    stavix = Stavix(max_interval=60, ohlc_collection_name='bitstamp-one-minute-1602922620', run_collection_name='runs')
    stavix.initialize_percents()
    emulator = Emulator(stavix, '1602902620', 60, 3)
    emulator.initialize()
    emulator.run()
