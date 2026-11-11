"""Regression: the job-card template must escape jobId in the data-j attribute.

web/index.html is inline JS with no JS test runner in this repo, so this static
guard checks the template source. Browser before/after evidence accompanies the
change in the PR discussion."""
import os, unittest


class JobIdEscaping(unittest.TestCase):
    def test_job_id_is_escaped_in_template(self):
        with open(os.path.join(os.path.dirname(__file__), "..", "web", "index.html")) as f:
            html = f.read()
        self.assertIn('data-j="${esc(x.jobId)}"', html)


if __name__ == "__main__":
    unittest.main()
