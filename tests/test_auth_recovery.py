"""Guards for sign-in recovery after rejected/expired tokens on both pages."""
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('page',['index.html','ai.html'])
def test_401_rebuilds_login_controls_without_replaying_mutations(page):
    s=(ROOT/'web'/page).read_text()
    assert 'if(r.status===401){await recoverSignIn();throw new StaleResponse()}' in s
    assert 'authRecovery=initAuth().finally(' in s
    assert 'Your saved data is unchanged.' in s
    assert 'if(window.google?.accounts?.id){renderGoogle()}' in s
    assert 'google.accounts.id.disableAutoSelect()' in s
    assert 'script.id="google-identity-script"' in s

def test_pdf_upload_recovers_login_too():
    s=(ROOT/'web'/'index.html').read_text()
    assert 'if(res.status===401){await recoverSignIn();return}' in s

@pytest.mark.parametrize('page',['index.html','ai.html'])
def test_auth_epoch_clears_sensitive_ui_and_discards_old_responses(page):
    s=(ROOT/'web'/page).read_text()
    assert 'auth!==token()||generation!==sourceGeneration' in s
    assert 'function resetAccountState()' in s
    assert 'function signedIn(email){\n  resetAccountState();' in s
    assert 'catch(e){if(e instanceof StaleResponse)return;' in s
    assert 'sourceGeneration++' in s


def test_url_fragments_never_trigger_mutations_or_auto_decisions():
    s=(ROOT/'web'/'ai.html').read_text()
    assert 'location.hash' not in s
    assert 'setInterval(' not in s
    assert 'URL fragments never authorize' in s


@pytest.mark.parametrize('page',['index.html','ai.html'])
def test_draft_epoch_is_independent_of_source_epoch(page):
    html=(ROOT/'web'/page).read_text()
    assert 'draftGeneration' in html
    assert 'epoch!==draftGeneration' in html
    assert ('requested!==did' if page=='index.html' else 'requested!==draftId') in html
