import asyncio
import configparser
import logging
import os
from urllib.parse import urlencode, urlparse, urlunsplit

from .DataFetcher import CachedDataFetcher
from .DataWriter import CsvWriter, XlsxWriter
from .helpers import chunks, decode_country, get_available_date_range, get_config_path, load_domains_list, months_before, months_between
from .ProgressBar import ProgressBar

logger = logging.getLogger('logger')

def parse_config():
    config = configparser.ConfigParser()
    config_file = config_file = os.path.join(get_config_path(), 'config.ini')

    logger.debug('Reading config file located at: %s', config_file)
    config.read(config_file)

    default_config = {
        'API': {
            'host': 'https://api.similarweb.com',
            'api_key': '',
            'countries': 'world',
            'start_date': '',
            'end_date': '',
            'nb_months': '1',
            'time_period_type': '1',
        },
        'Paths': {
            'domains_path': '',
        },
        'Output': {
            'format': 'csv',
            'is_custom': 'no',
            'folder': ''
        },
    }

    for section, options in default_config.items():
        if not config.has_section(section):
            config.add_section(section)
        for option in options:
            if not config.has_option(section, option) or (section == 'Metrics' and config.get(section, option) == ''):
                config.set(section, option, default_config[section][option])

    return config

async def dom_results(dom, config, start_date, end_date, fetcher):
    host = urlparse(config.get('API', 'host'))
    logger.debug('Getting results for domain: %s', dom)
    results = []

    params = {
        'api_key': config.get('API', 'api_key'),
        'start_date': start_date,
        'end_date': end_date,
        'country': 'world',
        'main_domain_only': 'false',
        'show_verified': 'false',
        'format': 'json',
    }

    country_codes = (c.strip().lower() for c in config.get('API', 'countries').split(','))

    for country_code in country_codes:
        params['country'] = country_code
        url_visits = urlunsplit((host.scheme, host.netloc, '/v1/website/{}/total-traffic-and-engagement/visits'.format(dom), urlencode(params), ''))
        data_visits = await fetcher.fetch(url_visits)

        if data_visits is not None and 'visits' in data_visits:
            results.extend([{
                'Domain': dom,
                'Country': decode_country(country_code),
                'Month': val.get('date'),
                'Visits': val.get('visits'),
            } for val in data_visits.get('visits')])

    return results

async def execute(pbar: ProgressBar, **kwargs) -> None:
    fetcher = CachedDataFetcher()
    config = parse_config()
    domains_list_path = config.get('Paths', 'domains_path')
    domains = load_domains_list(domains_list_path)

    mode = kwargs.get('mode', 'headless')
    logger.debug('Retrieve data for %s domains (%s)', len(domains), mode)

    start_date = config.get('API', 'start_date')
    end_date = config.get('API', 'end_date')
    time_period_type = config.getint('API', 'time_period_type')

    if time_period_type == 1:
        available_range = await get_available_date_range(fetcher)
        nb_months = config.getint('API', 'nb_months')
        months = months_before(available_range.get('end_date'), nb_months)
        start_date = months[0]
        end_date = months[-1]

    output_folder, filename = os.path.split(domains_list_path)
    if config.getboolean('Output', 'is_custom'):
        output_folder = config.get('Output', 'folder')

    data_writer = None
    if config.get('Output', 'format') == 'xlsx':
        data_writer = XlsxWriter(output_folder, filename)
    else:
        data_writer = CsvWriter(output_folder, filename)

    headers = [
        'Domain',
        'Country',
        'Month',
        'Visits',
    ]
    data_writer.create_table(headers)

    pbar.reset(max_value=len(domains), message='Loading Data')
    with pbar:
        for chunk in chunks(domains, 20):
            tasks = [asyncio.ensure_future(dom_results(domain, config, start_date, end_date, fetcher)) for domain in chunk]

            for task in tasks:
                dom_data = await task

                if dom_data is not None:
                    data_writer.add_rows(dom_data)

                pbar.increment()

    data_writer.close()


def hits_per_domain(config):
    countries = [c for c in config.get('API', 'countries').split(',') if c != '']
    return 1 * len(countries)
