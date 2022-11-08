import asyncio
import json
import logging
import os
import sqlite3
import ssl
from typing import List, Tuple
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
import backoff
import certifi

logger = logging.getLogger('logger')

MAX_HTTP_RETRIES = 3
CACHE_DATA_LIFESPAN = 50  # days
SQL_MAX_VARIABLES = 900  # max nb of variables in SQL prepared statements

def chunks(lst: List, n: int) -> List:
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]

class Singleton(type):
    _instances = {}
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class RetriableError(aiohttp.ClientResponseError):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

class RequestsCache():
    def __init__(self):
        self._conn = None
        self._actions_pending = 0

    def __del__(self):
        self.close()

    def set_db_path(self, db_path: str = None) -> None:
        logger.debug('RequestsCache: set db_path=%s', db_path)

        if db_path is not None:
            self.close()
            folders, _ = os.path.split(db_path)
            if not os.path.exists(folders):
                os.makedirs(folders)

            self._conn = sqlite3.connect(db_path)  # pylint: disable=no-member
            self._conn.execute('''
                CREATE TABLE IF NOT EXISTS
                    responses (
                        'url' TEXT NOT NULL PRIMARY KEY,
                        'response' TEXT NOT NULL,
                        'last_accessed' TEXT NOT NULL
                        )
            ''')

    def _normalize_url(self, url: str) -> str:
        split_url = urlsplit(url)
        query = split_url[3]
        query_params = [param for param in parse_qsl(query) if param[0] != 'api_key']
        query_params.sort(key=lambda param: param[0])
        normalized_url = urlunsplit(split_url._replace(query=urlencode(query_params)))

        return normalized_url

    def _update_count(self, count: int = 1) -> None:
        if self._conn is not None:
            self._actions_pending += count
            if self._actions_pending >= 100:
                logger.debug('RequestsCache: committing %s actions', self._actions_pending)
                self._conn.commit()
                self._actions_pending = 0

    def retrieve(self, url: str) -> dict:
        result = None
        if self._conn is not None:
            normalized_url = self._normalize_url(url)
            cursor = self._conn.cursor()
            cursor.execute("SELECT response FROM responses WHERE url=?", (normalized_url, ))
            results = cursor.fetchone()

            if results is not None:
                try:
                    result = json.loads(results[0])
                except ValueError:
                    logger.error(
                        'RequestsCache - retrieve: Could not parse reply for URL %s',
                        normalized_url)
                logger.debug('Retrieved data from cache for url %s', url)

        return result

    def retrieve_all(self, urls: List[str]) -> Tuple[dict, List[str]]:
        hits = {}
        missed = []
        urls_chunks = chunks(urls, SQL_MAX_VARIABLES)

        cache_results = {}
        if self._conn is not None:
            for chunk in urls_chunks:
                norm_urls = [self._normalize_url(url) for url in chunk]
                cursor = self._conn.cursor()
                cursor.execute(
                    f"SELECT url, response FROM responses WHERE url IN ({','.join(['?']*len(norm_urls))})",
                    norm_urls)
                rows = cursor.fetchall()

                cache_results.update(dict(rows))

        for url in urls:
            normalized_url = self._normalize_url(url)
            if normalized_url not in cache_results:
                missed.append(url)
            else:
                try:
                    hits[url] = json.loads(cache_results[normalized_url])
                except ValueError:
                    logger.error(
                        'RequestsCache - retrieve_all: Could not parse reply for URL %s',
                        normalized_url)
                    hits[url] = None

        logger.debug('Retrieved %s responses from cache, %s misses', len(hits), len(missed))

        return hits, [*missed]

    def create_or_update(self, url, response) -> None:
        if self._conn is not None and response is not None:
            normalized_url = self._normalize_url(url)
            self._conn.execute(
                "INSERT OR REPLACE INTO responses(url, response, last_accessed) VALUES (?, ?, datetime('now'))",
                (normalized_url, json.dumps(response)))
            self._update_count()
            logger.debug('RequestsCache - stored result for url %s', normalized_url)

    def create_or_update_all(self, data: dict):
        # logger.debug('Storing %s results in cache', len(data))
        if self._conn is not None:
            values = [(self._normalize_url(url), json.dumps(response)) for url, response
                      in data.items() if response is not None]
            self._conn.executemany("INSERT OR REPLACE INTO responses VALUES (?,?,datetime('now'))", values)
            self._update_count(len(values))
            logger.debug('Stored %s values in cache', len(values))

    def flush(self, max_age: int):
        if max_age < 0:
            raise ValueError('Max age must be greater than 0!')

        if self._conn is not None:
            days_delta = f'-{max_age} day'
            self._conn.execute(
                "DELETE FROM responses WHERE last_accessed <= datetime('now', ?)",
                (days_delta,))
            self._update_count()
            logger.debug('RequestsCache: flushed results older than %s days from cache', max_age)

    def close(self):
        if self._conn is not None:
            if self._actions_pending > 0:
                self._conn.commit()
                self._actions_pending = 0
            self._conn.close()
            self._conn = None

class DataFetcherInterface:
    _instance = None

    def __init__(self):
        pass

    async def close(self):
        pass

    async def fetch(self, url, no_concurrency=False, skip_cache=False) -> dict:
        pass

    async def fetch_all(self, urls: List[str], no_concurrency=False, skip_cache=False) -> dict:
        pass


class HttpFetcher(DataFetcherInterface, metaclass=Singleton):
    def __init__(self, max_nb_requests: int = 9, **kwargs):
        super(HttpFetcher, self).__init__(**kwargs)
        logger.debug('Create HttpFetcher instance with args: max_nb_requests = %s', max_nb_requests)
        self._session = aiohttp.ClientSession(raise_for_status=False)
        self._ssl_ctx = ssl.create_default_context(cafile=certifi.where())
        self._max_nb_requests = max_nb_requests
        self._sem_throttle = asyncio.Semaphore(max_nb_requests)
        self._sem_concurrency = asyncio.Semaphore(1)
        self._time_period = kwargs.get('time_period', 1.0)
        self._loop = asyncio.get_event_loop()

    async def set_rate(self, max_nb_requests: int):
        logger.debug('HttpFetcher set rate = %s', max_nb_requests)
        delta = max_nb_requests - self._max_nb_requests
        if (delta > 0):
            for _ in range(delta):
                self._sem_throttle.release()
        elif (delta < 0):
            for _ in range(-delta):
                await self._sem_throttle.acquire()

        self._max_nb_requests = max_nb_requests

    async def close(self):
        if self._session is not None:
            await self._session.close()
            self._session = None

    @backoff.on_exception(
        backoff.fibo,
        (RetriableError, aiohttp.ClientConnectionError),
        max_tries=MAX_HTTP_RETRIES)
    async def _fetch_retry(self, url) -> dict:
        await self._sem_throttle.acquire()

        headers = {'x-sw-source': 'TSA - Similarweb Extract App'}
        async with self._session.get(url, headers=headers, ssl=self._ssl_ctx) as response:
            logger.debug('HttpFetcher - http get: %s', url)
            self._loop.call_later(self._time_period, self._sem_throttle.release)

            if response.status == 429 or 500 <= response.status < 600:
                logger.warning('Error %s - retrying with url %s', response.status, url)
                raise RetriableError(request_info=url, status=response.status,
                                     message=await response.text(), history=())

            elif response.status == 400 and response.content_type == 'application/json':
                content = await response.json()
                meta = content.get('meta', {})
                error_msg = f'Similarweb error {meta.get("error_code")} - {meta.get("error_message")}'
                raise aiohttp.ClientResponseError(request_info=url, status=response.status,
                                                  message=error_msg, history=())

            # treat 404 (no data) as valid responses so they are stored in cache
            elif response.status >= 400 and response.status != 404:
                raise aiohttp.ClientResponseError(request_info=url, status=response.status,
                                                  message=await response.text(), history=())

            if response.content_type == 'application/json':
                return await response.json()
            else:
                logger.error('HttpFetcher - non JSON response: %s (status = %s)', await response.text(), response.status)
                return None

    async def fetch(self, url, no_concurrency=False, skip_cache=False) -> dict:
        result = None
        try:
            if no_concurrency:
                async with self._sem_concurrency:
                    logger.info('**** No Concurrency - calling URL: %s', url)
                    result = await self._fetch_retry(url)
                    logger.info('**** No Concurrency - retrieved URL: %s', url)
            else:
                logger.info('**** Concurrency OK - calling URL: %s', url)
                result = await self._fetch_retry(url)
                logger.info('**** Concurrency OK - retrieved URL: %s', url)

        except aiohttp.ClientResponseError as cre:
            logger.error('HttpFetcher - error with url %s: %s', url, cre.message)
        except aiohttp.ClientConnectionError as cce:
            logger.error('HttpFetcher - connection error for url %s: %s', url, cce)

        return result

    async def fetch_all(self, urls: List[str], no_concurrency=False, skip_cache=False) -> dict:
        results = {}

        responses = await asyncio.gather(*[self.fetch(url, no_concurrency) for url in urls])
        for url, data in zip(urls, responses):
            results[url] = data

        return results


class CachedDataFetcher(DataFetcherInterface, metaclass=Singleton):
    def __init__(self):
        super(CachedDataFetcher, self).__init__()
        logger.debug('Create CachedDataFetcher instance')
        self._api_fetcher = HttpFetcher()
        self._cache = RequestsCache()
        self._loop = asyncio.get_event_loop()

    def set_db_path(self, db_path: str):
        self._cache.set_db_path(db_path)

    async def set_rate(self, max_nb_requests: int):
        await self._api_fetcher.set_rate(max_nb_requests)

    async def close(self):
        self._cache.flush(CACHE_DATA_LIFESPAN)
        self._cache.close()
        await self._api_fetcher.close()


    async def fetch(self, url, no_concurrency=False, skip_cache=False) -> dict:
        result = self._cache.retrieve(url) if not skip_cache else None
        if not result:
            result = await self._api_fetcher.fetch(url, no_concurrency)

        if not skip_cache and result is not None:
            self._cache.create_or_update(url, result)

        return result

    async def fetch_all(self, urls: List[str], no_concurrency=False, skip_cache=False) -> dict:
        results, misses = self._cache.retrieve_all(urls) if not skip_cache else ([], urls)
        api_results = await self._api_fetcher.fetch_all(misses, no_concurrency)
        results.update(api_results)

        if not skip_cache:
            self._cache.create_or_update_all(results)

        return results
