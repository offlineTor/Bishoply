import os
import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi import FastAPI


class WebAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from backend.database import db
        from backend.database import db as database
        from backend.api.accounts import router
        self.database = database
        self.old_path, self.old_url = database.DB_PATH, database.DATABASE_URL
        self.old_secret = os.environ.get("SESSION_SECRET")
        os.environ["SESSION_SECRET"] = "test-web-auth-secret"
        self.temp = tempfile.TemporaryDirectory()
        database.DB_PATH = Path(self.temp.name) / "auth.db"
        database.DATABASE_URL = ""
        await db.initialize_database()
        app = FastAPI()
        app.include_router(router)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        self.database.DB_PATH, self.database.DATABASE_URL = self.old_path, self.old_url
        if self.old_secret is None:
            os.environ.pop("SESSION_SECRET", None)
        else:
            os.environ["SESSION_SECRET"] = self.old_secret
        self.temp.cleanup()

    async def test_signup_login_and_session_restore(self):
        signup = await self.client.post("/api/auth/signup", json={
            "username": "KnightOne",
            "email": "knight@example.com",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        })
        self.assertEqual(signup.status_code, 200, signup.text)
        self.assertTrue(signup.json()["authenticated"])
        session = await self.client.get("/api/auth/session")
        self.assertEqual(session.status_code, 200, session.text)
        self.assertTrue(session.json()["authenticated"])
        self.client.cookies.clear()
        login = await self.client.post("/api/auth/login", json={
            "identifier": "knightone",
            "password": "correct horse battery staple",
        })
        self.assertEqual(login.status_code, 200, login.text)
        self.assertEqual((await self.client.get("/api/auth/session")).status_code, 200)

    async def test_duplicate_email_or_username_is_rejected(self):
        payload = {
            "username": "KnightOne",
            "email": "knight@example.com",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        }
        self.assertEqual((await self.client.post("/api/auth/signup", json=payload)).status_code, 200)
        duplicate = await self.client.post("/api/auth/signup", json={**payload, "username": "OtherName"})
        self.assertEqual(duplicate.status_code, 409, duplicate.text)

    async def test_wrong_password_is_rejected(self):
        payload = {
            "username": "KnightOne",
            "email": "knight@example.com",
            "password": "correct horse battery staple",
            "confirm_password": "correct horse battery staple",
        }
        await self.client.post("/api/auth/signup", json=payload)
        response = await self.client.post("/api/auth/login", json={"identifier": "knightone", "password": "wrong password"})
        self.assertEqual(response.status_code, 401, response.text)

    async def test_password_recovery_fails_closed_without_mail_provider(self):
        response = await self.client.post("/api/auth/forgot-password", json={"email": "knight@example.com"})
        self.assertEqual(response.status_code, 503, response.text)
