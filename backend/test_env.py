from pathlib import Path

from django.test import SimpleTestCase

from backend.env import database_from_url, env_bool, env_int, env_list

BASE = Path("/srv/app")


class EnvHelperTests(SimpleTestCase):
    def test_env_bool(self):
        for raw in ("1", "true", "TRUE", "Yes", "on"):
            self.assertTrue(env_bool("X", False, {"X": raw}), raw)
        for raw in ("0", "false", "No", "off", ""):
            self.assertFalse(env_bool("X", True, {"X": raw}), raw)
        self.assertTrue(env_bool("MISSING", True, {}))
        self.assertFalse(env_bool("MISSING", False, {}))
        with self.assertRaises(ValueError):
            env_bool("X", False, {"X": "maybe"})

    def test_env_int(self):
        self.assertEqual(env_int("X", 5, {"X": "12"}), 12)
        self.assertEqual(env_int("X", 5, {}), 5)
        self.assertEqual(env_int("X", 5, {"X": " "}), 5)
        with self.assertRaises(ValueError):
            env_int("X", 5, {"X": "twelve"})

    def test_env_list_trims_and_drops_empty_items(self):
        self.assertEqual(env_list("X", "", {"X": " a.org, b.org ,,"}), ["a.org", "b.org"])
        self.assertEqual(env_list("X", "127.0.0.1,localhost", {}), ["127.0.0.1", "localhost"])
        self.assertEqual(env_list("X", "", {}), [])


class DatabaseUrlTests(SimpleTestCase):
    def test_relative_sqlite_path_is_inside_the_project(self):
        db = database_from_url("sqlite:///db.sqlite3", BASE)
        self.assertEqual(db["ENGINE"], "django.db.backends.sqlite3")
        self.assertEqual(db["NAME"], BASE / "db.sqlite3")

    def test_absolute_sqlite_path(self):
        self.assertEqual(database_from_url("sqlite:////data/hostel.db", BASE)["NAME"], Path("/data/hostel.db"))

    def test_postgres_url(self):
        db = database_from_url("postgres://meals:p%40ss%2Fword@db.internal:5433/hostel", BASE)
        self.assertEqual(db["ENGINE"], "django.db.backends.postgresql")
        self.assertEqual(
            (db["NAME"], db["USER"], db["PASSWORD"], db["HOST"], db["PORT"]),
            ("hostel", "meals", "p@ss/word", "db.internal", "5433"),
        )
        self.assertTrue(db["CONN_HEALTH_CHECKS"])

    def test_postgres_without_port(self):
        self.assertEqual(database_from_url("postgresql://u:p@db/hostel", BASE)["PORT"], "")

    def test_bad_urls_are_refused(self):
        for url in ("mysql://u:p@h/db", "postgres://u:p@h", "postgres:///hostel"):
            with self.assertRaises(ValueError, msg=url):
                database_from_url(url, BASE)
