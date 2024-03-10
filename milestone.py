#!/usr/bin/python3

import json, re, sys
from lib.config import *
from lib import sharesight
from lib import webhook
from lib import util
from lib import yahoo

# BUGS:
# - need to handle stock splits: flush cache if we see a split in yahoo
# https://finance.yahoo.com/quote/TSLA/history?period1=0&period2=1707609600&filter=split

def lambda_handler(chat_id=config_telegramChatID, specific_stock=None, service=None, interactive=False):
    def prepare_ath_payload(service, market_data):
        emoji = '⭐'
        payload = []
        payloadhigh = []
        payloadlow = []
        payloadprofit = []
        payloadcashflow = []
        payloadprofitneg = []
        payloadcashflowneg = []
        oldhigh = float()
        oldlow = float()
        records = util.json_load('finbot_ath.json', persist=True)
        if records is None:
            records = {}
        for ticker in tickers:
            try:
                oldhigh = records[ticker]['high']
                oldlow = records[ticker]['low']
            except (KeyError, TypeError):
                records[ticker] = {}
                records[ticker]['high'] = float()
                records[ticker]['low'] = float()
                try:
                    oldhigh, oldlow = yahoo.historic_high(ticker, market_data) # first run to prime cache file
                except (KeyError, TypeError):
                    continue
            try:
                newhigh = round(market_data[ticker]['fiftyTwoWeekHigh'], 2)
                newlow = round(market_data[ticker]['fiftyTwoWeekLow'], 2)
            except (KeyError, ValueError):
                continue

            newprofit = False
            newcashflow = False
            notify = True
            try:
                oldprofit = records[ticker]['profit']
                oldcashflow = records[ticker]['cashflow']
            except (KeyError, TypeError):
                notify = False
                oldprofit = False
                oldcashflow = False
            detail = yahoo.fetch_detail(ticker)
            if ticker in detail:
                if 'net_income' in detail[ticker]:
                    if detail[ticker]['net_income'] > 0:
                        newprofit = True
                if 'free_cashflow' in detail[ticker]:
                    if detail[ticker]['free_cashflow'] > 0:
                        newcashflow = True
            title = market_data[ticker]['profile_title']
            ticker_link = util.finance_link(ticker, market_data[ticker]['profile_exchange'], service)
            emoji = util.flag_from_ticker(ticker)
            records[ticker]['high'] = oldhigh
            records[ticker]['low'] = oldlow
            records[ticker]['profit'] = oldprofit
            records[ticker]['cashflow'] = oldcashflow
            if newhigh > oldhigh:
                if debug:
                    print("DEBUG", ticker, newhigh, "is higher than", oldhigh)
                records[ticker]['high'] = newhigh
                payloadhigh.append(f"{emoji} {title} ({ticker_link})")
            if newlow < oldlow:
                if debug:
                    print("DEBUG", ticker, newlow, "is lower than", oldlow)
                records[ticker]['low'] = newlow
                payloadlow.append(f"{emoji} {title} ({ticker_link})")
            if oldprofit != newprofit:
                records[ticker]['profit'] = newprofit
                if notify and newprofit:
                    payloadprofit.append(f"{emoji} {title} ({ticker_link})")
                if notify and not newprofit:
                    payloadprofitneg.append(f"{emoji} {title} ({ticker_link})")
            if oldcashflow != newcashflow:
                records[ticker]['cashflow'] = newcashflow
                if notify and newcashflow:
                    payloadcashflow.append(f"{emoji} {title} ({ticker_link})")
                if notify and not newcashflow:
                    payloadcashflowneg.append(f"{emoji} {title} ({ticker_link})")
        payloadlow.sort()
        payloadhigh.sort()
        payloadprofit.sort()
        payloadcashflow.sort()
        payloadprofitneg.sort()
        payloadcashflowneg.sort()
        if payloadhigh:
            message = 'Record high:'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadhigh
        if payloadlow:
            if payloadhigh:
                payload.append("")
            message = 'Record Low:'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadlow
        if payloadprofit:
            if payloadhigh or payloadlow:
                payload.append("")
            message = 'Became profitable'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadprofit
        if payloadcashflow:
            if payloadhigh or payloadlow or payloadprofit:
                payload.append("")
            message = 'Became cashflow positive'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadcashflow
        if payloadprofitneg:
            if payloadhigh or payloadlow or payloadprofit or payloadcashflow:
                payload.append("")
            message = 'Became unprofitable'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadprofitneg
        if payloadcashflowneg:
            if payloadhigh or payloadlow or payloadprofit or payloadcashflow or payloadprofitneg:
                payload.append("")
            message = 'Became cashflow negative'
            message = webhook.bold(message, service)
            payload.append(message)
            payload = payload + payloadcashflowneg
        return payload, records

    # MAIN #

    market_data = {}
    if specific_stock:
        ticker = util.transform_to_yahoo(specific_stock)
        tickers = [ticker]
    else:
        tickers = util.get_holdings_and_watchlist()
        tickers = list(tickers)
        tickers.sort()
        #tickers = ['BUGG.AX'] # DEBUG
        market_data = yahoo.fetch(tickers)

    # Prep and send payloads
    if not webhooks:
        print("Error: no services enabled in .env", file=sys.stderr)
        sys.exit(1)
    else:
        for service, url in webhooks.items():
            payload, records = prepare_ath_payload(service, market_data)
            if service == "telegram":
                url = url + "sendMessage?chat_id=" + str(chat_id)
            webhook.payload_wrapper(service, url, payload, chat_id)

    if records:
        util.json_write('finbot_ath.json', records, persist=True)

    # make google cloud happy
    return True

if __name__ == "__main__":
    lambda_handler()
