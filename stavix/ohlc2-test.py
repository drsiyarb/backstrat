import requests
import json


def main():
    ohlc = []
    end_date = 1402874440

    while True:
        if end_date:
            params = {
                'limit': '1000',
                'step': '60',
                'end': end_date - 1
            }
        else:
            params = {
                'limit': '1000',
                'step': '60',
            }
        response = requests.get('https://www.bitstamp.net/api/v2/ohlc/btcusd/', params=params)
        data = response.json()
        if 'data' not in data or 'ohlc' not in data['data'] or len(data['data']['ohlc']) == 0:
            break
        data = data['data']['ohlc']
        ohlc.extend(data)
        end_date = int(data[len(data) - 1]['timestamp'])
        print('Fetched %d items, extended list to length of %s, end_date: %s' % (len(data), len(ohlc), str(end_date)))

    with open('ohlc1m.json', 'w') as outfile:
        json.dump(ohlc, outfile)


if __name__ == '__main__':
    main()
