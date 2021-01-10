from scipy.stats import kurtosis
from pymongo import MongoClient


def get_change(current, previous):
    if current == previous:
        return 0
    try:
        return ((float(current) - float(previous)) / float(previous)) * 100.0
    except ZeroDivisionError:
        return float('inf')


def main():
    mongo_client = MongoClient()
    mongo_db = mongo_client.stavix
    mongo_collection = mongo_db['runs_3_10min']
    ohlc_collection = mongo_db['bitstamp-one-minute-1602922620']

    #ohlc_collection.create_index([('timestamp', -1)])

    data = [data['open'] for data in ohlc_collection.find().sort('timestamp', -1)]
    data = data[::10]

    percents = []
    prev_datum = None
    for datum in data:
        if prev_datum is not None:
            percents.append(get_change(datum, prev_datum))
        prev_datum = datum

    runs = []
    n = 3
    for i, percent in enumerate(percents):
        if i + n < len(percents):
            run = [round(percent, 1)]
            for j in range(i + 1, i + n + 1):
                run.append(round(percents[j], 1))
            runs.append(run)

    run_statistics = {}
    for run in runs:
        identity = repr(run[:-1])
        if mongo_collection.find({'run': identity}).count() > 0:
            print('Skipping run ' + identity + ' because it is already in collection')
            continue
        instance_count = 0
        following_average = 0
        followers = []
        for _run in runs:
            if repr(run[:-1]) == repr(_run[:-1]):
                instance_count += 1
                following_average += _run[-1]
                followers.append(_run[-1])
        following_average /= instance_count
        run_statistics[identity] = {'interval': '600',
                                    'data': 'bitstamp-one-minute-1602922620',
                                    'run': identity,
                                    'instance_count': instance_count,
                                    'following_average': following_average,
                                    'kurtosis': kurtosis(followers),
                                    'followers': followers}
        print('Run analysis complete. '
              'Identity: ' + identity +
              '. Following average: ' + str(following_average) +
              '. Instance count: ' + str(instance_count))
        print('Inserting one with ' + str(following_average) + ' following average')
        mongo_collection.insert_one(run_statistics[identity])

if __name__ == "__main__":
    main()
