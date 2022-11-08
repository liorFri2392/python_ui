import asyncio
import csv
import logging
import os
import re
import urllib
from calendar import monthrange
from datetime import datetime, timedelta
from typing import List, Tuple

import chardet
import pycountry
import requests

from .DataFetcher import CachedDataFetcher

logger = logging.getLogger('logger')

if os.name != "posix":
    # pylint: disable=import-error
    from win32com.shell import shell, shellcon
    HOMEDIR = "{}\\".format(shell.SHGetFolderPath(0, shellcon.CSIDL_LOCAL_APPDATA, 0, 0))
else:
    HOMEDIR = "{}/".format(os.path.expanduser("~"))

async def get_available_date_range(fetcher: CachedDataFetcher) -> str:
    available_range = {}
    data_describe = await fetcher.fetch('https://api.similarweb.com/v1/website/xxx/traffic-and-engagement/describe', skip_cache=True)
    if data_describe is not None:
        available_range = data_describe.get('response', {}).get('traffic_and_engagement', {
        }).get('countries', {}).get('world', {})

    return available_range

def get_config_path():
    config_path = os.path.join(HOMEDIR, 'SimilarwebExtract-Custom')
    if not os.path.exists(config_path):
        os.makedirs(config_path)
    return config_path

def load_domains_list(file_path: str) -> List[Tuple[str, str]]:
    # Read domains and call API
    logger.info('Loading domains from file: %s', file_path)
    # Regular expression to validate domains
    re_domain = re.compile(r'(?:https?://)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}(?:/.*)?')

    domains_list = []
    charenc = 'utf-8'
    try:
        with open(file_path, 'rb') as f:
            rawdata = f.read()
            result = chardet.detect(rawdata)
            charenc = result['encoding']

        with open(file_path, newline='', encoding=charenc) as csvfile:
            csv_rows = csv.reader(csvfile)
            for row in csv_rows:
                for cell in row:
                    if cell != '' and re_domain.match(cell):
                        domains_list.append(clean_domain(cell))

    except (FileNotFoundError, IsADirectoryError, PermissionError, ValueError) as err:
        logger.error('Error Loading Domains List: %s', err)

    logger.info('Loaded %s domains', len(domains_list))
    return domains_list

def chunks(lst: List, n: int) -> List:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

def date_to_year_month(date: str) -> str:
    return '-'.join(date.split('-')[:2])


def months_between(start_month: str, end_month: str) -> List[str]:
    if start_month > end_month:
        start_month, end_month = end_month, start_month

    year, month = (int(x) for x in start_month.split('-')[:2])
    end_year, end_month = (int(x) for x in end_month.split('-')[:2])

    if month > 12 or end_month > 12:
        raise ValueError('Incorrect Date Format')

    result = []
    while (year < end_year or month < end_month):
        result.append(f'{year:04d}-{month:02d}')
        if month < 12:
            month += 1
        else:
            month = 1
            year += 1

    result.append(f'{year:04d}-{month:02d}')

    return result

def days_before(date: str, nb_days: int = 28) -> List[str]:
    dt = datetime.strptime(date, '%Y-%m-%d')

    result = []
    for i in reversed(range(nb_days)):
        current_date = dt-timedelta(days=i)
        result.append(f'{current_date.year:04d}-{current_date.month:02d}-{current_date.day:02d}')

    return result

def months_before(month: str, nb_months: int = 12) -> List[str]:
    last_month = '-'.join(month.split('-')[:2])
    return months_between('2018-01', last_month)[-nb_months:]

def decode_country(code: str) -> str:
    country_code = str(code)
    if country_code.lower() == 'world' or country_code == '999':
        return 'World'

    country = pycountry.countries.get(alpha_2=country_code)
    if country is None:
        country_code_num = country_code.zfill(3)
        country = pycountry.countries.get(numeric=country_code_num)

    return country.name if country is not None else country_code


def clean_domain(domain: str) -> str:
    """ Strips a domain from the unnecessary information (protocol / www. / folders) in order
    to make it ready to process by Similarweb's API

    Args:
        domain (str): domain/url to be cleaned

    Returns:
        str: cleaned domain
    """
    domain = domain.strip().lower()
    domain = re.sub(r'^(?:https?:\/\/)?(?:www\.)?', '', domain)  # remove protocol
    domain = re.sub(r'\/.*$', '', domain)  # remove folder
    domain = urllib.parse.quote(domain, safe='')  # url safe

    return domain

def mask(unmasked: str, show_last: int = 6) -> str:
    """ Obfuscate string to hide sensitive information

    Args:
        unmasked (str): string to obfuscate
        show_last (int, optional): Number of characters that should not be shown in clear (at the end of the string). Defaults to 6.

    Returns:
        str: obfuscated string
    """
    return (len(unmasked[:-show_last]) * '*') + unmasked[-show_last:]

def get_fresh_data_date() -> str:
    fresh_data = None

    response = requests.get('https://api.similarweb.com/v1/website/xxx/traffic-and-engagement/describe')
    if response:
        data_describe = response.json()
        fresh_data = data_describe.get('response', {}).get('traffic_and_engagement', {}).get('countries', {}).get('world', {}).get('fresh_data')

    return fresh_data

def first_day_of_month(date: str) -> str:
    return f'{date_to_year_month(date)}-01'

def last_day_of_month(date: str) -> str:
    year, month = [int(val) for val in date_to_year_month(date).split('-')]
    _, last_day = monthrange(year, month)
    
    return f'{year:04d}-{month:02d}-{last_day:02d}'


class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
