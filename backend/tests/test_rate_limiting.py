import unittest

from backend.rate_limiting import LoginRateLimiter


class LoginRateLimiterTests(unittest.TestCase):
    def test_limits_repeated_failures_for_normalized_identity_and_source(self):
        limiter = LoginRateLimiter("test-secret", max_attempts=3, window_seconds=60)
        for attempt_time in (100.0, 101.0, 102.0):
            limiter.record_failure(" OWNER@example.com ", "192.0.2.10", now=attempt_time)

        self.assertEqual(limiter.retry_after("owner@example.com", "192.0.2.10", now=102), 58)

    def test_attempts_from_another_source_have_a_separate_bucket(self):
        limiter = LoginRateLimiter("test-secret", max_attempts=2, window_seconds=60)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=100)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=101)

        self.assertEqual(limiter.retry_after("owner@example.com", "192.0.2.10", now=101), 59)
        self.assertEqual(limiter.retry_after("owner@example.com", "192.0.2.11", now=101), 0)

    def test_expired_failures_stop_blocking_and_success_can_clear_bucket(self):
        limiter = LoginRateLimiter("test-secret", max_attempts=2, window_seconds=60)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=100)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=101)
        self.assertEqual(limiter.retry_after("owner@example.com", "192.0.2.10", now=161), 0)

        limiter.record_failure("owner@example.com", "192.0.2.10", now=200)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=201)
        limiter.clear("owner@example.com", "192.0.2.10")
        self.assertEqual(limiter.retry_after("owner@example.com", "192.0.2.10", now=201), 0)

    def test_failure_store_is_bounded_and_does_not_keep_plain_usernames(self):
        limiter = LoginRateLimiter("test-secret", max_attempts=2, window_seconds=60, max_keys=2)
        limiter.record_failure("owner@example.com", "192.0.2.10", now=100)
        limiter.record_failure("second@example.com", "192.0.2.10", now=101)
        limiter.record_failure("third@example.com", "192.0.2.10", now=102)

        self.assertLessEqual(len(limiter._failures), 2)
        self.assertNotIn("owner@example.com", "".join(limiter._failures))
        self.assertNotIn("third@example.com", "".join(limiter._failures))


if __name__ == "__main__":
    unittest.main()
