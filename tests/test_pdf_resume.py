"""PDF resume upload: valid PDF parses, broken/empty files return the standard error shape."""
import os, sys
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "agents"))
from slate_api.app import create_app  # noqa: E402
from slate_core.resume import extract_pdf_text  # noqa: E402
from slate_core.resume import ParseError  # noqa: E402

LINES = ["Asha Verma", "B.Tech Computer Science, IIITM Gwalior, 2027",
         "Intern at ExampleCo (3 months)", "Skills: Python, Git, Excel, communication"]

def make_pdf(lines) -> bytes:
    """Minimal one-page PDF with real extractable text (Helvetica, no compression)."""
    def esc(t): return t.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
    ops = ["BT /F1 12 Tf 14 TL 72 720 Td"] + [f"({esc(l)}) Tj T*" for l in lines] + ["ET"]
    stream = "\n".join(ops).encode()
    objs = [b"<</Type/Catalog/Pages 2 0 R>>",
            b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
            b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
            b"<</Length %d>>stream\n%s\nendstream" % (len(stream), stream)]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, body)
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for off in offsets[1:]:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF" % (len(objs) + 1, xref)
    return bytes(out)

def test_extract_pdf_text_roundtrip():
    text = extract_pdf_text(make_pdf(LINES))
    assert "Asha Verma" in text and "Python" in text

def test_extract_rejects_garbage():
    with pytest.raises(ParseError):
        extract_pdf_text(b"this is not a pdf at all, just some long garbage bytes")

def test_extract_rejects_too_large():
    with pytest.raises(ParseError):
        extract_pdf_text(b"%PDF-1.4\n" + b"0" * (5 * 1024 * 1024 + 1))

@pytest.fixture()
def client():
    return TestClient(create_app())

def test_upload_valid_pdf_parses(client):
    r = client.post("/v1/resume/pdf", files={"file": ("resume.pdf", make_pdf(LINES), "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["resumeId"].startswith("res_")
    assert body["parsed"]["name"] == "Asha Verma"
    assert "python" in body["parsed"]["skills"]

def test_upload_broken_file_standard_error(client):
    r = client.post("/v1/resume/pdf", files={"file": ("notes.pdf", b"definitely not a pdf...........", "application/pdf")})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "resume_unreadable"

def test_uploaded_pdf_drives_matches(client):
    rid = client.post("/v1/resume/pdf",
                      files={"file": ("resume.pdf", make_pdf(LINES), "application/pdf")}).json()["resumeId"]
    r = client.get("/v1/jobs", params={"resumeId": rid})
    assert r.status_code == 200 and len(r.json()["jobs"]) > 0


def test_pdf_response_preserves_original_source_text_for_current_editor(client):
    response=client.post('/v1/resume/pdf', files={'file':('synthetic.pdf',make_pdf(LINES),'application/pdf')})
    assert response.status_code==200
    data=response.json()
    assert data['sourceTextKind']=='original_uploaded_text_not_user_addendum'
    assert data['sourceText']==extract_pdf_text(make_pdf(LINES))
    assert 'Asha Verma' in data['sourceText']
