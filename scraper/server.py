import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request

load_dotenv(Path(__file__).parent.parent / ".env")

# Thêm scraper/ vào path để import các module
sys.path.insert(0, str(Path(__file__).parent))

from airtable_client import AirtableClient
from deduplicator import Deduplicator
import main as pipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

app = Flask(__name__)

API_SECRET_KEY = os.getenv("API_SECRET_KEY", "")


def _check_auth():
    """Return error response nếu API key sai, None nếu OK."""
    if not API_SECRET_KEY:
        return None  # dev mode, no auth
    key = request.headers.get("X-API-Key", "")
    if key != API_SECRET_KEY:
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/run-rss")
def run_rss():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        dedup = Deduplicator(client)
        created = pipeline.run_rss_pipeline(client, dedup)
        log.info(f"/run-rss: {created} new items")
        return jsonify({"created": created})
    except Exception as e:
        log.error(f"/run-rss error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-facebook")
def run_facebook():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        dedup = Deduplicator(client)
        created = pipeline.run_facebook_pipeline(client, dedup)
        log.info(f"/run-facebook: {created} new items")
        return jsonify({"created": created})
    except Exception as e:
        log.error(f"/run-facebook error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-ai-processor")
def run_ai_processor():
    err = _check_auth()
    if err:
        return err
    try:
        from ai_processor import AIProcessor
        processor = AIProcessor()
        stats = processor.process_new_items(limit=50)
        log.info(f"/run-ai-processor: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-ai-processor error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-buffer")
def run_buffer():
    err = _check_auth()
    if err:
        return err
    try:
        from buffer_publisher import BufferPublisher
        publisher = BufferPublisher()
        stats = publisher.push_pending_items(limit=20)
        log.info(f"/run-buffer: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-buffer error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-newsletter")
def run_newsletter():
    err = _check_auth()
    if err:
        return err
    try:
        from beehiiv_publisher import BeehiivPublisher
        publisher = BeehiivPublisher()
        stats = publisher.publish_pending_items(limit=20)
        log.info(f"/run-newsletter: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-newsletter error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/run-visual")
def run_visual():
    """Generate images for Approved Content Queue items without images."""
    err = _check_auth()
    if err:
        return err
    try:
        from visual_creator import VisualCreator
        creator = VisualCreator()
        stats = creator.process_pending(limit=10)
        log.info(f"/run-visual: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-visual error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
