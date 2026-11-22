import os
import unittest

os.environ.setdefault("ENABLE_AUTO_SCAN", "false")
os.environ.setdefault("SECRET_KEY", "ci-ai-company-test-secret-key-not-production")
os.environ.setdefault("COOKIE_SECURE", "false")
os.environ.setdefault("DATABASE_URL", "sqlite:///ci-market-tests.db")
os.environ.pop("OPENAI_API_KEY", None)

import app as platform
from ai_company import EMPLOYEES, DEPARTMENTS, install


install(platform)


class AICompanyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        platform.app.config.update(TESTING=True)

    def setUp(self):
        with platform.app.app_context():
            platform.db.session.remove()
            platform.db.drop_all()
            platform.db.create_all()
            admin = platform.User(
                email="owner@example.com",
                password_hash=platform.generate_password_hash("OwnerStrongPass123"),
                role="admin",
                subscription_plan="admin",
            )
            platform.db.session.add(admin)
            platform.db.session.commit()
        self.client = platform.app.test_client()
        token = self.client.get("/api/bootstrap").get_json()["csrf"]
        response = self.client.post(
            "/api/auth/login",
            json={"email": "owner@example.com", "password": "OwnerStrongPass123"},
            headers={"X-CSRF-Token": token},
        )
        self.assertEqual(response.status_code, 200, response.get_json())

    def test_registry_has_exactly_100_unique_employees_and_10_departments(self):
        self.assertEqual(len(EMPLOYEES), 100)
        self.assertEqual(len({employee["id"] for employee in EMPLOYEES}), 100)
        self.assertEqual(len(DEPARTMENTS), 10)
        self.assertEqual({employee["department"] for employee in EMPLOYEES}, {d[0] for d in DEPARTMENTS})
        self.assertEqual(EMPLOYEES[0]["title"], "المدير التنفيذي")

    def test_owner_dashboard_and_protected_page(self):
        page = self.client.get("/company")
        self.assertEqual(page.status_code, 200)
        dashboard = self.client.get("/api/ai-company/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        data = dashboard.get_json()
        self.assertEqual(data["employee_count"], 100)
        self.assertEqual(data["department_count"], 10)
        self.assertEqual(len(data["employees"]), 100)

    def test_owner_can_assign_task_to_specific_employee(self):
        csrf = self.client.get("/api/ai-company/dashboard").get_json()["csrf"]
        response = self.client.post(
            "/api/ai-company/tasks",
            json={
                "title": "مراجعة جودة بيانات السوق",
                "brief": "راجع حداثة البيانات وحدد النواقص والمخاطر.",
                "employee_id": "stp-081",
            },
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 201, response.get_json())
        self.assertEqual(response.get_json()["status"], "queued")

    def test_task_execution_requires_openai_secret(self):
        csrf = self.client.get("/api/ai-company/dashboard").get_json()["csrf"]
        created = self.client.post(
            "/api/ai-company/tasks",
            json={"title": "مهمة اختبار", "brief": "تحقق من اكتمال قائمة الفحص.", "employee_id": "stp-091"},
            headers={"X-CSRF-Token": csrf},
        )
        task_id = created.get_json()["task_id"]
        response = self.client.post(
            f"/api/ai-company/tasks/{task_id}/run",
            json={},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(response.status_code, 503)

    def test_employee_directory_is_not_public(self):
        client = platform.app.test_client()
        self.assertIn(client.get("/api/ai-company/dashboard").status_code, (401, 403))
        self.assertIn(client.get("/company").status_code, (401, 403))


if __name__ == "__main__":
    unittest.main()
