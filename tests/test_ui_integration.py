"""Static guards for the small auth/jobs/roadmap UI integration."""
from pathlib import Path
HTML = (Path(__file__).resolve().parents[1] / 'web' / 'index.html').read_text()

def test_freshness_discloses_fixture_meaning_beside_state():
    assert 'Demo fixture: ${esc(x.freshness||"unknown")} (not live-verified)' in HTML

def test_match_reason_and_job_id_are_escaped():
    assert '${esc(x.reason||"")}' in HTML
    assert 'data-j="${esc(x.jobId)}"' in HTML

def test_roadmap_resources_remain_https_links():
    assert 'm.resources.map(resLink)' in HTML
    assert 'rel="noopener noreferrer"' in HTML
    assert r'/^https:\/\//' in HTML

def test_auth_still_covers_json_and_pdf_requests():
    assert 'h["authorization"]="Bearer "+token()' in HTML
    assert 'ph["authorization"]="Bearer "+token()' in HTML

def test_dedicated_interview_page_has_voice_and_resume_controls():
    page=(Path(__file__).resolve().parents[1]/"web"/"interview.html").read_text()
    assert 'fetch("/v1"+path' in page
    assert 'mode:sessionMode' in page
    assert 'resumeId:$("resume").value||null' in page
    assert 'SpeechRecognition||window.webkitSpeechRecognition' in page
    assert 'answerReviews' in page or 'fb.answerReviews' in page


def test_interview_ui_has_camera_voice_delivery_and_manual_end_controls():
    page=(Path(__file__).resolve().parents[1]/"web"/"interview.html").read_text()
    assert 'getUserMedia({video:' in page
    assert 'MediaRecorder' in page
    assert 'measureDelivery' in page
    assert 'pitchRangeHz' in page
    assert 'deliveryMetrics' in page
    assert '"/end"' in page
    assert 'id="endInterview"' in page
    assert 'No video is uploaded or recorded' in page


def test_every_workspace_part_has_a_distinct_route_and_nav():
    for part in ('resume','targets','draft','comparisons','roadmap'):
        assert 'data-part="'+part+'"' in HTML
    assert 'pageParts={resume:["s1"],targets:["targetWorkspace"],draft:["s3"],comparisons:["s2"],roadmap:["s4"]}' in HTML
    assert 'crypto.subtle.digest("SHA-256",bytes)' in HTML
    assert 'beforeunload' in HTML
