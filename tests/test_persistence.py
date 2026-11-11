import os, sys, tempfile
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
import pytest
pytest.importorskip("sqlalchemy")
from slate_core import SlateService, SlateError
from slate_core.persistence import SqlSnapshot

RESUME = "Asha Verma\nB.Tech Computer Science, IIITM Gwalior, 2027\nIntern at ExampleCo (3 months)\nSkills: Python, Git\n"

def test_state_survives_restart_including_approval_and_memory():
    url = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
    a = SlateService(SqlSnapshot(url))
    rid = a.upload_resume(RESUME)["resumeId"]
    d = a.tailor(rid, "job_001")["draftId"]
    a.decide(d, "approve")
    s1 = a.start_interview("Data Analyst")["sessionId"]
    a.answer_interview(s1, "short"); a.interview_feedback(s1)
    b = SlateService(SqlSnapshot(url))           # "restart"
    assert "coverNote" in b.export_draft(d)       # approval persisted
    assert b.start_interview("Data Analyst")["carriedFromEarlier"]   # interview memory persisted
    new_draft = b.tailor(rid, "job_002")["draftId"]
    assert new_draft != d                         # ids keep counting, no reuse
    with pytest.raises(SlateError):
        b.export_draft(new_draft)                 # gate still closed for the new draft

def test_empty_store_starts_clean():
    url = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "e.db")
    assert SlateService(SqlSnapshot(url)).jobs("analyst")["jobs"]
