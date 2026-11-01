"""Internal bounded input loading and shared format/configuration preparation."""

from __future__ import annotations

from os import PathLike
from pathlib import Path

from bankparser.detection import detect_format
from bankparser.errors import InputError, UnsupportedFormatError
from bankparser.options import CsvOptions
from bankparser.profiles import CsvProfile

MAX_INPUT_BYTES = 5 * 1024 * 1024


def load_input(source: str | PathLike[str] | bytes) -> tuple[bytes, str | None]:
    if isinstance(source, bytes):
        data = source
        file_name = None
    else:
        path = Path(source)
        try:
            size = path.stat().st_size
        except OSError as exc:
            raise InputError(f"Unable to read input file {path}: {exc}") from exc
        if size > MAX_INPUT_BYTES:
            raise InputError(
                f"Input is too large ({size} bytes); maximum is {MAX_INPUT_BYTES} bytes"
            )
        try:
            with path.open("rb") as source_file:
                data = source_file.read(MAX_INPUT_BYTES + 1)
        except OSError as exc:
            raise InputError(f"Unable to read input file {path}: {exc}") from exc
        file_name = path.name

    if not data:
        raise InputError("Input file is empty")
    if len(data) > MAX_INPUT_BYTES:
        raise InputError(
            f"Input is too large ({len(data)} bytes); maximum is {MAX_INPUT_BYTES} bytes"
        )
    return data, file_name


def csv_configuration(
    options: CsvOptions | None, profile: CsvProfile | None
) -> CsvOptions | None:
    if profile is not None:
        if not isinstance(profile, CsvProfile) or options is not None:
            raise InputError("Supply csv_profile or csv_options, not both")
        return profile.options
    if options is not None and not isinstance(options, CsvOptions):
        raise InputError("csv_options must be CsvOptions")
    return options


def input_format(
    data: bytes, *, csv_options: CsvOptions | None, format: str | None
) -> str:
    if format not in (None, "csv"):
        raise InputError("Only format='csv' is supported as an explicit override")
    try:
        detected = detect_format(data)
    except UnsupportedFormatError:
        if format == "csv" or csv_options is not None:
            return (
                "csv"  # The adapter must still validate header shape, rows and amounts.
            )
        raise
    if detected != "csv" and (csv_options is not None or format == "csv"):
        raise InputError(
            "csv_options/CSV format override can only be used with CSV input"
        )
    return detected
