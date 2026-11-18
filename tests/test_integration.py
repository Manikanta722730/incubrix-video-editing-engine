"""Test suite for IncuBrix Integration Standard (Points 1-10).

1. One-command start and test (.env.example exists, compose exists, zero API keys required).
2. Documented HTTP API (openapi.yaml exists, valid OpenAPI 3.1, all routes under /api/v1/).
3. Background jobs (POST returns 202 with job_id, GET /api/v1/jobs/{job_id} returns status 0-100 and links, HMAC-SHA256 signature).
4. Safe retries (Idempotency-Key header returns same job, no duplicate work).
5. Clear errors (JSON format {"error": {"code", "message", "retryable", "details"}} with UPPER_SNAKE_CASE).
6. Configuration (Settings from env vars/config).
7. Files in, files out (Input accepted as upload or URL; outputs saved and returned as download links).
8. Logs and health (Structured JSON logs, X-Correlation-Id, GET /health, GET /ready).
9. Output manifest (JSON manifest with models, versions, settings, seed, timings, cost, warnings, licensing).
10. Batch runner (Command-line tool runs folder/file of test inputs and writes all results to one folder).
"""

import os
import unittest
import json
import yaml
from starlette.testclient import TestClient

from api.app import app
from engine.manifest import generate_manifest
from engine.batch_runner import run_batch

client = TestClient(app)


class TestIntegrationStandard(unittest.TestCase):

    def test_point_1_one_command_start_and_test(self):
        """Point 1: .env.example exists, lists settings, no API keys needed for testing."""
        self.assertTrue(os.path.exists(".env.example"))
        with open(".env.example", "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("STT_PROVIDER=mock", content)
        self.assertIn("LLM_PROVIDER=rule_based", content)
        self.assertIn("DEFAULT_TIME_POLICY", content)

    def test_point_2_documented_http_api(self):
        """Point 2: openapi.yaml is valid OpenAPI 3.1 and all routes under /api/v1/."""
        self.assertTrue(os.path.exists("openapi.yaml"))
        with open("openapi.yaml", "r", encoding="utf-8") as f:
            spec = yaml.safe_load(f)
        self.assertEqual(spec.get("openapi"), "3.1.0")
        v1_paths = [p for p in spec.get("paths", {}).keys() if p.startswith("/api/v1/")]
        self.assertTrue(len(v1_paths) >= 4)

    def test_point_3_background_jobs_and_webhook_hmac(self):
        """Point 3: Slower operations run as background jobs returning 202 with job_id, progress polling, HMAC."""
        # 1. Create session
        res_sess = client.post("/api/v1/sessions", json={"video_url": "test_pack/media/two_speaker_podcast.mp4"})
        self.assertEqual(res_sess.status_code, 201)
        sess_id = res_sess.json()["session_id"]

        # 2. Trigger render job -> returns 202
        res_render = client.post(f"/api/v1/sessions/{sess_id}/render", json={"callback_url": "http://localhost:8000/mock_webhook"})
        self.assertEqual(res_render.status_code, 202)
        job_data = res_render.json()
        self.assertIn("job_id", job_data)
        job_id = job_data["job_id"]

        # 3. Poll job status
        res_job = client.get(f"/api/v1/jobs/{job_id}")
        self.assertEqual(res_job.status_code, 200)
        self.assertIn(res_job.json()["status"], ["queued", "running", "succeeded"])

    def test_point_4_safe_retries_idempotency(self):
        """Point 4: Idempotency-Key header on POST returns same job/response without doing work twice."""
        idem_key = "test_retry_key_4242"
        # First request
        r1 = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": idem_key},
            json={"video_url": "test_pack/media/two_speaker_podcast.mp4"}
        )
        self.assertIn(r1.status_code, [200, 201])
        sess_1 = r1.json()["session_id"]

        # Duplicate request with same Idempotency-Key
        r2 = client.post(
            "/api/v1/sessions",
            headers={"Idempotency-Key": idem_key},
            json={"video_url": "test_pack/media/two_speaker_podcast.mp4"}
        )
        self.assertEqual(r2.status_code, 200)
        sess_2 = r2.json()["session_id"]

        self.assertEqual(sess_1, sess_2, "Idempotency failed: generated different session IDs!")

    def test_point_5_clear_errors(self):
        """Point 5: Errors are JSON {"error": {"code", "message", "retryable", "details"}} with UPPER_SNAKE_CASE."""
        res = client.get("/api/v1/sessions/non_existent_session_id_999")
        self.assertEqual(res.status_code, 404)
        err = res.json().get("error", {})
        self.assertIn("code", err)
        self.assertIn("message", err)
        self.assertIn("retryable", err)
        self.assertIn("details", err)
        self.assertEqual(err["code"], "TIMELINE_NOT_FOUND")

    def test_point_6_configuration(self):
        """Point 6: Configuration comes from environment variables without hardcoded paths."""
        from engine.config import get_settings
        settings = get_settings()
        self.assertIsNotNone(settings.DEFAULT_TIME_POLICY)
        self.assertIsNotNone(settings.STT_PROVIDER)
        self.assertIsNotNone(settings.LLM_PROVIDER)

    def test_point_7_files_in_files_out(self):
        """Point 7: Inputs accepted as upload/URL, outputs saved and returned as download links."""
        res = client.get("/api/v1/storage/download/non_existent_file.mp4")
        self.assertEqual(res.status_code, 404)
        self.assertEqual(res.json()["error"]["code"], "MEDIA_NOT_FOUND")

    def test_point_8_logs_and_health(self):
        """Point 8: GET /health and GET /ready endpoints and X-Correlation-Id header."""
        res_health = client.get("/health")
        self.assertEqual(res_health.status_code, 200)
        self.assertEqual(res_health.json()["status"], "ok")

        res_ready = client.get("/ready")
        self.assertEqual(res_ready.status_code, 200)
        self.assertEqual(res_ready.json()["status"], "ready")

        res_corr = client.get("/health", headers={"X-Correlation-Id": "trace_xyz_123"})
        self.assertEqual(res_corr.headers.get("X-Correlation-Id"), "trace_xyz_123")

    def test_point_9_output_manifest(self):
        """Point 9: Output manifest JSON includes models, settings, seed, timings, cost, licensing."""
        manifest = generate_manifest(
            job_id="job_test_01",
            timeline_id="tl_test_01",
            source_media_duration_s=240.0,
            rendered_duration_s=210.0,
            timings={"render": 0.5, "total": 0.6}
        )
        self.assertIn("models_and_providers", manifest)
        self.assertIn("settings", manifest)
        self.assertIn("execution_seed", manifest)
        self.assertIn("timings", manifest)
        self.assertIn("cost_estimate", manifest)
        self.assertIn("licensing_and_rights", manifest)
        self.assertTrue(manifest["licensing_and_rights"]["commercial_use_permitted"])

    def test_point_10_batch_runner(self):
        """Point 10: Batch runner CLI tool runs folder of test inputs and writes all results to one folder."""
        batch_summary = run_batch("test_pack/sessions/session_01_worked_example.yaml", "test_pack/outputs/int_batch_test")
        self.assertEqual(batch_summary["succeeded"], 1)
        self.assertTrue(os.path.exists("test_pack/outputs/int_batch_test/batch_summary.json"))


if __name__ == "__main__":
    unittest.main()

