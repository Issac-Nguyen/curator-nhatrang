import logging
import os
import sys
import threading
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


def _run_facebook_bg():
    """Background worker for Facebook scraping."""
    try:
        client = AirtableClient()
        dedup = Deduplicator(client)
        created = pipeline.run_facebook_pipeline(client, dedup)
        log.info(f"[BG] Facebook scraper done: {created} new items")
    except Exception as e:
        log.error(f"[BG] Facebook scraper error: {e}")


@app.post("/run-facebook")
def run_facebook():
    err = _check_auth()
    if err:
        return err
    thread = threading.Thread(target=_run_facebook_bg, daemon=True)
    thread.start()
    return jsonify({"status": "started", "message": "Facebook scraper running in background"})


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


@app.post("/run-instagram")
def run_instagram():
    err = _check_auth()
    if err:
        return err
    try:
        from instagram_publisher import InstagramPublisher
        publisher = InstagramPublisher()
        stats = publisher.push_pending_items(limit=20)
        log.info(f"/run-instagram: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-instagram error: {e}")
        return jsonify({"error": str(e)}), 500


@app.post("/refresh-instagram-token")
def refresh_instagram_token():
    err = _check_auth()
    if err:
        return err
    try:
        from instagram_publisher import _refresh_token_if_needed
        token = _refresh_token_if_needed()
        masked = token[:10] + "..." + token[-5:] if len(token) > 20 else "***"
        log.info(f"/refresh-instagram-token: token={masked}")
        return jsonify({"status": "ok", "token_preview": masked})
    except Exception as e:
        log.error(f"/refresh-instagram-token error: {e}")
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


@app.post("/run-cleanup")
def run_cleanup():
    err = _check_auth()
    if err:
        return err
    try:
        client = AirtableClient()
        stats = {"published_deleted": 0, "raw_skip_deleted": 0, "raw_old_deleted": 0}

        # 1. Delete Published records > 30 days
        old_published = client.get_records(
            "published",
            filter_formula='IS_BEFORE({Published at}, DATEADD(TODAY(), -30, "days"))',
            max_records=100,
        )
        if old_published:
            ids = [r["id"] for r in old_published]
            stats["published_deleted"] = client.delete_records_batch("published", ids)

        # 2. Delete Raw Items Status=Skip
        skip_items = client.get_records(
            "rawItems",
            filter_formula='{Status}="Skip"',
            max_records=100,
        )
        if skip_items:
            ids = [r["id"] for r in skip_items]
            stats["raw_skip_deleted"] = client.delete_records_batch("rawItems", ids)

        # 3. Delete Raw Items Status=New older than 30 days
        old_new_items = client.get_records(
            "rawItems",
            filter_formula='AND({Status}="New", IS_BEFORE({Collected at}, DATEADD(TODAY(), -30, "days")))',
            max_records=100,
        )
        if old_new_items:
            ids = [r["id"] for r in old_new_items]
            stats["raw_old_deleted"] = client.delete_records_batch("rawItems", ids)

        log.info(f"/run-cleanup: {stats}")
        return jsonify(stats)
    except Exception as e:
        log.error(f"/run-cleanup error: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)
