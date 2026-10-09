"""Indexed native evidence with bounded pages; original records remain intact."""
import json
from .inspection import read_drc_report

PAGE_SIZE = 200
TEXT_LIMIT = 64000


def report_excerpt(value, location='the validation log in the exported review folder'):
    if len(value) <= TEXT_LIMIT:
        return value
    return value[:TEXT_LIMIT] + '\n\nDisplay shortened. Full report: ' + location


class ReportPages:
    def __init__(self, records):
        self.records = records
        self._search = [json.dumps(record).lower() for record in records]
        self._matches = list(range(len(records)))
        self.page = 0

    @classmethod
    def from_native(cls, data):
        return cls(read_drc_report(data))

    def filter(self, query):
        query = query.lower()
        self._matches = [i for i, value in enumerate(self._search) if query in value]
        self.page = 0

    @property
    def count(self):
        return len(self._matches)

    @property
    def page_count(self):
        return max(1, (self.count + PAGE_SIZE - 1) // PAGE_SIZE)

    def move(self, offset):
        self.page = max(0, min(self.page + offset, self.page_count - 1))

    def rows(self):
        start = self.page * PAGE_SIZE
        return [self.records[i] for i in self._matches[start:start + PAGE_SIZE]]
