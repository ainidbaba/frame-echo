"""Artifact-safety checks: blinded metadata, offline images and JSON boundaries."""
import base64
import json
from pathlib import Path
import re
import tempfile
import unittest

try:
    from scripts.review_page import write_review_page
except ModuleNotFoundError:
    from review_page import write_review_page


def candidate(**updates):
    uri = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xd9").decode()
    item = {"candidate_id":"C001", "artwork_id":"A01", "artwork_title":"Example artwork", "artist":"Example artist",
            "video_id":"V01", "frame_sha256":"a" * 64, "presentation_order":1,
            "reference_image":uri, "frame_image":uri, "canonical_timestamp":78.022}
    item.update(updates)
    return item


class ReviewPageSafetyTests(unittest.TestCase):
    def generate(self, items):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "review.html"
            write_review_page(destination, items, "round2-test", 271828)
            return destination.read_text(encoding="utf-8")

    def payload(self, document):
        match = re.search(r'<script id="review-data" type="application/json">(.*?)</script>', document, re.S)
        self.assertIsNotNone(match)
        return json.loads(match.group(1))

    def test_offline_payload_drops_condition_membership_and_keeps_export_identity(self):
        document = self.generate([candidate(method="SECRET_METHOD", rank=999, score=.999, membership=["SECRET_VARIANT"])])
        payload = self.payload(document)
        self.assertNotIn("SECRET_METHOD", document)
        self.assertNotIn("SECRET_VARIANT", document)
        self.assertNotIn("method", payload["items"][0])
        self.assertEqual(payload["items"][0]["canonical_timestamp"], 78.022)
        self.assertEqual(payload["items"][0]["frame_sha256"], "a" * 64)
        self.assertNotRegex(document, r'<script[^>]+src\s*=')
        self.assertNotRegex(document, r'<link[^>]+href\s*=')
        self.assertNotRegex(document, r'\b(?:fetch|XMLHttpRequest|sendBeacon)\s*\(')

    def test_untrusted_artwork_text_cannot_close_the_json_script(self):
        title = '</script><script>alert("unsafe")</script>&\u2028'
        document = self.generate([candidate(artwork_title=title)])
        self.assertEqual(self.payload(document)["items"][0]["artwork_title"], title)
        self.assertNotIn(title, document)
        self.assertEqual(document.count("</script>"), 2)

    def test_supplied_order_is_retained_and_page_embeds_no_answers(self):
        items = [candidate(candidate_id="C002", presentation_order=2), candidate(candidate_id="C001", presentation_order=1)]
        payload = self.payload(self.generate(items))
        self.assertEqual([item["candidate_id"] for item in payload["items"]], ["C002", "C001"])
        self.assertNotIn("answers", payload)
        self.assertEqual(payload["seed"], 271828)

    def test_invalid_remote_images_duplicate_ids_and_invalid_timing_are_rejected(self):
        cases = [
            [candidate(frame_image="https://example.invalid/image.jpg")],
            [candidate(reference_image="data:image/jpeg;base64,not-base64")],
            [candidate(), candidate(presentation_order=2)],
            [candidate(canonical_timestamp=float("nan"))],
            [candidate(canonical_timestamp=-1)],
        ]
        for items in cases:
            with self.subTest(items=items), tempfile.TemporaryDirectory() as directory, self.assertRaises(ValueError):
                write_review_page(Path(directory) / "review.html", items, "test", 1)


if __name__ == "__main__":
    unittest.main()
