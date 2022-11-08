from enum import Enum

class DevicesModes(Enum):
    TOTAL = 'Desktop & Mobile Web (aggregated)'
    DESKTOP = 'Desktop Only'
    MOBILE = 'Mobile Web Only'
    BOTH = 'Desktop & Mobile Web (separated)'

class Granularities(Enum):
    MONTHLY = 'Monthly'
    DAILY = 'Daily'

class OutputFormats(Enum):
    CSV = 'Comma-Separated Values (.csv)'
    XLSX = 'Excel (.xlsx)'
