import json
import logging
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).parent.parent / ".env")
log = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.json"
with open(CONFIG_PATH) as f:
    _config = json.load(f)

BASE_ID = _config["baseId"]
SOURCES_TABLE = _config["tables"]["sources"]
RAW_ITEMS_TABLE = _config["tables"]["rawItems"]

API_TOKEN = os.getenv("AIRTABLE_TOKEN")
BASE_URL = f"https://api.airtable.com/v0/{BASE_ID}"
HEADERS = {"Authorization": f"Bearer {API_TOKEN}", "Content-Type": "application/json"}

RATE_LIMIT_SLEEP = 0.2  # 200ms between calls
MAX_RETRIES = 3


def _request(method: str, url: str, **kwargs) -> dict:
    for attempt in range(MAX_RETRIES):
        resp = requests.request(method, url, headers=HEADERS, **kwargs)
        if resp.status_code == 429:
            wait = 1 * (attempt + 1)
            log.warning(f"Rate limit hit, sleeping {wait}s (attempt {attempt+1})")
            time.sleep(wait)
            continue
        resp.raise_for_status()
        time.sleep(RATE_LIMIT_SLEEP)
        return resp.json()
    raise RuntimeError(f"Max retries exceeded for {url}")


class AirtableClient:
    def get_active_sources(self, type_filter: str = None) -> list[dict]:
        """Return active sources, optionally filtered by Type."""
        params = {"filterByFormula": "{Active}=1"}
        if type_filter:
            params["filterByFormula"] = f'AND({{Active}}=1, {{Type}}="{type_filter}")'

        records = []
        offset = None
        while True:
            if offset:
                params["offset"] = offset
            data = _request("GET", f"{BASE_URL}/Sources", params=params)
            for r in data.get("records", []):
                records.append({"id": r["id"], **r["fields"]})
            offset = data.get("offset")
            if not offset:
                break
        log.info(f"Loaded {len(records)} active sources" + (f" (type={type_filter})" if type_filter else ""))
        return records

    def get_existing_urls(self) -> set[str]:
        """Return set of all URLs already in Raw Items table."""
        urls = set()
        offset = None
        params = {"fields[]": "URL"}
        while True:
            if offset:
                params["offset"] = offset
            data = _request("GET", f"{BASE_URL}/Raw%20Items", params=params)
            for r in data.get("records", []):
                url = r.get("fields", {}).get("URL")
                if url:
                    urls.add(url)
            offset = data.get("offset")
            if not offset:
                break
        log.info(f"Loaded {len(urls)} existing URLs for dedup")
        return urls

    def create_raw_item(self, data: dict) -> dict:
        """Create a single Raw Item record with Status=New."""
        fields = {
            "Title": data.get("title", "")[:500],
            "Content": data.get("content", ""),
            "URL": data.get("url", ""),
            "Published date": data.get("published_date"),
            "Collected at": data.get("collected_at"),
            "Status": "New",
        }
        if data.get("source_id"):
            fields["Source"] = [data["source_id"]]
        fields = {k: v for k, v in fields.items() if v is not None}
        result = _request("POST", f"{BASE_URL}/Raw%20Items", json={"records": [{"fields": fields}]})
        return result["records"][0]

    def create_raw_items_batch(self, items: list[dict]) -> int:
        """Create up to 10 records per batch. Returns count created."""
        created = 0
        for i in range(0, len(items), 10):
            batch = items[i:i + 10]
            records = []
            for data in batch:
                fields = {
                    "Title": data.get("title", "")[:500],
                    "Content": data.get("content", ""),
                    "URL": data.get("url", ""),
                    "Published date": data.get("published_date"),
                    "Collected at": data.get("collected_at"),
                    "Source Image URL": data.get("source_image_url"),
                    "Status": "New",
                }
                if data.get("source_id"):
                    fields["Source"] = [data["source_id"]]
                fields = {k: v for k, v in fields.items() if v is not None}
                records.append({"fields": fields})
            result = _request("POST", f"{BASE_URL}/Raw%20Items", json={"records": records})
            created += len(result.get("records", []))
            log.info(f"Batch created {len(result.get('records', []))} records")
        return created

    def get_records(self, table_key: str, filter_formula: str = None, max_records: int = 100) -> list[dict]:
        """Fetch records from any table by key (from config). Returns list of {id, fields}."""
        table_id = _config["tables"][table_key]
        params = {}
        if filter_formula:
            params["filterByFormula"] = filter_formula
        if max_records:
            params["maxRecords"] = max_records

        records = []
        offset = None
        while True:
            if offset:
                params["offset"] = offset
            data = _request("GET", f"{BASE_URL}/{table_id}", params=params)
            records.extend(data.get("records", []))
            offset = data.get("offset")
            if not offset or len(records) >= max_records:
                break
        log.info(f"Fetched {len(records)} records from {table_key}")
        return records

    def update_record(self, table_key: str, record_id: str, fields: dict) -> dict:
        """Update fields on a record. Returns updated record."""
        table_id = _config["tables"][table_key]
        result = _request(
            "PATCH",
            f"{BASE_URL}/{table_id}/{record_id}",
            json={"fields": fields},
        )
        log.debug(f"Updated {record_id} in {table_key}")
        return result

    def update_source_last_checked(self, source_id: str) -> None:
        """Update Last checked timestamp for a Source record."""
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        _request("PATCH", f"{BASE_URL}/Sources/{source_id}", json={"fields": {"Last checked": now}})
        log.debug(f"Updated last_checked for source {source_id}")

    def create_record(self, table_key: str, fields: dict) -> dict:
        """Create a single record in any table. Returns created record."""
        table_id = _config["tables"][table_key]
        fields = {k: v for k, v in fields.items() if v is not None}
        result = _request("POST", f"{BASE_URL}/{table_id}", json={"records": [{"fields": fields}]})
        log.info(f"Created record in {table_key}")
        return result["records"][0]

    def delete_record(self, table_key: str, record_id: str) -> None:
        """Delete a single record."""
        table_id = _config["tables"][table_key]
        _request("DELETE", f"{BASE_URL}/{table_id}/{record_id}")
        log.info(f"Deleted {record_id} from {table_key}")

    def delete_records_batch(self, table_key: str, record_ids: list[str]) -> int:
        """Delete up to 10 records per batch. Returns count deleted."""
        table_id = _config["tables"][table_key]
        deleted = 0
        for i in range(0, len(record_ids), 10):
            batch = record_ids[i:i + 10]
            params = "&".join(f"records[]={rid}" for rid in batch)
            _request("DELETE", f"{BASE_URL}/{table_id}?{params}")
            deleted += len(batch)
            log.info(f"Batch deleted {len(batch)} records from {table_key}")
        return deleted
