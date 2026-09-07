import os
import unittest

from backend.security import RequestRateLimiter, environment, is_production


class SecurityPrimitiveTests(unittest.TestCase):
    def test_rate_limiter_throttles_after_limit(self):
        limiter = RequestRateLimiter(limit=2, window_seconds=60)
        self.assertTrue(limiter.allow("test-client"))
        self.assertTrue(limiter.allow("test-client"))
        self.assertFalse(limiter.allow("test-client"))

    def test_environment_defaults_to_development(self):
        old = os.environ.pop("BISHOPLY_ENV", None)
        try:
            self.assertEqual(environment(), "development")
            self.assertFalse(is_production())
        finally:
            if old is not None:
                os.environ["BISHOPLY_ENV"] = old


if __name__ == "__main__":
    unittest.main()
