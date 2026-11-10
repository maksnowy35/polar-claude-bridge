import unittest

from tools.check_sensitive import check_content, check_path

# Built from parts so this file does not trip the guard it is testing.
FAKE_SECRET_LINE = "CLIENT_" + 'SECRET = "' + "a1b2c3d4e5f6a7b8" + '"'
FAKE_BEARER = "Authorization: Bear" + "er " + "x" * 32
FAKE_DB_URL = "postgres" + "ql://user:" + "s3cret@ep-test.eu-central-1.aws.neon.tech/neondb"


class PathRulesTest(unittest.TestCase):
    def test_private_and_confidential_files_are_blocked(self):
        self.assertTrue(check_path("database/private/raw/api/sleep.json"))
        self.assertTrue(check_path("database/confidential/journal/log.csv"))

    def test_readmes_in_data_folders_are_allowed(self):
        self.assertEqual(check_path("database/private/README.md"), [])

    def test_env_files(self):
        self.assertTrue(check_path(".env"))
        self.assertTrue(check_path(".env.local"))
        self.assertEqual(check_path(".env.example"), [])

    def test_database_files(self):
        self.assertTrue(check_path("health.db"))


class ContentRulesTest(unittest.TestCase):
    def test_polar_json_outside_allowed_folders(self):
        self.assertTrue(check_content("exports/night.json", '{"polar_user": "x", "hypnogram": {}}'))
        self.assertEqual(check_content("tests/fixtures/night.json", '{"polar_user": "x"}'), [])
        self.assertEqual(check_content("database/public/sample/night.json", '{"hypnogram": {}}'), [])

    def test_hardcoded_secrets(self):
        self.assertTrue(check_content("auth.py", FAKE_SECRET_LINE))
        self.assertTrue(check_content("notes.md", FAKE_BEARER))
        self.assertTrue(check_content("README.md", FAKE_DB_URL))

    def test_secrets_from_environment_are_fine(self):
        self.assertEqual(check_content("auth.py", 'CLIENT_SECRET = os.getenv("POLAR_CLIENT_SECRET", "")'), [])
        self.assertEqual(check_content("README.md", "DATABASE_URL=postgresql://user:...@host/db"), [])


if __name__ == "__main__":
    unittest.main()
