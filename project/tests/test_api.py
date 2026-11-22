"""Exercise the real HTTP upload, asynchronous search and export workflow."""

from __future__ import annotations

import csv
import io
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]


class ApiWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="frame-echo-test-")
        cls.data_dir = Path(cls.directory.name)
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{port}"
        cls.log = (cls.data_dir / "server.log").open("w+")
        environment = {**os.environ, "FRAME_ECHO_DATA_DIR": str(cls.data_dir)}
        cls.server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
            cwd=ROOT, env=environment, stdout=cls.log, stderr=cls.log,
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(cls.base + "/api/capabilities", timeout=1) as response:
                    if response.status == 200:
                        return
            except (urllib.error.URLError, TimeoutError):
                if cls.server.poll() is not None:
                    break
                time.sleep(0.1)
        cls.server.terminate()
        cls.log.seek(0)
        raise RuntimeError("Test server did not start:\n" + cls.log.read())

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=15)
        cls.log.close()
        cls.directory.cleanup()

    def request(self, path, data=None, content_type=None, headers=None):
        request_headers = dict(headers or {})
        if content_type:
            request_headers["Content-Type"] = content_type
        request = urllib.request.Request(self.base + path, data=data, headers=request_headers)
        return urllib.request.urlopen(request, timeout=20)

    def json_request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode()
        with self.request(path, data, "application/json" if data else None) as response:
            return json.load(response)

    def wait_for_job(self, job_id):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            job = self.json_request(f"/api/jobs/{job_id}")
            if job["status"] in {"complete", "error"}:
                return job
            time.sleep(0.05)
        self.fail("The synthetic search did not finish within 20 seconds.")

    def persisted_job(self, job_id):
        path = self.data_dir / "runtime" / job_id / "results.json"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if path.is_file():
                return json.loads(path.read_text(encoding="utf-8"))
            time.sleep(0.01)
        self.fail("The completed search record was not persisted.")

    def upload(self, video_bytes=None, art_bytes=None, **settings):
        boundary = "frameecho-test-boundary-271828"
        body = bytearray()
        files = {
            "video_file": ("test.mp4", "video/mp4", video_bytes if video_bytes is not None else (self.data_dir / "demo" / "video.mp4").read_bytes()),
            "art_file": ("reference.png", "image/png", art_bytes if art_bytes is not None else (self.data_dir / "demo" / "reference.png").read_bytes()),
        }
        for name, (filename, mime, data) in files.items():
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {mime}\r\n\r\n'.encode())
            body.extend(data)
            body.extend(b"\r\n")
        for name, value in settings.items():
            if value is None:
                continue
            body.extend(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode())
        body.extend(f"--{boundary}--\r\n".encode())
        with self.request("/api/search", bytes(body), f"multipart/form-data; boundary={boundary}") as response:
            self.assertEqual(response.status, 202)
            return json.load(response)

    def test_frontend_assets_and_capabilities(self):
        for path, expected in [("/", b"Frame Echo"), ("/assets/app.js", b"/api/search"), ("/assets/styles.css", b".results-grid")]:
            with self.request(path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected, response.read())
        capabilities = self.json_request("/api/capabilities")
        self.assertTrue(capabilities["methods"][0]["available"])
        self.assertFalse(capabilities["methods"][1]["available"])

    def test_demo_ranking_media_range_and_csv_are_consistent(self):
        job_id = self.json_request("/api/demo/search", {"interval": 1, "top_k": 6, "min_gap": 3})["job_id"]
        job = self.wait_for_job(job_id)
        self.assertEqual(job["status"], "complete", job.get("error"))
        self.assertTrue(job["synthetic"])
        self.assertEqual(job["progress"], 100)
        self.assertEqual(job["frames_total"], 24)
        self.assertGreaterEqual(job["results"][0]["timestamp"], 4)
        self.assertLess(job["results"][0]["timestamp"], 8)
        self.assertEqual(len(job["results"]), 6)
        self.assertIsNone(job["settings"]["min_score"])
        self.assertEqual(job["match_status"], "matches_found")
        scores = [result["score"] for result in job["results"]]
        self.assertEqual(scores, sorted(scores, reverse=True))
        times = [result["timestamp"] for result in job["results"]]
        self.assertTrue(all(abs(a - b) >= 3 - 1e-6 for i, a in enumerate(times) for b in times[i + 1:]))
        with self.request(job["results"][0]["thumbnail_url"]) as response:
            self.assertEqual(response.headers.get_content_type(), "image/jpeg")
            self.assertGreater(len(response.read()), 100)
        with self.request(job["video"]["url"], headers={"Range": "bytes=0-99"}) as response:
            self.assertEqual(response.status, 206)
            self.assertEqual(len(response.read()), 100)
        with self.request(job["export_url"]) as response:
            rows = list(csv.DictReader(io.StringIO(response.read().decode("utf-8-sig"))))
        self.assertEqual(len(rows), len(job["results"]))
        self.assertEqual(rows[0]["video_sha256"], job["video"]["sha256"])
        self.assertAlmostEqual(float(rows[0]["cosine_similarity"]), job["results"][0]["score"], places=7)
        self.assertEqual(rows[0]["synthetic"], "True")
        self.assertEqual(rows[0]["min_score"], "")
        self.assertEqual(rows[0]["match_status"], "matches_found")
        saved = self.persisted_job(job_id)
        self.assertEqual(saved["results"], job["results"])

    def test_real_multipart_upload_route(self):
        job = self.wait_for_job(self.upload(interval=2, top_k=3, min_gap=0, method="colour")["job_id"])
        self.assertEqual(job["status"], "complete", job.get("error"))
        self.assertFalse(job["synthetic"])
        self.assertEqual(job["frames_total"], 12)
        self.assertEqual(len(job["results"]), 3)
        self.assertIsNone(job["settings"]["min_score"])

    def test_explicit_null_threshold_keeps_demo_results_unchanged(self):
        normal = self.wait_for_job(self.json_request("/api/demo/search", {"method": "colour"})["job_id"])
        explicit_null = self.wait_for_job(self.json_request("/api/demo/search", {"method": "colour", "min_score": None})["job_id"])
        self.assertEqual(normal["status"], "complete", normal.get("error"))
        self.assertEqual(explicit_null["status"], "complete", explicit_null.get("error"))
        self.assertEqual(normal["results"], [
            {**match,
             "thumbnail_url": match["thumbnail_url"].replace(explicit_null["job_id"], normal["job_id"]),
             "frame_url": match["frame_url"].replace(explicit_null["job_id"], normal["job_id"])}
            for match in explicit_null["results"]
        ])
        self.assertEqual(explicit_null["match_status"], "matches_found")
        self.assertIsNone(explicit_null["settings"]["min_score"])

    def test_demo_and_multipart_thresholds_can_return_fewer_results(self):
        for create in (
            lambda: self.json_request("/api/demo/search", {"method": "colour", "min_score": 0.8}),
            lambda: self.upload(method="colour", min_score=0.8),
        ):
            with self.subTest(route=create):
                job = self.wait_for_job(create()["job_id"])
                self.assertEqual(job["status"], "complete", job.get("error"))
                self.assertEqual(job["settings"]["min_score"], 0.8)
                self.assertEqual(job["match_status"], "matches_found")
                self.assertGreater(len(job["results"]), 0)
                self.assertLess(len(job["results"]), job["settings"]["top_k"])
                self.assertTrue(all(match["score"] >= 0.8 for match in job["results"]))

    def test_no_match_upload_completes_and_preserves_empty_result_evidence(self):
        reference = io.BytesIO()
        # A fully saturated magenta fixture differs from the muted demo palettes.
        Image.new("RGB", (120, 120), (255, 0, 255)).save(reference, format="PNG")
        job_id = self.upload(art_bytes=reference.getvalue(), method="colour", min_score=0.99)["job_id"]
        job = self.wait_for_job(job_id)
        self.assertEqual(job["status"], "complete", job.get("error"))
        self.assertEqual(job["progress"], 100)
        self.assertIsNone(job["error"])
        self.assertEqual(job["results"], [])
        self.assertEqual(job["match_status"], "no_match")
        self.assertEqual(job["message"], "No sufficiently similar frames found")
        self.assertEqual(job["settings"]["min_score"], 0.99)
        self.assertEqual(job["metadata_url"], f"/api/jobs/{job_id}/export.json")
        self.assertEqual(self.persisted_job(job_id)["match_status"], "no_match")
        with self.request(job["metadata_url"]) as response:
            self.assertEqual(response.headers.get_content_type(), "application/json")
            self.assertIn("attachment", response.headers["Content-Disposition"])
            exported = json.load(response)
        self.assertEqual(exported["results"], [])
        self.assertEqual(exported["settings"]["min_score"], 0.99)
        self.assertEqual(exported["match_status"], "no_match")
        self.assertEqual(exported["video"]["sha256"], job["video"]["sha256"])
        with self.request(job["export_url"]) as response:
            reader = csv.DictReader(io.StringIO(response.read().decode("utf-8-sig")))
            self.assertIn("min_score", reader.fieldnames)
            self.assertIn("match_status", reader.fieldnames)
            self.assertEqual(list(reader), [])

    def test_minimum_score_validation_for_demo_and_upload(self):
        for threshold in (-1.01, 1.01, "nan", "inf", "-inf", "not a score", "null"):
            for route in ("demo", "upload"):
                with self.subTest(route=route, min_score=threshold):
                    with self.assertRaises(urllib.error.HTTPError) as caught:
                        if route == "demo":
                            self.json_request("/api/demo/search", {"min_score": threshold})
                        else:
                            self.upload(min_score=threshold)
                    self.assertEqual(caught.exception.code, 422)
                    caught.exception.close()

    def test_bad_video_and_bad_image_report_job_errors(self):
        for payload in ({"video_bytes": b"this is not a movie"}, {"art_bytes": b"this is not an image"}):
            job = self.wait_for_job(self.upload(**payload)["job_id"])
            self.assertEqual(job["status"], "error")
            self.assertTrue(job["error"])
            self.assertEqual(job["results"], [])

    def test_invalid_settings_and_unavailable_clip_are_rejected(self):
        for settings in ({"interval": 0}, {"top_k": 21}, {"method": "aesthetics"}, {"min_gap": -1}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.json_request("/api/demo/search", settings)
            self.assertEqual(caught.exception.code, 422)
            caught.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.json_request("/api/demo/search", {"method": "clip"})
        self.assertEqual(caught.exception.code, 409)
        caught.exception.close()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.json_request("/api/jobs/does-not-exist")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


class MetadataExportGuardTests(unittest.TestCase):
    def test_metadata_export_before_completion_returns_conflict(self):
        # Invoke the registered route against a controlled queued record. A real
        # tiny video often finishes before a second HTTP request can reach it.
        from fastapi import HTTPException
        from app.main import SearchSettings, create_app

        with tempfile.TemporaryDirectory(prefix="frame-echo-queued-") as temporary:
            application = create_app(Path(temporary))
            manager = application.state.manager
            try:
                job_id, _ = manager.new(SearchSettings(), "queued.mp4", "reference.png", synthetic=True)
                endpoint = next(route.endpoint for route in application.routes
                                if getattr(route, "path", None) == "/api/jobs/{job_id}/export.json")
                with self.assertRaises(HTTPException) as caught:
                    endpoint(job_id)
                self.assertEqual(caught.exception.status_code, 409)
            finally:
                manager.executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
