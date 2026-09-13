"""End-to-end on the real dataset: every decision must pass the output contract."""
import unittest

from data.loader import Dataset
from main import run
from output.validate import COLUMNS

DATASET = Dataset()


class PipelineTest(unittest.TestCase):
    def test_every_sample_and_evaluation_request_is_valid(self):
        requests = DATASET.sample_requests + DATASET.requests
        rows, problems = run(DATASET, requests)
        self.assertEqual(problems, [])
        self.assertEqual([r["request_id"] for r in rows], [r.request_id for r in requests])
        self.assertTrue(all(tuple(r) == COLUMNS for r in rows))


if __name__ == "__main__":
    unittest.main()
