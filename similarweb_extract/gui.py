import asyncio
import logging
import os
import sys
import textwrap
from typing import Iterable, List, Tuple

import pyperclip3
import wx
from wx.adv import BannerWindow
from wxasync import AsyncBind, StartCoroutine

from .DataFetcher import CachedDataFetcher
from .functions import execute, hits_per_domain, parse_config
from .ProgressBar import UserAbortException, WxPythonProgressBar
from .helpers import decode_country, get_config_path, load_domains_list, mask, months_between
from .enums import OutputFormats

logger = logging.getLogger('logger')

WINDOW_WIDTH = 800
WINDOW_HEIGHT = 600
BANNER_HEIGHT = 320

MONTHS_NUMBERS = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06', 'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}


def encode_month(month: str, year: str) -> str:
    result = ''
    if year != '' and month != '':
        result = f'{year}-{MONTHS_NUMBERS[month]}'

    return result

def decode_month(date: str) -> Tuple[str, str]:
    result = ('', '')
    if '-' in date:
        month_name = ''
        year, month_num = date.split('-')[:2]
        for key, val in MONTHS_NUMBERS.items():
            if val == month_num:
                month_name = key
                break

        result = (month_name, year)

    return result

def set_combobox_choices(combobox: wx.ComboBox, choices: Iterable[str]):
    combobox.Clear()
    for choice in choices:
        combobox.Append(str(choice))

class MainWindow(wx.Frame):
    def __init__(self):
        super().__init__(parent=None, title='Similarweb Extract Data',
                         size=wx.Size(WINDOW_WIDTH, WINDOW_HEIGHT))
        sizer = wx.BoxSizer(wx.VERTICAL)
        self.main_window = wx.Panel(self)
        sizer.Add(self.main_window, 1, wx.EXPAND)

        self.available_countries_desktop = {}
        self.available_countries_mobile_set = {}
        self.available_months = []
        self.domains = []
        self.countries = []

        self.fetcher = CachedDataFetcher()

        self.config = parse_config()
        self.capabilities = {}
        self.domains_path = self.config['Paths']['domains_path']
        self.remaining_hits = 0

        self.status_bar = self.CreateStatusBar(2)
        self.status_bar.SetStatusWidths([-1, 300])

        self.add_widgets()
        self.set_menu_bar()

        if self.config.get('API', 'api_key') == '':
            self.configure_options()
        else:
            StartCoroutine(self.update_capabilities(), self)

        logger.info('Loaded Main Window')
        self.Show()

    def add_widgets_row_to_sizer(self, sizer: wx.Sizer, label: str, controls: List[wx.Control], expand: bool = False, label_width: int = 130):
        sizer_row = wx.BoxSizer(wx.HORIZONTAL)
        label_control = wx.StaticText(self.main_window, label=label, size=wx.Size(label_width, 20))
        sizer_row.Add(label_control, 0, wx.TOP | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 5)
        for control in controls:
            sizer_row.Add(control, 1, wx.TOP | wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 5)

        if expand:
            sizer.Add(sizer_row, 0, wx.EXPAND)
        else:
            sizer.Add(sizer_row, 0, wx.ALIGN_LEFT)

        return sizer_row

    def add_widgets(self):
        window_sizer = wx.BoxSizer(wx.HORIZONTAL)

        # Banner image
        banner = BannerWindow(self, wx.TOP)
        workdir = os.getcwd()
        if getattr(sys, 'frozen', False):
            workdir = sys._MEIPASS # pylint: disable=no-member, protected-access


        banner_path = os.path.join(workdir, 'resources', 'similarweb-banner.jpg')
        img = wx.Image(banner_path, type=wx.BITMAP_TYPE_JPEG)
        width, height = img.GetSize().Get()
        ratio = width/height
        img = img.Scale(BANNER_HEIGHT * ratio, BANNER_HEIGHT, wx.IMAGE_QUALITY_HIGH)
        bmp = wx.Bitmap(img)
        banner.SetBitmap(bmp)
        window_sizer.Add(banner, proportion=0, flag=wx.ALIGN_LEFT | wx.ALIGN_BOTTOM |
                         wx.LEFT | wx.BOTTOM | wx.TOP, border=25)

        # Main self
        main_sizer = wx.BoxSizer(wx.VERTICAL)
        window_sizer.Add(main_sizer, proportion=1, flag=wx.ALIGN_LEFT | wx.EXPAND | wx.ALL, border=25)

        # API Parameters
        params_sizer = wx.StaticBoxSizer(wx.VERTICAL, self.main_window, 'Select Parameters')

        # Params - Domains
        btn_load_file = wx.Button(self.main_window, label='Load Domains File')
        AsyncBind(wx.EVT_BUTTON, self._on_load_file, btn_load_file)
        self.domains_path = self.config['Paths']['domains_path']
        self.domains_path_label = wx.StaticText(
            self.main_window, style=wx.ST_ELLIPSIZE_START)

        self.add_widgets_row_to_sizer(params_sizer, 'Domains List', [btn_load_file])
        self.add_widgets_row_to_sizer(params_sizer, '', [self.domains_path_label])

        # Params - Countries
        btn_select_countries = wx.Button(self.main_window, label='Choose Countries')
        btn_select_countries.Bind(wx.EVT_BUTTON, self._on_select_countries)
        self.selected_countries = wx.StaticText(self.main_window, label='')
        self.countries_error = wx.StaticText(self.main_window)
        self.countries_error.SetForegroundColour((219, 9, 27))

        self.add_widgets_row_to_sizer(params_sizer, 'Countries', [btn_select_countries])
        self.add_widgets_row_to_sizer(params_sizer, '', [self.selected_countries])
        self.add_widgets_row_to_sizer(params_sizer, '', [self.countries_error])

        # Time Period Selection
        self.time_period_select = wx.RadioBox(self.main_window, choices=['Select Dates', 'Recent Months'])
        self.time_period_select.Bind(wx.EVT_RADIOBOX, self._on_field_change)
        self.add_widgets_row_to_sizer(params_sizer, 'Time Period', [self.time_period_select])

        # Params - Start Date
        self.start_month = wx.ComboBox(
            self.main_window, -1, choices=list(MONTHS_NUMBERS.keys()), style=wx.CB_READONLY)
        self.start_month.Bind(wx.EVT_COMBOBOX, self._on_field_change)
        self.start_year = wx.ComboBox(
            self.main_window, -1, style=wx.CB_READONLY)
        self.start_year.Bind(wx.EVT_COMBOBOX, self._on_field_change)

        self.start_date_error = wx.StaticText(self.main_window)
        self.start_date_error.SetForegroundColour((219, 9, 27))

        self.start_date_row = self.add_widgets_row_to_sizer(params_sizer, 'Start Month', [self.start_month, self.start_year, self.start_date_error])

        # Params - End Date
        self.end_month = wx.ComboBox(
            self.main_window, -1, choices=list(MONTHS_NUMBERS.keys()), style=wx.CB_READONLY)
        self.end_month.Bind(wx.EVT_COMBOBOX, self._on_field_change)
        self.end_year = wx.ComboBox(self.main_window, -1, style=wx.CB_READONLY)
        self.end_year.Bind(wx.EVT_COMBOBOX, self._on_field_change)

        self.end_date_error = wx.StaticText(self.main_window)
        self.end_date_error.SetForegroundColour((219, 9, 27))
        self.end_date_row = self.add_widgets_row_to_sizer(params_sizer, 'End Month', [self.end_month, self.end_year, self.end_date_error])

        # Nb Months Select
        self.nb_months_select = wx.ComboBox(self.main_window, -1, style=wx.CB_READONLY)
        self.nb_months_select.Bind(wx.EVT_COMBOBOX, self._on_field_change)
        self.nb_months_error = wx.StaticText(self.main_window)
        self.nb_months_error.SetForegroundColour((219, 9, 27))
        self.nb_months_row = self.add_widgets_row_to_sizer(params_sizer, 'Select # of Months', [self.nb_months_select, self.nb_months_error])


        main_sizer.Add(params_sizer, 0, wx.EXPAND | wx.BOTTOM, 15)

        execute_btn = wx.Button(
            self.main_window, label='Extract Data', size=wx.Size(100, 24))
        AsyncBind(wx.EVT_BUTTON, self._on_press, execute_btn)
        main_sizer.Add(execute_btn, 0, wx.ALL | wx.CENTER, 25)

        self.SetSizerAndFit(window_sizer)

    async def update_capabilities(self):
        api_key = self.config['API']['api_key']

        data_account = await self.fetcher.fetch(f'https://api.similarweb.com/capabilities?api_key={api_key}', skip_cache=True)
        self.capabilities = data_account

        if data_account is not None:
            logger.debug('Successfully retrieved capabilities for key %s', mask(api_key))
            countries_desktop = data_account.get('web_desktop_data', {}).get('countries', [])
            country_codes_desktop = [c.get('code').lower() for c in countries_desktop]
            self.available_countries_desktop = {decode_country(c): c for c in country_codes_desktop}

            countries_mobile = data_account.get('web_mobile_data', {}).get('countries', [])
            country_codes_mobile = [c.get('code').lower() for c in countries_mobile]
            self.available_countries_mobile_set = {c for c in country_codes_mobile}

            interval = data_account.get('web_desktop_data', {}).get('snapshot_interval', {})
            self.available_months = months_between(interval.get('start_date'), interval.get('end_date'))

            available_years = list({m.split('-')[0] for m in self.available_months})
            set_combobox_choices(self.start_year, available_years)
            set_combobox_choices(self.end_year, available_years)
            set_combobox_choices(self.nb_months_select, range(1, len(self.available_months) + 1))

        else:
            logger.error('Could not load capabilities for API key %s', mask(api_key))

        remaining_hits_account = 0
        if data_account is not None:
            remaining_hits_account = data_account.get('remaining_hits') or 0
        data_user = await self.fetcher.fetch(f'https://api.similarweb.com/user-capabilities?api_key={api_key}', skip_cache=True)
        if data_user is not None:
            self.remaining_hits = data_user.get('user_remaining') or remaining_hits_account
        else:
            self.remaining_hits = 'Invalid API key!'

        await self.initialize_form()
        self._validate_form()
        self._save_config()

    async def initialize_form(self):
        self.countries = [country_code.lower().strip() for country_code
                          in self.config.get('API', 'countries').split(',')]
        countries_names = '; '.join([decode_country(country_code) for country_code
                                     in self.countries])
        self.selected_countries.SetLabel(countries_names)
        time_period_type = self.config.get('API', 'time_period_type')
        if time_period_type is not None and time_period_type != '':
            self.time_period_select.SetSelection(int(time_period_type))
        else:
            self.time_period_select.SetSelection(1)

        sm, sy = decode_month(self.config.get('API', 'start_date'))
        self.start_month.SetValue(sm)
        self.start_year.SetValue(sy)

        em, ey = decode_month(self.config.get('API', 'end_date'))
        self.end_month.SetValue(em)
        self.end_year.SetValue(ey)

        self.nb_months_select.SetValue(self.config.get('API', 'nb_months'))

        self._load_file_info()
        self._refresh_hits_count()

    def set_menu_bar(self):
        menu_bar = wx.MenuBar()
        file_menu = wx.Menu()
        quit_item = file_menu.Append(wx.ID_EXIT, '&Quit', 'Quit Application')
        self.Bind(wx.EVT_MENU, self._on_quit, quit_item)

        # settings_menu = wx.Menu()
        configure_options_item = file_menu.Append(
            wx.ID_ANY, '&Settings', 'Configure the options for this app')
        self.Bind(wx.EVT_MENU, self.configure_options, configure_options_item)

        menu_bar.Append(file_menu, '&File')
        self.SetMenuBar(menu_bar)

    def _load_file_info(self):
        self.domains_path_label.SetLabel(self.domains_path)
        self.domains = load_domains_list(self.domains_path)
        self._refresh_hits_count()

    def _save_config(self):
        self.config.set('Paths', 'domains_path', self.domains_path)

        self.config.set('API', 'countries', ','.join(self.countries))

        self.config.set('API', 'time_period_type', str(self.time_period_select.GetSelection()))
        self.config.set('API', 'start_date', encode_month(self.start_month.GetValue(), self.start_year.GetValue()))
        self.config.set('API', 'end_date', encode_month(self.end_month.GetValue(), self.end_year.GetValue()))
        self.config.set('API', 'nb_months', str(self.nb_months_select.GetSelection() + 1))

        config_file = os.path.join(get_config_path(), 'config.ini')
        with open(config_file, 'w') as configfile:
            self.config.write(configfile)

        logger.debug('Config Saved in %s', config_file)

    async def _on_load_file(self, _):
        with wx.FileDialog(self, 'Open', '', '', 'CSV files (*.csv)|*.csv',
                           wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as file_dialog:
            if file_dialog.ShowModal() == wx.ID_CANCEL:
                return

            self.domains_path = file_dialog.GetPath()
            self._save_config()
            self._load_file_info()

    def _refresh_hits_count(self, _=None):
        hpd = hits_per_domain(self.config)
        self.status_bar.SetStatusText(
            f'Consumption: {len(self.domains) * hpd:,} API hits per run ({len(self.domains):,} domains - {len(self.countries)} countries)')
        api_key = self.config.get("API", "api_key")
        if api_key is None or api_key == '':
            self.status_bar.SetStatusText('Please enter an API key!', 1)
        elif isinstance(self.remaining_hits, str):
            self.status_bar.SetStatusText(
                f'API Key: ********{api_key[-6:]} ({self.remaining_hits})', 1)
        else:
            self.status_bar.SetStatusText(
                f'API Key: ********{api_key[-6:]} ({self.remaining_hits:,} hits remaining)', 1)

    def configure_options(self, _=None):
        defaults = {
            'api_key': self.config.get('API', 'api_key'),
            'is_custom_folder': self.config.getboolean('Output', 'is_custom'),
            'output_folder': self.config.get('Output', 'folder'),
            'output_format': self.config.get('Output', 'format'),
        }

        with ParametersDialog(defaults) as dlg:
            ans = dlg.ShowModal()
            if ans == wx.ID_OK:
                api_key = dlg.apiKeyText.GetValue().strip()
                self.config.set('API', 'api_key', api_key)

                output_format = dlg.formats[dlg.outputFormat.GetSelection()]
                if output_format == OutputFormats.XLSX.value:
                    self.config.set('Output', 'format', 'xlsx')
                elif output_format == OutputFormats.CSV.value:
                    self.config.set('Output', 'format', 'csv')
                else:
                    self.config.set('Output', 'format', 'csv')

                is_custom_folder = dlg.values.get('is_custom_folder')
                self.config.set('Output', 'is_custom', 'yes' if is_custom_folder else 'no')
                output_folder = dlg.values.get('output_folder')
                self.config.set('Output', 'folder', output_folder)

                StartCoroutine(self.update_capabilities(), self)

    def _on_select_countries(self, _):
        countries = sorted(list(self.available_countries_desktop.keys()))
        with wx.MultiChoiceDialog(self,
                                   'Choose the countries you want to retrieve data for',
                                   'Select Countries',
                                   countries) as dialog:

            selections = [i for i, country in enumerate(countries) if self.available_countries_desktop.get(country) in self.countries]
            dialog.SetSelections(selections)

            if (dialog.ShowModal() == wx.ID_OK):
                selections = dialog.GetSelections()
                country_names = [countries[x] for x in selections]

                self.countries = [self.available_countries_desktop.get(country_name) for country_name in country_names]
                countries_names = '; '.join([decode_country(country_code) for country_code in self.countries])
                self.selected_countries.SetLabel(countries_names)

                self._on_field_change()


    async def _on_press(self, e):
        pbar = WxPythonProgressBar(self)
        try:
            await execute(pbar, mode='ui')
            self.status_bar.SetStatusText('Job done!')

        except UserAbortException as uae:
            logger.info('Execution interrupted: %s', uae)
            pbar.__exit__(None, None, None)
            self.status_bar.SetStatusText('Request Cancelled!')

        finally:
            await asyncio.sleep(2)
            await self.update_capabilities()

        logger.debug('Data Processing complete!')
        e.Skip()

    def _on_quit(self, e):
        self.Close()
        e.Skip()

    def OnClose(self, e):
        logger.debug('Closed Main Window')
        self.Destroy()
        e.Skip()

    def _validate_form(self):
        self.start_date_row.ShowItems(show=False)
        self.end_date_row.ShowItems(show=False)
        self.nb_months_row.ShowItems(show=False)

        time_period_type = self.time_period_select.GetSelection()
        if time_period_type == 0:  # choose start/end dates
            self.start_date_row.ShowItems(show=True)
            self.end_date_row.ShowItems(show=True)

        elif time_period_type == 1:  # recent months
            self.nb_months_row.ShowItems(show=True)
            # self.date_range_row.ShowItems(show=True)

        start_date = encode_month(self.start_month.GetValue(), self.start_year.GetValue())
        end_date = encode_month(self.end_month.GetValue(), self.end_year.GetValue())

        # Dates Errors
        if len(self.available_months) > 0:
            if start_date < self.available_months[0]:
                self.start_date_error.SetLabel(f'Invalid - must be >= {self.available_months[0]}')
            elif start_date > self.available_months[-1]:
                self.start_date_error.SetLabel(f'Invalid - must be <= {self.available_months[-1]}')
            else:
                self.start_date_error.SetLabel('')

            if end_date < self.available_months[0]:
                self.end_date_error.SetLabel(f'Invalid - must be >= {self.available_months[0]}')
            elif end_date > self.available_months[-1]:
                self.end_date_error.SetLabel(f'Invalid - must be <= {self.available_months[-1]}')
            else:
                self.end_date_error.SetLabel('')
        else:
            self.start_date_error.SetLabel('')
            self.end_date_error.SetLabel('')

        # Countries errors
        countries_no_mobile = [decode_country(c) for c in self.countries if c not in self.available_countries_mobile_set]
        countries_selection = [c for c in self.countries if c != '']
        if len(countries_selection) == 0:
            self.countries_error.SetLabel('No country selected!')
        elif len(countries_no_mobile) > 0:
            self.countries_error.SetLabel(f'Warning: no Mobile Web data for {", ".join(countries_no_mobile)}')
        else:
            self.countries_error.SetLabel('')

        # By default, enable fields that are subject to be disabled
        # self.lbl_start_date.Enable()
        self.start_month.Enable()
        self.start_year.Enable()
        # self.lbl_end_date.Enable()
        self.end_month.Enable()
        self.end_year.Enable()

        self.Layout()

    def _on_field_change(self, _=None):
        self._validate_form()
        self._save_config()
        self._refresh_hits_count()

class ParametersDialog(wx.Dialog):
    """"""

    # ----------------------------------------------------------------------
    def __init__(self, defaults: dict):
        """Constructor"""
        wx.Dialog.__init__(self, None, title='App Settings')
        self.values = defaults
        self.labels_widths = 120

        paddingSizer = wx.BoxSizer(wx.VERTICAL)
        self.mainSizer = wx.BoxSizer(wx.VERTICAL)
        btnSizer = wx.BoxSizer(wx.HORIZONTAL)

        self.mainSizer.Add(wx.StaticText(
            self, label='You can find your API key here:'))
        self.mainSizer.Add(wx.adv.HyperlinkCtrl(
            self, url='https://account.similarweb.com/#/api-management'))
        self.mainSizer.AddSpacer(25)

        apiKeyLbl = wx.StaticText(
            self, label='API Key *', size=wx.Size(self.labels_widths, 20))
        self.apiKeyText = wx.TextCtrl(self, style=wx.TE_PASSWORD)
        self.apiKeyText.SetValue(self.values.get('api_key'))
        self.addWidget(apiKeyLbl, self.apiKeyText)

        output_type_box = wx.BoxSizer(wx.HORIZONTAL)
        lbl_output_type = wx.StaticText(self, label='Destination Folder', size=wx.Size(self.labels_widths, 20))
        self.output_type = wx.RadioBox(self, choices=['Same as domains list', 'Custom folder'])
        self.output_type.SetSelection(0)

        self.btn_load_file = wx.Button(self, label='Choose Folder')
        self.Bind(wx.EVT_BUTTON, self._on_choose_ouput_folder, self.btn_load_file)

        output_type_box.Add(self.output_type, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        output_type_box.Add(self.btn_load_file, 0, wx.ALIGN_CENTER_VERTICAL, 0)
        self.output_type.Bind(wx.EVT_RADIOBOX, self._on_choose_output_type)
        self.addWidget(lbl_output_type, output_type_box)

        self.displayOutputFolder = wx.StaticText(self, style=wx.ST_ELLIPSIZE_START)

        self.btn_load_file.Disable()
        if self.values.get('is_custom_folder'):
            self.output_type.SetSelection(1)
            self.btn_load_file.Enable()
            self.displayOutputFolder.SetLabel(self.values.get('output_folder', ''))

        self.addWidget(wx.StaticText(self, size=wx.Size(self.labels_widths, 20)), self.displayOutputFolder)

        outputFormatLbl = wx.StaticText(
            self, label='Output File Format', size=wx.Size(self.labels_widths, 20))
        self.formats = [format.value for format in OutputFormats]
        self.outputFormat = wx.ComboBox(
            self, choices=self.formats, style=wx.CB_READONLY)
        default_format = self.values.get('output_format', 'csv')

        for i, fmt in enumerate(self.formats):
            if f'.{default_format}' in fmt:
                self.outputFormat.SetSelection(i)
                break

        self.addWidget(outputFormatLbl, self.outputFormat)
        self.mainSizer.AddSpacer(25)

        self.okBtn = wx.Button(self, wx.ID_OK)
        btnSizer.Add(self.okBtn, 0, wx.CENTER | wx.ALL, 5)
        if self.values.get('is_custom_folder') and self.values.get('output_folder', '') == '':
            self.okBtn.Disable()
            self.displayOutputFolder.SetLabel('Please select a destination folder!')
            self.displayOutputFolder.SetForegroundColour((219, 9, 27))

        cancelBtn = wx.Button(self, wx.ID_CANCEL)
        btnSizer.Add(cancelBtn, 0, wx.CENTER | wx.ALL, 5)

        self.mainSizer.Add(btnSizer, 0, wx.CENTER)

        paddingSizer.Add(self.mainSizer, 1, wx.ALL, 20)
        self.SetSizerAndFit(paddingSizer)

    # ----------------------------------------------------------------------
    def addWidget(self, lbl: str, txt: wx.Control):
        """
        """
        sizer = wx.BoxSizer(wx.HORIZONTAL)
        sizer.Add(lbl, 0, wx.TOP | wx.RIGHT | wx.ALIGN_CENTER_VERTICAL, 10)
        sizer.Add(txt, 1, wx.TOP | wx.LEFT | wx.ALIGN_CENTER_VERTICAL, 10)
        self.mainSizer.Add(sizer, 0, wx.EXPAND)

    def _on_choose_output_type(self, _):
        if self.output_type.GetSelection() == 1:
            self.values['is_custom_folder'] = True
            self.btn_load_file.Enable()
        else:
            self.values['is_custom_folder'] = False
            self.btn_load_file.Disable()

        self._update_output_folder_label()

    def _on_choose_ouput_folder(self, _):
        with wx.DirDialog(None, "Choose a Destination Folder", style=wx.DD_DEFAULT_STYLE | wx.DD_NEW_DIR_BUTTON) as dialog:
            if dialog.ShowModal() == wx.ID_OK:
                self.values['output_folder'] = dialog.GetPath()
                self._update_output_folder_label()

    def _update_output_folder_label(self):
        output_folder = ''
        color = wx.SystemSettings.GetColour(wx.SYS_COLOUR_WINDOWTEXT)
        self.displayOutputFolder.SetForegroundColour(color)
        self.okBtn.Enable()
        if self.values.get('is_custom_folder'):
            output_folder = self.values.get('output_folder', '')
            if self.values.get('output_folder', '') == '':
                self.okBtn.Disable()
                output_folder = 'Please select a destination folder!'
                self.displayOutputFolder.SetForegroundColour((219, 9, 27))

        self.displayOutputFolder.SetLabel(output_folder)

class ErrorDialog(wx.Dialog):
    def __init__(self, parent, title, stacktrace):
        wx.Dialog.__init__(self, parent, title=title)
        self.stacktrace = stacktrace

        sizer = wx.BoxSizer(wx.VERTICAL)
        # text = wx.StaticText(self, label='An unexpected error occurred.\nPlease Copy the text below and send it to the developer.')
        # sizer.Add(text, flag=wx.ALIGN_LEFT | wx.LEFT | wx.BOTTOM | wx.TOP, border=15)

        # Create the top row, containing the error icon and text message.
        top_row_sizer = wx.BoxSizer(wx.HORIZONTAL)

        error_bitmap = wx.ArtProvider.GetBitmap(
            wx.ART_ERROR, wx.ART_MESSAGE_BOX
        )
        error_bitmap_ctrl = wx.StaticBitmap(self, -1)
        error_bitmap_ctrl.SetBitmap(error_bitmap)

        message_text = textwrap.dedent("""\
            Oops! An unhandled error occurred. Please send the
            contents of the text control below to the application's
            developer.\
        """)
        message_label = wx.StaticText(self, -1, message_text)

        top_row_sizer.Add(error_bitmap_ctrl, flag=wx.ALL, border=10)
        top_row_sizer.Add(message_label, flag=wx.ALIGN_CENTER_VERTICAL)
        sizer.Add(top_row_sizer, flag=wx.ALIGN_LEFT |
                  wx.LEFT | wx.BOTTOM | wx.TOP, border=15)

        self.copy_button = wx.Button(self, wx.ID_ANY, 'Copy to clipboard')
        self.copy_button.Bind(wx.EVT_BUTTON, self.copy_stacktrace)

        sizer.Add(self.copy_button, flag=wx.ALIGN_RIGHT |
                  wx.TOP | wx.RIGHT, border=15)
        sizer.Add((-1, 5))
        selectable_text = wx.TextCtrl(
            self, style=wx.TE_READONLY | wx.TE_MULTILINE, size=(400, 200))
        selectable_text.SetValue(self.stacktrace)
        sizer.Add(selectable_text, flag=wx.ALIGN_LEFT |
                  wx.LEFT | wx.RIGHT, border=15)
        sizer.Add(self.CreateButtonSizer(wx.OK), flag=wx.CENTER |
                  wx.TOP | wx.LEFT | wx.BOTTOM | wx.RIGHT, border=25)
        self.SetSizerAndFit(sizer)
        self.Centre()
        self.ShowModal()
        self.Destroy()

    def copy_stacktrace(self, _):
        pyperclip3.copy(self.stacktrace)
        self.copy_button.SetLabel('Copied!')
        self.copy_button.Disable()
