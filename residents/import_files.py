"""Reading uploaded student files (CSV or Excel) and photo zips. No database in here."""
import csv
import io
import os
import re
import zipfile
from dataclasses import dataclass, field

MAX_FILE_BYTES = 5 * 1024 * 1024
MAX_ROWS = 5000
MAX_ZIP_MEMBERS = 6000
MAX_ZIP_TOTAL_BYTES = 500 * 1024 * 1024
MAX_PHOTO_BYTES = 8 * 1024 * 1024
PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

COLUMNS = [
    "roll_number", "name", "gender", "category", "diet", "religion", "course", "department",
    "country", "state", "guardian_name", "guardian_phone", "hostel", "room", "photo",
]
REQUIRED = ["roll_number", "name", "gender", "category", "diet"]

# Other spellings of each column that are accepted in the header row.
ALIASES = {
    "roll_number": {"roll_number", "roll_no", "roll", "rollno", "roll_num", "registration_number",
                    "registration_no", "reg_no", "student_id", "id"},
    "name": {"name", "student_name", "full_name", "student"},
    "gender": {"gender", "sex"},
    "category": {"category", "student_category"},
    "diet": {"diet", "diet_type", "food_preference", "food"},
    "religion": {"religion"},
    "course": {"course", "program", "programme"},
    "department": {"department", "dept", "faculty"},
    "country": {"country", "nationality"},
    "state": {"state", "province", "region"},
    "guardian_name": {"guardian_name", "guardian", "parent_name", "parent", "father_name"},
    "guardian_phone": {"guardian_phone", "guardian_mobile", "guardian_contact", "parent_phone",
                       "parent_mobile", "phone", "mobile", "contact"},
    "hostel": {"hostel", "hostel_name", "block"},
    "room": {"room", "room_number", "room_no"},
    "photo": {"photo", "photo_file", "picture", "image"},
}
_ALIAS_TO_COLUMN = {alias: column for column, names in ALIASES.items() for alias in names}


class ImportFileError(Exception):
    """The uploaded file cannot be used at all (as opposed to a problem in one row)."""


@dataclass
class ParsedFile:
    rows: list  # [(spreadsheet row number, {column: text})]
    ignored_columns: list = field(default_factory=list)


def normalise_header(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).strip().lower()).strip("_")


def clean_cell(value):
    """Text for a cell. Excel hands numbers over as floats, so 1234.0 becomes "1234"."""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return " ".join(str(value).split())


def normalise_gender(value):
    value = value.strip().lower()
    if value in {"m", "male", "boy", "man"}:
        return "male"
    if value in {"f", "female", "girl", "woman"}:
        return "female"
    return None


def _read_csv(path):
    with open(path, "rb") as handle:
        raw = handle.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")  # what Excel on Windows writes
    first_line = next((line for line in text.splitlines() if line.strip()), "")
    delimiter = max(",;\t", key=first_line.count) if first_line.count(",") + first_line.count(";") + first_line.count("\t") else ","
    return [row for row in csv.reader(io.StringIO(text), delimiter=delimiter)]


def _read_xlsx(path):
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except Exception:
        raise ImportFileError("This does not look like a valid Excel (.xlsx) file.")
    try:
        rows = []
        for row in workbook.worksheets[0].iter_rows(values_only=True):
            rows.append(list(row))
            if len(rows) > MAX_ROWS + 1:
                break
        return rows
    finally:
        workbook.close()


def read_table(path):
    """Read a .csv or .xlsx file into rows of {column: text}. Raises ImportFileError if unusable."""
    path = str(path)
    if os.path.getsize(path) > MAX_FILE_BYTES:
        raise ImportFileError("The file is larger than 5 MB.")
    extension = os.path.splitext(path)[1].lower()
    if extension == ".csv":
        raw_rows = _read_csv(path)
    elif extension == ".xlsx":
        raw_rows = _read_xlsx(path)
    else:
        raise ImportFileError("Use a .csv or .xlsx file (in Excel: Save As, then CSV or Excel Workbook).")
    return _parse(raw_rows)


def _parse(raw_rows):
    raw_rows = [row for row in raw_rows if row is not None]
    if not raw_rows:
        raise ImportFileError("The file is empty.")
    mapping, ignored = {}, []
    for index, cell in enumerate(raw_rows[0]):
        label = clean_cell(cell)
        if not label:
            continue
        column = _ALIAS_TO_COLUMN.get(normalise_header(label))
        if column is None or column in mapping.values():
            ignored.append(label)
        else:
            mapping[index] = column
    missing = [column for column in REQUIRED if column not in mapping.values()]
    if missing:
        found = ", ".join(clean_cell(c) for c in raw_rows[0] if clean_cell(c)) or "none"
        raise ImportFileError(f"Missing column(s): {', '.join(missing)}. The file has: {found}.")

    rows = []
    for number, raw in enumerate(raw_rows[1:], start=2):
        values = {column: clean_cell(raw[i]) if i < len(raw) else "" for i, column in mapping.items()}
        if any(values.values()):
            rows.append((number, values))
    if len(rows) > MAX_ROWS:
        raise ImportFileError(f"The file has more than {MAX_ROWS} students. Split it into smaller files.")
    if not rows:
        raise ImportFileError("The file has a header row but no students.")
    return ParsedFile(rows, ignored)


# ---------- photo zip ----------

@dataclass
class PhotoIndex:
    by_stem: dict = field(default_factory=dict)  # "ku260001" -> member name in the zip
    by_name: dict = field(default_factory=dict)  # "ku260001.jpg" -> member name in the zip
    problems: list = field(default_factory=list)

    def find(self, roll_number, photo_column=""):
        """The zip member for a student: by the photo column if given, else by roll number."""
        if photo_column:
            return self.by_name.get(os.path.basename(photo_column).lower())
        return self.by_stem.get(roll_number.lower())


def index_photos(zip_path):
    """List the usable photos in a zip. Only file names are used, never folders or paths."""
    index = PhotoIndex()
    try:
        archive = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise ImportFileError("The photo file is not a valid zip archive.")
    with archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        if len(infos) > MAX_ZIP_MEMBERS:
            raise ImportFileError(f"The photo zip has more than {MAX_ZIP_MEMBERS} files.")
        if sum(i.file_size for i in infos) > MAX_ZIP_TOTAL_BYTES:
            raise ImportFileError("The photo zip is too large when unpacked.")
        for info in infos:
            base = os.path.basename(info.filename.replace("\\", "/"))
            stem, extension = os.path.splitext(base)
            if not base or base.startswith(".") or info.filename.startswith("__MACOSX/"):
                continue
            if extension.lower() not in PHOTO_EXTENSIONS:
                index.problems.append(f"{base}: not a .jpg, .png or .webp picture, ignored.")
                continue
            if info.file_size > MAX_PHOTO_BYTES:
                index.problems.append(f"{base}: larger than 8 MB, ignored.")
                continue
            if stem.lower() in index.by_stem:
                index.problems.append(f"{base}: another picture already uses this name, ignored.")
                continue
            index.by_stem[stem.strip().lower()] = info.filename
            index.by_name[base.lower()] = info.filename
    return index


def read_photo(zip_path, member):
    with zipfile.ZipFile(zip_path) as archive:
        return archive.read(member)
