import json

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
    mongo_collection = mongo_db['one-hour-one-run']

    with open('./ohlc1h.json') as json_file:
        data = json.load(json_file)

    data = [datum[1] for datum in data]

    percents = []
    prev_datum = None
    for datum in data:
        if prev_datum is not None:
            percents.append(get_change(datum, prev_datum))
        prev_datum = datum

    runs = []
    n = 1
    for i, percent in enumerate(percents):
        if i + n < len(percents):
            run = [round(percent, 1)]
            for j in range(i + 1, i + n + 1):
                run.append(round(percents[j], 1))
            runs.append(run)

    run_statistics = {}
    for run in runs:
        identity = repr(run[:-1])
        if identity in run_statistics:
            continue
        instance_count = 0
        following_average = 0
        followers = []
        for _run in runs:
            if run[:-1] == _run[:-1]:
                instance_count += 1
                following_average += _run[-1]
                followers.append(_run[-1])
        following_average /= instance_count
        run_statistics[identity] = {'run': identity,
                                    'instance_count': instance_count,
                                    'following_average': following_average,
                                    'kurtosis': kurtosis(followers),
                                    'followers': followers}
        mongo_collection.insert_one(run_statistics[identity])


if __name__ == "__main__":
    main()
