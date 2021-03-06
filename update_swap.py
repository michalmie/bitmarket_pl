#!/usr/bin/python
import requests
import hmac
import hashlib
import time
import simplejson as json
import logging
from decimal import Decimal
from pprint import pprint

def setupLogger():
	logger = logging.getLogger('update_swap')
	logger.setLevel(logging.DEBUG)
	fh = logging.FileHandler('update_swap.log')
	fh.setLevel(logging.DEBUG)
	ch = logging.StreamHandler()
	ch.setLevel(logging.INFO)
	formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
	fh.setFormatter(formatter)
	ch.setFormatter(formatter)
	logger.addHandler(fh)
	logger.addHandler(ch)
	return logger

logger = setupLogger()

configFile = open('config.json', 'r')
config = json.load(configFile, use_decimal = True)
configFile.close()

sleepTimeBetweenChecks = config['sleep_between_checks_in_seconds']
publicKey = str(config['public_api_key'])
secretKey = str(config['secret_api_key'])
offsetFromCutoff = config['offset_from_cuttof']

logger.info('SleepTime: ' + str(sleepTimeBetweenChecks) + ' PublicKey: ' + publicKey + ' SecretKey: ' + secretKey + ' cutoff_ofset: ' + str(offsetFromCutoff))


def mergeTwoDicts(x, y):
	z = x.copy()
	z.update(y)
	return z

def getCurrentCutOff():
	swapStateJson = json.loads(requests.get('https://www.bitmarket.pl/json/swapBTC/swap.json').text, use_decimal = True)
	cutoff = swapStateJson['cutoff']
	logger.debug('demand = ' + str(swapStateJson['demand']))
	return cutoff

def bitMarketPlApiCall(method, params = {}):
	postDataAsDict = mergeTwoDicts(params, {
		'method': method,
		'tonce': int(time.time())
	})
	postParamsAsString = "&".join([param + '=' + str(postDataAsDict[param]) for param in postDataAsDict])

	postHeaders = {
		'API-Key': publicKey,
		'API-Hash': hmac.new(secretKey, postParamsAsString, hashlib.sha512).hexdigest()
	}

	logger.debug("Request data: " + postParamsAsString + " headers: " + str(postHeaders))
	request_response = requests.post('https://www.bitmarket.pl/api2/', data = postParamsAsString, headers = postHeaders)

	if request_response.status_code == 200 and not ('error' in request_response.text):
		logger.debug(request_response)
		logger.debug(request_response.text)
	else:
		logger.error(request_response)
		logger.error(request_response.text)

	return request_response

def closeSwapPosition(id):
	logger.info('closing swap position: ' + str(id))
	bitMarketPlApiCall('swapClose', { 'id': id, 'currency': 'BTC' })

def openSwapPosition(amount, rate):
	logger.info('Opening new swap position. Amount: ' + str(amount) + ' BTC, Rate: ' + str(rate) + ' %')
	bitMarketPlApiCall('swapOpen', { 'amount': amount, 'rate': rate, 'currency': 'BTC' })

def checkIfShouldUpdateSwapRate():
	totalEarnings = 0
	stableCount = 0
	previousCutOff = Decimal('-1')

	while True:
		try:
			currentCutOff = getCurrentCutOff()
			if previousCutOff < Decimal('0'):
				previousCutOff = currentCutOff

			logger.info('Current cutoff ' + str(currentCutOff) + ' Previous cutoff ' + str(previousCutOff))

			currentSwapPositions = json.loads(bitMarketPlApiCall('swapList', { 'currency': 'BTC' }).text, use_decimal = True)['data']
			if len(currentSwapPositions) == 0:
				logger.warn('No swap position to maximize, create a position.')
				time.sleep(sleepTimeBetweenChecks)
				continue

			currentSwapPosition = currentSwapPositions[0]


			currentRate = currentSwapPosition['rate']
			earnings = currentSwapPosition['earnings']
			earningsAsString = '{0:f}'.format(earnings)
			currentAmount = currentSwapPosition['amount']
			diffFromPreviousCutoff = previousCutOff - currentCutOff

			weAreNotEarning = currentRate >= currentCutOff

			if diffFromPreviousCutoff < Decimal('0.01'):
				stableCount = stableCount + 1
			else:
				stableCount = 0

			weCouldEarnMore = (currentCutOff - currentRate) >= Decimal('0.5') and stableCount > 10
			logger.debug('diffFromPreviousCutoff: ' + str(diffFromPreviousCutoff) + ' notEarning: ' + str(weAreNotEarning) + ' couldEarnMore: ' + str(weCouldEarnMore))

			if weAreNotEarning or weCouldEarnMore:
				if weCouldEarnMore:
					newRate = currentCutOff - offsetFromCutoff
					logger.info('let\' increase rate from ' + str(currentCutOff) + ' to ' + str(newRate))
				else:
					newRate = currentCutOff - max(diffFromPreviousCutoff * 5, offsetFromCutoff)
					logger.info('let\' decrease rate from ' + str(currentCutOff) + ' to ' + str(newRate))

				logger.info('current rate: ' + str(currentRate) + ' is not ok. Changeing to: ' + str(newRate))
				closeSwapPosition(currentSwapPosition['id'])

				time.sleep(2)

				logger.info('swap position ' + str(currentSwapPosition['id']) + ' earned: ' + earningsAsString + ' with amount: ' + str(currentAmount))
				newAmount = currentAmount + earnings - Decimal('0.00000005') # sometimes API returns not precise values, giving wrong value will leave us with no position opened
				openSwapPosition(newAmount, newRate)
				totalEarnings = totalEarnings + earnings
			else:
				logger.info('current rate: ' + str(currentRate) + ' is ok. Earnings: ' + earningsAsString + ' BTC. Total earnings: ' + '{0:f}'.format(totalEarnings + earnings))
			
			previousCutOff = currentCutOff

		except Exception as ex:
			logger.error(ex, exc_info=True)

		time.sleep(sleepTimeBetweenChecks)

def main():
	checkIfShouldUpdateSwapRate()

if __name__ == '__main__':
	main()
