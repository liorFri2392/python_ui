import os
import time
from itertools import islice
from logging.handlers import BaseRotatingHandler, TimedRotatingFileHandler

# rotation intervals in seconds
_intervals = {
    "S": 1,
    "M": 60,
    "H": 60 * 60,
    "D": 60 * 60 * 24,
    "MIDNIGHT": 60 * 60 * 24,
    "W": 60 * 60 * 24 * 7,
}

class TimedPatternFileHandler(BaseRotatingHandler):
    """File handler that uses the current time in the log filename.

    The time is quantisized to a configured interval. See
    TimedRotatingFileHandler for the meaning of the when, interval, utc and
    atTime arguments.

    If backupCount is non-zero, then older filenames that match the base
    filename are deleted to only leave the backupCount most recent copies,
    whenever opening a new log file with a different name.

    """

    def __init__(
        self,
        filenamePattern,
        when="h",
        interval=1,
        backupCount=0,
        encoding=None,
        delay=False,
        utc=False,
        atTime=None,
    ):
        self.when = when.upper()
        self.backupCount = backupCount
        self.utc = utc
        self.atTime = atTime
        try:
            key = "W" if self.when.startswith("W") else self.when
            self.interval = _intervals[key]
        except KeyError:
            raise ValueError(
                f"Invalid rollover interval specified: {self.when}"
            ) from None
        if self.when.startswith("W"):
            if len(self.when) != 2:
                raise ValueError(
                    "You must specify a day for weekly rollover from 0 to 6 "
                    f"(0 is Monday): {self.when}"
                )
            if not "0" <= self.when[1] <= "6":
                raise ValueError(
                    f"Invalid day specified for weekly rollover: {self.when}"
                )
            self.dayOfWeek = int(self.when[1])

        self.interval = self.interval * interval
        self.pattern = os.path.abspath(os.fspath(filenamePattern))

        # determine best time to base our rollover times on
        # prefer the creation time of the most recently created log file.
        t = now = time.time()
        entry = next(self._matching_files(), None)
        if entry is not None:
            t = entry.stat().st_ctime
            while t + self.interval < now:
                t += self.interval

        self.rolloverAt = self.computeRollover(t)

        # delete older files on startup and not delaying
        if not delay and backupCount > 0:
            keep = backupCount
            if os.path.exists(self.baseFilename):
                keep += 1
                delete = islice(self._matching_files(), keep, None)
                for entry in delete:
                    os.remove(entry.path)

        # Will set self.baseFilename indirectly, and then may use
        # self.baseFilename to open. So by this point self.rolloverAt and
        # self.interval must be known.
        super().__init__(filenamePattern, "a", encoding, delay)

    @property
    def baseFilename(self):
        """Generate the 'current' filename to open"""
        # use the start of *this* interval, not the next
        t = self.rolloverAt - self.interval
        if self.utc:
            time_tuple = time.gmtime(t)
        else:
            time_tuple = time.localtime(t)
            dst = time.localtime(self.rolloverAt)[-1]
            if dst != time_tuple[-1] and self.interval > 3600:
                # DST switches between t and self.rolloverAt, adjust
                addend = 3600 if dst else -3600
                time_tuple = time.localtime(t + addend)
        return time.strftime(self.pattern, time_tuple)

    @baseFilename.setter
    def baseFilename(self, _):
        # assigned to by FileHandler, just ignore this as we use self.pattern
        # instead
        pass

    def _matching_files(self):
        """Generate DirEntry entries that match the filename pattern.

        The files are ordered by their last modification time, most recent
        files first.

        """
        matches = []
        pattern = self.pattern
        for entry in os.scandir(os.path.dirname(pattern)):
            if not entry.is_file():
                continue
            try:
                time.strptime(entry.path, pattern)
                matches.append(entry)
            except ValueError:
                continue
        matches.sort(key=lambda e: e.stat().st_mtime, reverse=True)
        return iter(matches)

    def doRollover(self):
        """Do a roll-over. This basically needs to open a new generated filename.
        """
        if self.stream:
            self.stream.close()
            self.stream = None

        if self.backupCount > 0:
            delete = islice(self._matching_files(), self.backupCount, None)
            for entry in delete:
                os.remove(entry.path)

        now = int(time.time())
        rollover = self.computeRollover(now)
        while rollover <= now:
            rollover += self.interval
        if not self.utc:
            # If DST changes and midnight or weekly rollover, adjust for this.
            if self.when == "MIDNIGHT" or self.when.startswith("W"):
                dst = time.localtime(now)[-1]
                if dst != time.localtime(rollover)[-1]:
                    rollover += 3600 if dst else -3600
        self.rolloverAt = rollover

        if not self.delay:
            self.stream = self._open()

    # borrow *some* TimedRotatingFileHandler methods
    computeRollover = TimedRotatingFileHandler.computeRollover
    shouldRollover = TimedRotatingFileHandler.shouldRollover
