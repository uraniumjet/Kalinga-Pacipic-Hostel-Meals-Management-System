# Hostel Meals Management System

Web application for hostel wardens: verify students at meal counters, block duplicate collection, record daily roll call and exit permits, and produce reports.

> Status: being rebuilt as a configurable, multi-organisation system. The current code is the original prototype with repository clean-up applied.

## Run locally
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # then export the variables, or set them in your shell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

## Known issues in the prototype (to be replaced by the rebuild)
- No login or roles on the API and pages.
- `meals.views.collect_meal` writes a field `MealLog` does not have and creates records before checking duplicates.
- `admin_dashboard` overwrites its own context.
- Pages load scripts from CDNs.
