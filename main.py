import argparse
import asyncio
import logging
import os
import traceback

from wxasync import WxAsyncApp
from logging_handlers.TimedPatternFileHandler import TimedPatternFileHandler

from similarweb_extract.DataFetcher import CachedDataFetcher
from similarweb_extract.functions import execute, get_config_path
from similarweb_extract.ProgressBar import TerminalProgressBar
from similarweb_extract.gui import ErrorDialog, MainWindow

logger = logging.getLogger('logger')
formatter = logging.Formatter(
    fmt='%(asctime)s %(levelname)-8s %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S')
logs_folder = os.path.join(get_config_path(), 'logs')
if not os.path.exists(logs_folder):
    os.makedirs(logs_folder)
fh = TimedPatternFileHandler(os.path.join(
    logs_folder, 'debug-%d%m%y.log'), when='MIDNIGHT', backupCount=20)
fh.setFormatter(formatter)
logger.addHandler(fh)
logger.setLevel(logging.INFO)


parser = argparse.ArgumentParser(
    description='Retrieve info from the SimilarWeb API'
    )
# parser.add_argument('file', help='path to the input csv file')
parser.add_argument('-c', '--commandline', action='store_true',
                    help='Disable UI (get data from config file)'
                    )
parser.add_argument('-r', '--rate', type=int, default=9,
                    help='max number of simultaneous http requests (default = 9)'
                    )
parser.add_argument('-n', '--nocache', action='store_true',
                    help='Disable caching of successful responses from the API'
                    )
parser.add_argument('-v', '--verbose', action='store_true', help='verbose mode')

args = parser.parse_args()

if args.verbose:
    logger.setLevel(logging.DEBUG)


async def main() -> None:
    fetcher = CachedDataFetcher()
    await fetcher.set_rate(args.rate)
    db_path = None if args.nocache else os.path.join(
        get_config_path(), 'apicache.sqlite')
    fetcher.set_db_path(db_path)

    if args.commandline:
        logger.info('Starting headless run')
        pbar = TerminalProgressBar()

        await execute(pbar)

        logger.info('Job done!')

    else:
        app = WxAsyncApp()
        frm = MainWindow()
        frm.Show()

        try:
            await app.MainLoop()
        except Exception as e:
            exc_info = traceback.format_exc()
            logger.exception(exc_info)
            ErrorDialog(None, 'Similarweb Extract - Error', exc_info)
            raise e

if __name__ == "__main__":
    main_fetcher = CachedDataFetcher()
    loop = asyncio.events.get_event_loop()

    try:
        loop.run_until_complete(main())

    finally:
        loop.call_soon(main_fetcher.close())
