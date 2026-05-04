from __future__ import annotations

import ctypes
import platform
from dataclasses import dataclass
from types import SimpleNamespace


DM_IN_BUFFER = 0x00000008
DM_IN_PROMPT = 0x00000004
DM_OUT_BUFFER = 0x00000002

DM_ORIENTATION = 0x00000001
DM_PAPERSIZE = 0x00000002
DM_PAPERLENGTH = 0x00000004
DM_PAPERWIDTH = 0x00000008
DM_COPIES = 0x00000100
DM_COLOR = 0x00000800

DMORIENT_PORTRAIT = 1
DMORIENT_LANDSCAPE = 2
DMCOLOR_MONOCHROME = 1
DMCOLOR_COLOR = 2

IDOK = 1
IDCANCEL = 2


class _DEVMODEW(ctypes.Structure):
    _fields_ = [
        ("dmDeviceName", ctypes.c_wchar * 32),
        ("dmSpecVersion", ctypes.c_ushort),
        ("dmDriverVersion", ctypes.c_ushort),
        ("dmSize", ctypes.c_ushort),
        ("dmDriverExtra", ctypes.c_ushort),
        ("dmFields", ctypes.c_uint32),
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short),
        ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short),
        ("dmPrintQuality", ctypes.c_short),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", ctypes.c_wchar * 32),
        ("dmLogPixels", ctypes.c_ushort),
        ("dmBitsPerPel", ctypes.c_uint32),
        ("dmPelsWidth", ctypes.c_uint32),
        ("dmPelsHeight", ctypes.c_uint32),
        ("dmDisplayFlags", ctypes.c_uint32),
        ("dmDisplayFrequency", ctypes.c_uint32),
        ("dmICMMethod", ctypes.c_uint32),
        ("dmICMIntent", ctypes.c_uint32),
        ("dmMediaType", ctypes.c_uint32),
        ("dmDitherType", ctypes.c_uint32),
        ("dmReserved1", ctypes.c_uint32),
        ("dmReserved2", ctypes.c_uint32),
        ("dmPanningWidth", ctypes.c_uint32),
        ("dmPanningHeight", ctypes.c_uint32),
    ]


@dataclass(frozen=True)
class NativePrinterDriverSettingsResult:
    printer_name: str
    devmode_bytes: bytes
    orientation: str | None = None
    paper_name: str | None = None
    paper_width_mm: float | None = None
    paper_height_mm: float | None = None
    copies: int | None = None
    color_mode: str | None = None


class WindowsPrinterDriverService:
    """Open the native Windows printer driver preferences dialog without printing."""

    def __init__(self):
        self._is_windows = platform.system().lower() == "windows"
        self._win32print = None
        if self._is_windows:
            try:
                import win32print  # type: ignore

                self._win32print = win32print
            except Exception:
                self._win32print = None

    def is_available(self) -> bool:
        return self._is_windows

    def open_driver_preferences(
        self,
        printer_name: str,
        parent_hwnd: int | None = None,
    ) -> NativePrinterDriverSettingsResult | None:
        if not self._is_windows:
            raise RuntimeError("Native printer driver preferences are only available on Windows.")
        if not printer_name:
            raise RuntimeError("No printer is selected.")

        hprinter = self._open_printer(printer_name)
        try:
            winspool = ctypes.WinDLL("winspool.drv")
            document_properties = winspool.DocumentPropertiesW
            document_properties.argtypes = [
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_wchar_p,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_uint32,
            ]
            document_properties.restype = ctypes.c_long

            size = document_properties(parent_hwnd or 0, hprinter, printer_name, None, None, 0)
            if size <= 0:
                raise RuntimeError("Could not query printer driver settings.")

            devmode_buffer = ctypes.create_string_buffer(size)
            preload = document_properties(
                parent_hwnd or 0,
                hprinter,
                printer_name,
                devmode_buffer,
                None,
                DM_OUT_BUFFER,
            )
            if preload < 0:
                raise RuntimeError("Could not read the current printer driver settings.")
            result = document_properties(
                parent_hwnd or 0,
                hprinter,
                printer_name,
                devmode_buffer,
                devmode_buffer,
                DM_IN_BUFFER | DM_OUT_BUFFER | DM_IN_PROMPT,
            )
            if result == IDCANCEL:
                return None
            if result < 0:
                raise RuntimeError("Printer driver preferences dialog failed.")

            devmode = ctypes.cast(devmode_buffer, ctypes.POINTER(_DEVMODEW)).contents
            return NativePrinterDriverSettingsResult(
                printer_name=printer_name,
                devmode_bytes=bytes(ctypes.string_at(devmode_buffer, size)),
                orientation=self._extract_orientation(devmode),
                paper_name=self._extract_paper_name(devmode),
                paper_width_mm=self._extract_paper_width_mm(devmode),
                paper_height_mm=self._extract_paper_height_mm(devmode),
                copies=self._extract_copies(devmode),
                color_mode=self._extract_color_mode(devmode),
            )
        finally:
            self._close_printer(hprinter)

    def build_qprinter(self, printer_name: str, settings) -> object:
        from PySide6.QtGui import QPageLayout, QPageSize
        from PySide6.QtCore import QSizeF
        from PySide6.QtPrintSupport import QPrinter

        printer = QPrinter()
        printer.setPrinterName(printer_name)

        if getattr(settings, "driver_copies", None):
            printer.setCopyCount(max(1, int(settings.driver_copies)))

        orientation = getattr(settings, "driver_orientation", None)
        if orientation == "landscape":
            printer.setPageOrientation(QPageLayout.Orientation.Landscape)
        elif orientation == "portrait":
            printer.setPageOrientation(QPageLayout.Orientation.Portrait)

        paper_width = getattr(settings, "driver_paper_width_mm", None)
        paper_height = getattr(settings, "driver_paper_height_mm", None)
        if paper_width and paper_height:
            page_size = QPageSize(
                QSizeF(float(paper_width), float(paper_height)),
                QPageSize.Unit.Millimeter,
                getattr(settings, "driver_paper_name", "") or "Driver Paper",
            )
            printer.setPageSize(page_size)

        color_mode = getattr(settings, "driver_color_mode", None)
        if color_mode == "grayscale":
            printer.setColorMode(QPrinter.ColorMode.GrayScale)
        elif color_mode == "color":
            printer.setColorMode(QPrinter.ColorMode.Color)

        return printer

    def build_qprinter_from_result(self, result: NativePrinterDriverSettingsResult):
        settings_view = SimpleNamespace(
            driver_orientation=result.orientation,
            driver_paper_name=result.paper_name,
            driver_paper_width_mm=result.paper_width_mm,
            driver_paper_height_mm=result.paper_height_mm,
            driver_copies=result.copies or 1,
            driver_color_mode=result.color_mode,
        )
        return self.build_qprinter(result.printer_name, settings_view)

    def _open_printer(self, printer_name: str):
        if self._win32print is not None:
            return self._win32print.OpenPrinter(printer_name)

        winspool = ctypes.WinDLL("winspool.drv")
        open_printer = winspool.OpenPrinterW
        open_printer.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p]
        open_printer.restype = ctypes.c_int

        handle = ctypes.c_void_p()
        success = open_printer(printer_name, ctypes.byref(handle), None)
        if not success:
            raise ctypes.WinError()
        return handle

    def _close_printer(self, hprinter):
        if self._win32print is not None:
            self._win32print.ClosePrinter(hprinter)
            return

        winspool = ctypes.WinDLL("winspool.drv")
        close_printer = winspool.ClosePrinter
        close_printer.argtypes = [ctypes.c_void_p]
        close_printer.restype = ctypes.c_int
        close_printer(hprinter)

    def _extract_orientation(self, devmode: _DEVMODEW) -> str | None:
        if not (devmode.dmFields & DM_ORIENTATION):
            return None
        if devmode.dmOrientation == DMORIENT_LANDSCAPE:
            return "landscape"
        if devmode.dmOrientation == DMORIENT_PORTRAIT:
            return "portrait"
        return None

    def _extract_paper_name(self, devmode: _DEVMODEW) -> str | None:
        form_name = (devmode.dmFormName or "").strip("\x00 ").strip()
        if form_name:
            return form_name
        if devmode.dmPaperSize > 0:
            return f"Paper #{int(devmode.dmPaperSize)}"
        return None

    def _extract_paper_width_mm(self, devmode: _DEVMODEW) -> float | None:
        if devmode.dmFields & DM_PAPERWIDTH and devmode.dmPaperWidth > 0:
            return float(devmode.dmPaperWidth) / 10.0
        return None

    def _extract_paper_height_mm(self, devmode: _DEVMODEW) -> float | None:
        if devmode.dmFields & DM_PAPERLENGTH and devmode.dmPaperLength > 0:
            return float(devmode.dmPaperLength) / 10.0
        return None

    def _extract_copies(self, devmode: _DEVMODEW) -> int | None:
        if devmode.dmFields & DM_COPIES and devmode.dmCopies > 0:
            return int(devmode.dmCopies)
        return None

    def _extract_color_mode(self, devmode: _DEVMODEW) -> str | None:
        if not (devmode.dmFields & DM_COLOR):
            return None
        if devmode.dmColor == DMCOLOR_MONOCHROME:
            return "grayscale"
        if devmode.dmColor == DMCOLOR_COLOR:
            return "color"
        return None
