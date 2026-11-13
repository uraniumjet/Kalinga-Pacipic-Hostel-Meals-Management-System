# Contributing

## Set up
```bash
python3 -m venv .venv && source .venv/bin/activate
make install          # installs dependencies and the pre-commit hooks
python manage.py migrate
make seed             # fictional test data (demo organisation)
make run
```

## Before you open a pull request
```bash
make check            # ruff, migrations are up to date, all tests
```
CI runs the same checks, plus PostgreSQL, a deployment check and a Docker build.

## Rules we keep
- **Rules live in `services.py`.** Views call services; they do not write rows directly.
- **Every screen scopes its data** through `accounts/access.py`. A new query on students, hostels or staff must go through those helpers, and needs a test that another organisation cannot see it.
- **Nothing is specific to one institution.** Names, times, categories and periods are data an admin sets.
- **No money.** The system records facts and produces reports; it never charges fines.
- **Tests with every change.** Bug fixes get a test that fails without the fix.
- **Real student data never goes into the repository**, issues or screenshots. Use `make seed` data.
- Small pull requests, one purpose each; commit messages say what changed and why.

## Style
`ruff check .` is the standard (see `pyproject.toml`). Imports are sorted by ruff. Prefer clear names over comments;
comment the reason for a rule, not what the code does.

## Migrations
Change a model, run `python manage.py makemigrations`, commit the migration with the change.
Do not edit a migration that has been released.
