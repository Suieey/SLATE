from fastapi.testclient import TestClient
from slate_api.app import create_app
from slate_core.service import SlateService

def test_all_part_urls_are_real_server_routes():
    c=TestClient(create_app(SlateService()))
    for route in ('/','/resume','/targets','/draft','/comparisons','/roadmap'):
        r=c.get(route)
        assert r.status_code==200 and 'id="targetWorkspace"' in r.text and 'routePage(activePart,true)' in r.text
