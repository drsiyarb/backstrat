import requests
import json


def main():
    ohlc = []
    last_date = 0
    while True:
        params = {
            'symbol': 'BTCUSDT',
            'interval': '1m',
            'limit': 1000,
            'startTime': last_date
        }
        response = requests.get('https://api.binance.com/api/v3/klines', params=params)
        data = response.json()
        if len(data) == 0:
            break
        ohlc.extend(data)
        print('Fetched %d items, extended list to length of %s' % (len(data), len(ohlc)))
        last_date = data[-1][6]
    with open('ohlc1m.json', 'w') as outfile:
        json.dump(ohlc, outfile)


if __name__ == '__main__':
    main()
