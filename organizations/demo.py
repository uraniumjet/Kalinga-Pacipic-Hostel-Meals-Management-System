"""Synthetic demo data: an organisation set-up and realistic (but fictional) student files.

Nothing here is real. Names are made up from common first and last names, phone numbers are
deliberately invalid, and the pictures are coloured discs with initials.
"""
import csv
import io
import random
import zipfile
from pathlib import Path

ORG = {"name": "Demo University", "slug": "demo", "timezone": "Asia/Kolkata"}
CATEGORIES = ["International", "National"]
DIETS = ["Vegetarian", "Non-vegetarian"]
MEALS = [("Breakfast", 1, "07:30", "09:00"), ("Lunch", 2, "12:30", "14:00"), ("Dinner", 3, "19:30", "21:00")]
COUNTERS = [("International counter", ["International"]), ("National counter", ["National"])]
_CAPACITIES = [2, 4, 6, 4, 2, 4, 6, 4, 2, 4, 6, 4]
HOSTELS = {  # name -> (gender, [(room number, capacity)])
    "Boys Hostel A": ("male", [(str(101 + i), _CAPACITIES[i]) for i in range(12)]),
    "Girls Hostel B": ("female", [(str(201 + i), _CAPACITIES[i]) for i in range(10)]),
}

_NATIONAL = {
    "male": ["Aarav", "Rohit", "Amit", "Suresh", "Rakesh", "Manoj", "Sourav", "Debasish", "Pratyush", "Niraj", "Satyam", "Biswajit"],
    "female": ["Ananya", "Priya", "Sneha", "Pooja", "Ritu", "Subhashree", "Lipsa", "Sasmita", "Madhusmita", "Anjali", "Kavita", "Itishree"],
    "last": ["Sharma", "Das", "Mohanty", "Patra", "Nayak", "Singh", "Kumar", "Behera", "Mishra", "Sahoo", "Jena", "Rout"],
    "places": [("India", "Odisha"), ("India", "Bihar"), ("India", "West Bengal"), ("India", "Jharkhand"), ("India", "Assam")],
    "religion": ["Hindu", "Hindu", "Hindu", "Muslim", "Christian", "Sikh"],
}
_INTERNATIONAL = {
    "male": ["Musa", "Ibrahim", "Abdullahi", "Chinedu", "Tunde", "Kwame", "Kofi", "Bikash", "Rahim", "Karim", "Omar", "Hassan"],
    "female": ["Aisha", "Fatima", "Zainab", "Amina", "Ngozi", "Chiamaka", "Abena", "Ama", "Sunita", "Nusrat", "Ruksana", "Layla"],
    "last": ["Bello", "Okafor", "Adeyemi", "Mensah", "Boateng", "Gurung", "Thapa", "Hossain", "Rahman", "Alharbi", "Saleh", "Danjuma"],
    "places": [("Nigeria", "Kano"), ("Nigeria", "Kaduna"), ("Nigeria", "Lagos"), ("Nigeria", "Enugu"), ("Ghana", "Ashanti"),
               ("Nepal", "Bagmati"), ("Bangladesh", "Dhaka"), ("Yemen", "Sanaa")],
    "religion": ["Muslim", "Muslim", "Muslim", "Christian", "Christian", "Hindu", "Buddhist"],
}
_COURSES = [("MSc Computer Science", "Computer Science"), ("B.Tech CSE", "Computer Science"), ("BBA", "Management"),
            ("MBA", "Management"), ("B.Sc Agriculture", "Agriculture"), ("MA English", "Humanities")]
_COLOURS = ["#1f6f5c", "#8a4f7d", "#c06c3a", "#3b6ea5", "#7a7a2e", "#a14a4a", "#4a6b8a", "#6b4fa1"]


def _room_slots(gender):
    name, (g, rooms) = next((n, v) for n, v in HOSTELS.items() if v[0] == gender)
    return [(name, number) for number, capacity in rooms for _ in range(capacity)]


def generate_students(count=60, seed=2026, without_room=3):
    """Fictional students as rows for the import file. The last few have no room yet."""
    rng = random.Random(seed)
    rows, used_names = [], set()
    slots = {"male": _room_slots("male"), "female": _room_slots("female")}
    for n in range(1, count + 1):
        gender = "male" if rng.random() < 0.6 else "female"
        international = rng.random() < 0.4
        pool = _INTERNATIONAL if international else _NATIONAL
        while True:
            name = f"{rng.choice(pool[gender])} {rng.choice(pool['last'])}"
            if name not in used_names:
                used_names.add(name)
                break
        country, state = rng.choice(pool["places"])
        course, department = rng.choice(_COURSES)
        hostel, room = ("", "")
        if n <= count - without_room and slots[gender]:
            hostel, room = slots[gender].pop(0)
        rows.append({
            "roll_number": f"KU26{n:04d}", "name": name, "gender": gender,
            "category": "International" if international else "National",
            "diet": rng.choice(DIETS), "religion": rng.choice(pool["religion"]),
            "course": course, "department": department, "country": country, "state": state,
            "guardian_name": f"Mr. {name.split()[-1]}", "guardian_phone": f"+00 000 000 {n:04d}",
            "hostel": hostel, "room": room, "photo": "",
        })
    return rows


def with_deliberate_errors(rows):
    """A copy of the rows with six known mistakes, for trying the import preview."""
    rows = [dict(r) for r in rows]
    females = [i for i, r in enumerate(rows) if r["gender"] == "female"]
    rows[1]["roll_number"] = rows[0]["roll_number"]  # duplicate roll number in the file
    rows[3]["category"] = "Foreigner"  # unknown category
    rows[4]["gender"] = "X"  # unknown gender
    rows[5]["hostel"], rows[5]["room"] = "Boys Hostel A", "999"  # room that does not exist
    rows[females[2]]["hostel"], rows[females[2]]["room"] = "Boys Hostel A", "101"  # girl in a boys hostel
    rows[7]["name"] = ""  # missing name
    return rows


def _csv_bytes(rows, columns):
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


def _avatar(name, colour):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("RGB", (240, 240), colour)
    draw = ImageDraw.Draw(image)
    initials = "".join(part[0] for part in name.split()[:2]).upper()
    try:
        font = ImageFont.load_default(size=96)
    except TypeError:  # very old Pillow
        font = ImageFont.load_default()
    box = draw.textbbox((0, 0), initials, font=font)
    draw.text(((240 - (box[2] - box[0])) / 2 - box[0], (240 - (box[3] - box[1])) / 2 - box[1]), initials, fill="white", font=font)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return buffer.getvalue()


def write_sample_files(out_dir, count=60, seed=2026):
    """Write the sample CSV, Excel file, error-test CSV and photo zip. Returns {label: path}."""
    from openpyxl import Workbook

    from residents.import_files import COLUMNS

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows = generate_students(count, seed)
    paths = {}

    paths["csv"] = out / "students_demo.csv"
    paths["csv"].write_bytes(_csv_bytes(rows, COLUMNS))

    paths["errors"] = out / "students_demo_with_errors.csv"
    paths["errors"].write_bytes(_csv_bytes(with_deliberate_errors(rows), COLUMNS))

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Students"
    sheet.append(COLUMNS)
    for row in rows:
        sheet.append([row[c] for c in COLUMNS])
    paths["xlsx"] = out / "students_demo.xlsx"
    workbook.save(paths["xlsx"])

    paths["photos"] = out / "photos_demo.zip"
    with zipfile.ZipFile(paths["photos"], "w", zipfile.ZIP_STORED) as archive:
        for index, row in enumerate(rows):
            archive.writestr(f"{row['roll_number']}.jpg", _avatar(row["name"], _COLOURS[index % len(_COLOURS)]))
    return paths
