# Hostel Meals Management System

A configurable system for hostels and messes: serve each student the right meal once, take the night roll call, record exit permits, and produce reports. Nothing in it is specific to one institution. Categories, diet types, hostels, rooms, meal times, counters and special periods (Ramadan, Navratri, ...) are data that an administrator sets up, and one installation can serve several organisations.

## What it does
- **Meal counters:** find a student by QR code (USB scanner or phone camera), roll number or name; see the photo; serve the meal that is open for that student right now. The same meal cannot be collected twice, and a counter can be limited to some categories of students.
- **Special periods:** date ranges with their own rules for some students, for example Ramadan (no breakfast, lunch and dinner moved, an Iftar time that can be set day by day) or Navratri.
- **Registration:** the warden registers students with a photo (upload or webcam), picks a room that has a free bed, and can import a whole class from CSV or Excel, with a preview.
- **Rooms:** capacity per room, gender rules per hostel, and a full history of moves.
- **Roll call:** night only, per hostel. The warden ticks the students who are missing.
- **Exit permits:** the warden grants them. A student on a permit shows as on leave, with the number of days left before being marked absent. Absence without a permit, or after the permit ended, is recorded with the days overdue.
- **Reports:** meals per day, meals per student, attendance, and absences without permission, daily, weekly, monthly or for any range, as a web page, CSV or PDF.
- **Roles:** an admin sees the whole organisation; a warden sees only the hostels assigned to them.

The system only records facts. It never charges fines: the reports give the central administration what it needs to do that.

## Run it
```bash
python3 -m venv .venv && source .venv/bin/activate     # on Windows: .venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo          # a fictional demo organisation and two users (prints a password)
python manage.py runserver
```
Open http://127.0.0.1:8000/ and sign in as `demo_warden` or `demo_admin`. To start with your own organisation instead, run `python manage.py createsuperuser`, then in `/admin/` create an organisation, its hostels and rooms, categories, diet types, meal types with their windows, counters, and a staff profile for each user.

Settings come from environment variables (see `.env.example`): `DJANGO_SECRET_KEY`, `DJANGO_DEBUG`, `DJANGO_ALLOWED_HOSTS`. The defaults are for local development only.

## Try the student import
```bash
python manage.py make_sample_files   # writes fictional students and photos to sample_data/
```
Then open `/residents/import/` and upload `sample_data/students_demo.csv` with `sample_data/photos_demo.zip`. `students_demo_with_errors.csv` has six planted mistakes to show the preview.

## Tests
```bash
python manage.py test
```

## Layout
| App | Purpose |
| --- | --- |
| `organizations` | organisations, categories, diet types, hostels, rooms, staff profiles, demo data |
| `residents` | students, room allocation, registration, import |
| `mess` | meal types and windows, counters, special periods, meal collection rules and the counter screen |
| `attendance` | exit permits and the night roll call |
| `reports` | report tables and CSV/PDF export |
| `accounts` | login and the admin/warden access rules |

Business rules live in each app's `services.py`; views call them rather than writing records directly.

## Notes
- Times are interpreted in each organisation's own time zone.
- Student QR codes hold a random token, never the roll number.
- Camera QR scanning uses the browser's built-in reader. It works in Chrome on Android and in some desktop browsers, and needs the page to be on `localhost` or `https`. A USB scanner or typing always works.
