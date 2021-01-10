import requests

from pymongo import MongoClient


def main():
    mongo_client = MongoClient()
    mongo_db = mongo_client.stavix
    mongo_collection = mongo_db['bitstamp-one-minute-ohlc']

    oldest_document = mongo_collection.find().sort('timestamp', 1).limit(1)
    oldest_timestamp = int(oldest_document[0]['timestamp']) if oldest_document and oldest_document.count() > 0 else 2000000000

    while True:
        params = {
            'limit': '1000',
            'step': '60',
            'end': oldest_timestamp - 1
        }
        response = requests.get('https://www.bitstamp.net/api/v2/ohlc/btcusd/', params=params)
        data = response.json()
        if 'data' not in data or 'ohlc' not in data['data'] or len(data['data']['ohlc']) == 0:
            break
        data = data['data']['ohlc']
        mongo_collection.insert_many(data)
        oldest_document = mongo_collection.find().sort('timestamp', 1).limit(1)[0]
        oldest_timestamp = int(oldest_document['timestamp'])
        print('Fetched "%d", oldest timestamp "%d", Mongo count "%d"' % (len(data), oldest_timestamp, mongo_collection.count()))


if __name__ == '__main__':
    main()