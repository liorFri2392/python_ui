from tqdm import tqdm
import wx

class UserAbortException(Exception):
    pass

class ProgressBar:
    max_value: int
    message: str

    def __init__(self, max_value: int = 100, message: str = None):
        self.max_value = max_value
        self.message = message

    def reset(self, max_value: int = 100, message: str = None):
        self.max_value = max_value
        self.message = message
        return self

    def set_max(self, max_value: int = 100):
        self.max_value = max_value
        return self

    def set_message(self, message: str = None):
        self.message = message
        return self

    def increment(self, incr: int = 1):
        return self

    def __enter__(self):
        pass

    def __exit__(self, exc_type, exc_value, traceback):
        pass


class TerminalProgressBar(ProgressBar):
    pbar: tqdm
    max_value: int
    message: str

    def __init__(self, max_value: int = 100, message: str = None):
        super().__init__(max_value, message)
        self.pbar = None

    def reset(self, max_value: int = 100, message: str = None):
        super().reset(max_value, message)
        if self.pbar is not None:
            self.pbar.n = 0
            self.pbar.max_value = max_value
            self.pbar.set_description(message)
            self.pbar.refresh()
        return self

    def set_max(self, max_value: int = 100):
        super().set_max(max_value)
        if self.pbar is not None:
            self.pbar.total = max_value
            self.pbar.refresh()
        return self

    def set_message(self, message: str = None):
        super().set_message(message)
        if self.pbar is not None:
            self.pbar.set_description(message)
        return self

    def increment(self, incr: int = 1):
        if self.pbar is not None:
            self.pbar.update(incr)
        return self

    def __enter__(self):
        self.pbar = tqdm(total=self.max_value, desc=self.message)

    def __exit__(self, exc_type, exc_value, traceback):
        self.pbar.close()
        self.pbar = None


class WxPythonProgressBar(ProgressBar):
    wxApp: wx.Frame
    pbar: wx.ProgressDialog

    def __init__(self, wxApp: wx.Frame, max_value: int = 100, message: str = None):
        super().__init__(max_value, message)
        self.wxApp = wxApp
        self.pbar = None

    def reset(self, max_value: int = 100, message: str = None):
        super().reset(max_value, message)
        if self.pbar is not None:
            self.pbar.SetRange(max_value)
            self.pbar.Update(0, message or 'Processing Data')

        return self

    def set_max(self, max_value: int = 100):
        super().set_max(max_value)
        if self.pbar is not None:
            self.pbar.SetRange(max_value)
        return self

    def set_message(self, message: str = None):
        super().set_message(message)
        if self.pbar is not None:
            self.pbar.Update(self.pbar.GetValue(), message or 'Processing Data')

        return self

    def increment(self, incr: int = 1):
        if self.pbar is not None:
            current_value = self.pbar.GetValue()
            new_value = current_value + incr
            cont, _ = self.pbar.Update(new_value)
            if not cont:
                raise UserAbortException('Request Cancelled by User')

        return self

    def __enter__(self):
        self.pbar = wx.ProgressDialog('Similarweb Data Extraction',
                                         self.message or 'Processing Data',
                                         maximum = self.max_value,
                                         parent = self.wxApp,
                                         style = wx.PD_APP_MODAL | wx.PD_ELAPSED_TIME | wx.PD_REMAINING_TIME | wx.PD_CAN_ABORT | wx.PD_AUTO_HIDE
                                     )


    def __exit__(self, exc_type, exc_value, traceback):
        if self.pbar is not None:
            self.pbar.Destroy()
            self.pbar = None
