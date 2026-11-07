import os
import unittest
from unittest.mock import patch

os.environ.setdefault("ENABLE_AUTO_SCAN", "false")
os.environ.setdefault("SECRET_KEY", "ci-auth-test-secret-key-not-for-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///ci-market-tests.db")

import app as platform


class AuthenticationAndAdminTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform.app.config.update(TESTING=True)

    _ip_counter = 10

    def setUp(self):
        with platform.app.app_context():
            platform.db.session.remove()
            platform.db.drop_all()
            platform.db.create_all()
        self.client = platform.app.test_client()
        # Rate-limit counters are keyed by client IP; isolate each test while
        # leaving production rate limiting enabled and covered by the app.
        type(self)._ip_counter += 1
        self.client.environ_base["REMOTE_ADDR"] = f"198.51.100.{type(self)._ip_counter}"

    def csrf_headers(self):
        token = self.client.get("/api/bootstrap").get_json()["csrf"]
        return {"X-CSRF-Token": token}

    def register_user(self, email="member@example.com", password="strongpass12345", **extra):
        payload = {"email": email, "password": password, **extra}
        return self.client.post(
            "/api/auth/register",
            json=payload,
            headers=self.csrf_headers(),
        )

    def login(self, identifier, password):
        return self.client.post(
            "/api/auth/login",
            json={"email": identifier, "password": password},
            headers=self.csrf_headers(),
        )

    def test_registration_creates_regular_user_and_authenticates_session(self):
        old_token = self.client.get("/api/bootstrap").get_json()["csrf"]
        response = self.client.post(
            "/api/auth/register",
            json={
                "email": "  Member@Example.com ",
                "password": "strongpass12345",
                "role": "admin",
            },
            headers={"X-CSRF-Token": old_token},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        data = response.get_json()
        self.assertEqual(data["user"]["email"], "member@example.com")
        self.assertEqual(data["user"]["role"], "user")
        self.assertNotEqual(data["csrf"], old_token)
        self.assertEqual(self.client.get("/api/me").status_code, 200)

    def test_registration_rejects_weak_password_and_invalid_email(self):
        weak = self.register_user(password="123456789012")
        self.assertEqual(weak.status_code, 400)
        invalid_email = self.register_user(email="not-an-email")
        self.assertEqual(invalid_email.status_code, 400)
        with platform.app.app_context():
            self.assertEqual(platform.User.query.count(), 0)

    def test_duplicate_email_is_case_insensitive_and_returns_conflict(self):
        first = self.register_user(email="Member@Example.com")
        second = self.register_user(email="member@example.com")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)
        self.assertIn("مسجل", second.get_json()["error"])

    def test_login_accepts_case_insensitive_email_and_rotates_csrf(self):
        registered = self.register_user()
        self.assertEqual(registered.status_code, 201)
        self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": registered.get_json()["csrf"]},
        )
        old_token = self.client.get("/api/bootstrap").get_json()["csrf"]
        logged_in = self.client.post(
            "/api/auth/login",
            json={"email": "MEMBER@EXAMPLE.COM", "password": "strongpass12345"},
            headers={"X-CSRF-Token": old_token},
        )
        self.assertEqual(logged_in.status_code, 200, logged_in.get_json())
        self.assertEqual(logged_in.get_json()["user"]["role"], "user")
        self.assertNotEqual(logged_in.get_json()["csrf"], old_token)
        self.assertEqual(self.client.get("/api/me").status_code, 200)

    def test_wrong_password_and_missing_fields_are_rejected(self):
        self.register_user()
        wrong = self.login("member@example.com", "incorrect-password")
        missing = self.client.post(
            "/api/auth/login",
            json={"email": ""},
            headers=self.csrf_headers(),
        )
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(missing.status_code, 400)

    def test_admin_bootstrap_rejects_existing_user_email_without_server_error(self):
        self.register_user(email="already-used@example.com")
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_TOKEN": "one-time-setup-token"}):
            response = self.client.post(
                "/api/admin/login-bootstrap",
                json={
                    "token": "one-time-setup-token",
                    "email": "already-used@example.com",
                    "password": "AdminStrongPass123",
                },
                headers=self.csrf_headers(),
            )
        self.assertEqual(response.status_code, 409, response.get_json())
        with platform.app.app_context():
            self.assertEqual(platform.User.query.filter_by(role="admin").count(), 0)

    def test_admin_bootstrap_creates_first_admin_once_and_authenticates(self):
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_TOKEN": "one-time-setup-token"}):
            created = self.client.post(
                "/api/admin/login-bootstrap",
                json={
                    "token": "one-time-setup-token",
                    "email": "root@example.com",
                    "password": "AdminStrongPass123",
                },
                headers=self.csrf_headers(),
            )
            self.assertEqual(created.status_code, 201, created.get_json())
            self.assertEqual(created.get_json()["user"]["role"], "admin")
            self.assertEqual(self.client.get("/api/admin/overview").status_code, 200)

            second_attempt = self.client.post(
                "/api/admin/login-bootstrap",
                json={
                    "token": "one-time-setup-token",
                    "email": "another-root@example.com",
                    "password": "AnotherStrongPass123",
                },
                headers=self.csrf_headers(),
            )
        self.assertEqual(second_attempt.status_code, 404)

    def test_admin_username_alias_can_sign_in_but_regular_user_cannot_access_admin(self):
        self.register_user()
        forbidden = self.client.get("/api/admin/overview")
        self.assertEqual(forbidden.status_code, 403)
        self.client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": self.client.get("/api/bootstrap").get_json()["csrf"]},
        )

        with platform.app.app_context():
            admin = platform.User(
                email="root@example.com",
                password_hash=platform.generate_password_hash("AdminStrongPass123"),
                role="admin",
                subscription_plan="admin",
            )
            platform.db.session.add(admin)
            platform.db.session.commit()

        with patch.dict(os.environ, {"ADMIN_USERNAME": "superadmin", "ADMIN_EMAIL": ""}):
            logged_in = self.login("superadmin", "AdminStrongPass123")
        self.assertEqual(logged_in.status_code, 200, logged_in.get_json())
        self.assertEqual(logged_in.get_json()["user"]["role"], "admin")
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 200)

    def test_admin_bootstrap_requires_correct_token_and_strong_password(self):
        with patch.dict(os.environ, {"ADMIN_BOOTSTRAP_TOKEN": "one-time-setup-token"}):
            bad_token = self.client.post(
                "/api/admin/login-bootstrap",
                json={
                    "token": "wrong",
                    "email": "root@example.com",
                    "password": "AdminStrongPass123",
                },
                headers=self.csrf_headers(),
            )
            weak_password = self.client.post(
                "/api/admin/login-bootstrap",
                json={
                    "token": "one-time-setup-token",
                    "email": "root@example.com",
                    "password": "12345678901234",
                },
                headers=self.csrf_headers(),
            )
        self.assertEqual(bad_token.status_code, 403)
        self.assertEqual(weak_password.status_code, 400)


if __name__ == "__main__":
    unittest.main()
