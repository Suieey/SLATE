"""Synthetic finish/state/provider failure regressions, no live calls."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'agents'))
from slate_core.interview import InterviewStore,GeminiInterviewCoach
from slate_core.llm import MockLLM
from slate_core.ai_service import AISlateService
from slate_core.auth import DevAuth
from slate_core.user_store import SqlUserStore
from slate_api.app import create_authenticated_app
from fastapi.testclient import TestClient

def test_finished_legacy_session_cannot_accept_null_question():
 s=InterviewStore();s._sessions['old']={'role':'Data Analyst','questions':['Question?'],'answers':['A saved answer'],'carried':[]}
 with pytest.raises(ValueError,match='interview_ended'):s.answer('old','Another answer')
 assert len(s._sessions['old']['answers'])==1

def test_partial_state_marker_not_carried_as_a_weak_skill():
 s=InterviewStore();i=s.start('Data Analyst',[])['sessionId'];s.answer(i,'short');f=s.feedback(i)
 assert 'interview still in progress' in f['weakAreas']
 again=s.start('Data Analyst',s.past_feedback('Data Analyst'))
 assert again['carriedFromEarlier'] and 'interview still in progress' not in again['carriedFromEarlier']

@pytest.mark.parametrize('reply',['not JSON','{"score":"bad"}','{}'])
def test_malformed_provider_output_cannot_stop_fallback(reply):
 s=InterviewStore(coach=GeminiInterviewCoach(MockLLM(reply)));i=s.start('Data Analyst',[])['sessionId']
 r=s.answer(i,'I checked the SQL query and compared the results with the source data.')
 assert r['nextQuestion'] and 1<=r['evaluation']['score']<=5
 assert s.end(i)['ended']

def test_provider_failure_switches_to_honest_fallback():
 class Broken:
  def generate(self,prompt):raise TimeoutError('synthetic provider timeout')
 s=InterviewStore(coach=GeminiInterviewCoach(Broken()));started=s.start('Data Analyst',[])
 assert started['coachMode']=='deterministic_fallback'
 r=s.answer(started['sessionId'],'I checked a SQL query and validated the test results.')
 assert r['nextQuestion'] and s.end(started['sessionId'])['coachMode']=='deterministic_fallback'

def test_end_report_restart_and_account_isolation(tmp_path):
 url='sqlite:///'+str(tmp_path/'state.db')
 def client():return TestClient(create_authenticated_app(DevAuth(),SqlUserStore(url)))
 c=client();a={'Authorization':'Bearer dev:a@example.com'};b={'Authorization':'Bearer dev:b@example.com'}
 i=c.post('/v1/interview/mock',headers=a,json={'targetRole':'Human Resources','mode':'voice'}).json()['sessionId']
 assert c.post('/v1/interview/'+i+'/answer',headers=a,json={'text':'I checked employee policy and documented the complaint.'}).status_code==200
 assert c.post('/v1/interview/'+i+'/end',headers=b).status_code==404
 f=c.post('/v1/interview/'+i+'/end',headers=a).json();assert f['ended'] and f['answeredCount']==1
 c=client();assert c.get('/v1/interview/'+i+'/feedback',headers=a).json()['answerReviews'][0]['answer'].startswith('I checked')
 assert c.post('/v1/interview/'+i+'/answer',headers=a,json={'text':'extra'}).status_code==409
 assert c.post('/v1/interview/'+i+'/end',headers=a).json()['answeredCount']==1
 assert c.get('/v1/interview/'+i+'/feedback',headers=b).status_code==404
