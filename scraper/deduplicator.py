import logging

log = logging.getLogger(__name__)


class Deduplicator:
    def __init__(self, client):
        self._urls = client.get_existing_urls()

    def is_duplicate(self, url: str) -> bool:
        return url in self._urls

    def add_url(self, url: str) -> None:
        self._urls.add(url)

    def filter_new_items(self, items: list[dict]) -> list[dict]:
        new_items = [i for i in items if i.get("url") and not self.is_duplicate(i["url"])]
        skipped = len(items) - len(new_items)
        if skipped:
            log.debug(f"Dedup: skipped {skipped} duplicates, kept {len(new_items)}")
        return new_items
