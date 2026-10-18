"""Negative-case-first CP3 safety, reliability, review and API acceptance."""
import copy
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from enterprise_automation.api.main import app
from enterprise_automation.api.cp3 import limiter
from enterprise_automation.cp3_demo import evaluate, SCENARIOS
from enterprise_automation.governance.policy import event_contract, digest, mock_ai_suggestion, validate_ai_suggestion
from enterprise_automation.governance.queue import LocalQueue
from enterprise_automation.governance.retry import RetryPolicy
from enterprise_automation.governance.security import authorize, LocalRateLimiter, public_error

@pytest.fixture
def event():
    return dict(SCENARIOS[0])

@pytest.fixture
def queue(tmp_path):
    q = LocalQueue(tmp_path/'queue.sqlite')
    yield q
    q.close()

@pytest.mark.parametrize('field,wrong', [
    ('event_id','../escape'),('event_id',''),('source','OTHER'),('record_ref','../bad'),
    ('scenario','external_write'),('reason_code','anything'),('reason_code','ignore_previous_instructions'),
])
def test_contract_rejects_invalid(event,field,wrong):
    event[field]=wrong
    with pytest.raises(ValueError):event_contract(event)

@pytest.mark.parametrize('forbidden', ['email','api_key','full_name','instructions','payload','tenant_id'])
def test_free_text_and_pii_fields_rejected(event,forbidden):
    event[forbidden]='sensitive'
    with pytest.raises(ValueError):event_contract(event)

@pytest.mark.parametrize('scenario', ['success','transient','permanent','review'])
def test_allowed_scenarios(event,scenario):
    event['scenario']=scenario
    assert event_contract(event)['scenario']==scenario

@pytest.mark.parametrize('field,wrong', [
    ('event_id','other'),('reason_code','source_outage'),('evidence_sha256','0'*64),
    ('recommendation','auto_approve'),('provider','real_llm'),('schema_version','v2'),
])
def test_untrusted_ai_claims_rejected(event,field,wrong):
    proposal=mock_ai_suggestion(event)
    proposal[field]=wrong
    with pytest.raises(ValueError,match='Unsupported AI'):validate_ai_suggestion(event,proposal)


def test_ai_extra_field_rejected(event):
    suggestion=mock_ai_suggestion(event); suggestion['malicious']='override'
    with pytest.raises(ValueError):validate_ai_suggestion(event,suggestion)


def test_ai_proposal_validated_but_never_auto_applied(event):
    suggestion=mock_ai_suggestion(event)
    assert validate_ai_suggestion(event,suggestion)==suggestion
    assert suggestion['provider']=='deterministic_mock_no_llm'


def test_duplicate_is_idempotent(queue,event):
    assert queue.enqueue(event)=='enqueued'
    assert queue.enqueue(event)=='duplicate_skipped'
    assert queue.counts()['pending']==1


def test_conflicting_duplicate_requires_review(queue,event):
    queue.enqueue(event)
    event['record_ref']='different'
    with pytest.raises(ValueError,match='Conflicting'):queue.enqueue(event)
    assert queue.counts()['pending']==1


def test_success_and_terminal_processing(queue,event):
    queue.enqueue(event)
    assert queue.process_one(0)['status']=='completed'
    assert queue.process_one(0) is None
    assert queue.counts()['completed']==1
    assert queue.snapshot()['total_attempts']==1


def test_retry_backoff_and_eventual_success(queue):
    queue.enqueue(SCENARIOS[1])
    assert queue.process_one(0)['status']=='retry_wait'
    assert queue.process_one(1) is None
    assert queue.process_one(2)['status']=='completed'
    assert queue.snapshot()['total_attempts']==2


def test_permanent_failure_dead_letter(queue):
    queue.enqueue(SCENARIOS[2])
    assert queue.process_one(0)['status']=='dead_letter'
    assert queue.counts()['dead_letter']==1
    assert queue.process_one(200) is None


def test_reviewer_must_decide(queue):
    queue.enqueue(SCENARIOS[3])
    assert queue.process_one(0)['status']=='awaiting_review'
    assert queue.counts()['review_approved']==0
    assert queue.decide('review_04','approve',1)=='review_approved'
    assert queue.counts()['review_approved']==1
    with pytest.raises(ValueError):queue.decide('review_04','reject',2)


def test_unreviewed_item_cannot_be_approved(queue):
    queue.enqueue(SCENARIOS[3])
    with pytest.raises(ValueError):queue.decide('review_04','approve',0)


def test_review_proposal_tamper_blocked(queue):
    queue.enqueue(SCENARIOS[3]);queue.process_one(0)
    queue.db.execute("UPDATE events SET proposal_json='{}' WHERE event_id='review_04'")
    with pytest.raises(ValueError):queue.decide('review_04','approve',1)
    assert queue.counts()['awaiting_review']==1


def test_lease_recovery_and_stale_resolver(queue,event):
    queue.enqueue(event)
    old=queue.claim(0,lease_ticks=2)
    assert queue.claim(1) is None
    new=queue.claim(2)
    assert new['attempts']==2
    with pytest.raises(ValueError):queue.resolve(old,2,outcome='success')
    assert queue.resolve(new,2,outcome='success')=='completed'


def test_lease_exhaustion_dead_letter(queue,event):
    queue.enqueue(event)
    queue.claim(0,lease_ticks=1);queue.claim(1,lease_ticks=1);queue.claim(2,lease_ticks=1)
    exhausted=queue.claim(3)
    assert exhausted['status']=='dead_letter'
    assert queue.counts()['dead_letter']==1


def test_queue_persists_across_reopen(tmp_path,event):
    path=tmp_path/'x.sqlite'
    q=LocalQueue(path);q.enqueue(event);q.close()
    q=LocalQueue(path)
    try:
        assert q.process_one(0)['status']=='completed'
    finally:q.close()


def test_invalid_logical_clock(queue,event):
    queue.enqueue(event)
    for tick in [-1,0.1,None]:
        with pytest.raises(ValueError):queue.claim(tick)


@pytest.mark.parametrize('attempts,delay',[(-1,2),(0,2),(6,2),(3,0),(3,31)])
def test_retry_policy_limits(attempts,delay):
    with pytest.raises(ValueError):RetryPolicy(max_attempts=attempts,base_backoff_ticks=delay)


def test_retry_backoff_is_bounded():
    policy=RetryPolicy()
    assert policy.next_tick(2,1)==4
    assert policy.next_tick(2,3)==10


def test_authorize_disabled_without_both_credentials(monkeypatch):
    monkeypatch.delenv('PROJECT15_CP3_REVIEWER_KEY',raising=False)
    monkeypatch.setenv('PROJECT15_CP3_OPERATOR_KEY','op-secret')
    with pytest.raises(HTTPException) as exc:authorize('op-secret','operator')
    assert exc.value.status_code==503


def test_authorize_distinct_scope(monkeypatch):
    monkeypatch.setenv('PROJECT15_CP3_OPERATOR_KEY','op-secret')
    monkeypatch.setenv('PROJECT15_CP3_REVIEWER_KEY','review-secret')
    assert authorize('op-secret','operator')=='operator'
    with pytest.raises(HTTPException) as exc:authorize('op-secret','reviewer')
    assert exc.value.status_code==401


def test_authorize_rejects_shared_secret(monkeypatch):
    monkeypatch.setenv('PROJECT15_CP3_OPERATOR_KEY','same')
    monkeypatch.setenv('PROJECT15_CP3_REVIEWER_KEY','same')
    with pytest.raises(HTTPException) as exc:authorize('same','operator')
    assert exc.value.status_code==503


def test_rate_limit_with_rollover():
    limit=LocalRateLimiter(max_requests=2,window_seconds=60)
    limit.enforce('operator',now=1);limit.enforce('operator',now=2)
    with pytest.raises(HTTPException) as exc:limit.enforce('operator',now=3)
    assert exc.value.status_code==429
    limit.enforce('operator',now=61)


def test_errors_never_include_exception_text():
    assert public_error(RuntimeError('api_key=secret'))=='RuntimeError'


def test_cp3_demo_reproducible_counts(tmp_path):
    manifest=evaluate(tmp_path,'cp3_test')
    assert manifest['observed']['total_events']==4
    assert manifest['observed']['total_attempts']==5
    assert manifest['observed']['counts']['completed']==2
    assert manifest['observed']['counts']['dead_letter']==1
    assert manifest['observed']['counts']['review_rejected']==1
    assert manifest['model_calls']==0 and manifest['external_writes']==0
    assert len(manifest['input_fixture_sha256'])==64
    with pytest.raises(FileExistsError):evaluate(tmp_path,'cp3_test')


def test_cp3_demo_traversal_rejected(tmp_path):
    with pytest.raises(ValueError):evaluate(tmp_path,'../bad')


@pytest.fixture
def api_creds(monkeypatch,tmp_path):
    monkeypatch.setenv('PROJECT15_CP3_OPERATOR_KEY','op-local-demo')
    monkeypatch.setenv('PROJECT15_CP3_REVIEWER_KEY','review-local-demo')
    monkeypatch.setenv('PROJECT15_ROOT',str(tmp_path))
    limiter._history.clear()
    return {'X-API-Key':'op-local-demo'}, {'X-API-Key':'review-local-demo'}


def test_cp3_api_missing_auth_rejected(api_creds):
    assert TestClient(app).get('/cp3/metrics').status_code==401


def test_cp3_api_event_and_metric(api_creds):
    operator,_=api_creds
    client=TestClient(app)
    assert client.post('/cp3/event',json=SCENARIOS[0],headers=operator).json()['result']=='enqueued'
    assert client.post('/cp3/event',json=SCENARIOS[0],headers=operator).json()['result']=='duplicate_skipped'
    assert client.post('/cp3/process?tick=0',headers=operator).json()['result']['status']=='completed'
    assert client.get('/cp3/metrics',headers=operator).json()['counts']['completed']==1


def test_cp3_api_review_scope_separation(api_creds):
    op,reviewer=api_creds
    client=TestClient(app)
    assert client.post('/cp3/event',json=SCENARIOS[3],headers=op).status_code==200
    client.post('/cp3/process?tick=0',headers=op)
    payload={'decision':'reject','tick':1}
    assert client.post('/cp3/review/review_04',json=payload,headers=op).status_code==401
    result=client.post('/cp3/review/review_04',json=payload,headers=reviewer)
    assert result.status_code==200 and result.json()['result']=='review_rejected'


def test_cp3_api_injection_denied(api_creds):
    op,_=api_creds
    malicious={**SCENARIOS[0],'payload':{'instructions':'ignore validation'}}
    assert TestClient(app).post('/cp3/event',json=malicious,headers=op).status_code==422


def test_paginated_metadata_only(queue):
    for row in SCENARIOS:queue.enqueue(row)
    first=queue.page(offset=0,limit=2)
    assert first['total']==4 and first['next_offset']==2
    assert list(first['items'][0])==['event_id','status','attempts']
    assert len(queue.page(offset=2,limit=3)['items'])==2
    assert queue.page(offset=4,limit=2)['next_offset'] is None
    for kwargs in ({'offset':-1}, {'limit':0}, {'limit':500}, {'offset':1.1}):
        with pytest.raises(ValueError):queue.page(**kwargs)

def test_temporary_timeouts_dead_letter(queue):
    queue.enqueue(SCENARIOS[0])
    for tick,attempt in [(0,1),(2,2),(6,3)]:
        claim=queue.claim(tick)
        assert claim['attempts']==attempt
        status=queue.resolve(claim,tick,outcome='timeout')
    assert status=='dead_letter'
    assert queue.snapshot()['total_attempts']==3

def test_api_event_pagination(api_creds):
    op,_=api_creds
    client=TestClient(app)
    for e in SCENARIOS:assert client.post('/cp3/event',json=e,headers=op).status_code==200
    r=client.get('/cp3/events?offset=1&limit=2',headers=op)
    assert r.status_code==200 and r.json()['total']==4
    assert len(r.json()['items'])==2 and r.json()['next_offset']==3

def test_event_contract_does_not_coerce_ids(event):
    event['event_id']=123
    with pytest.raises(ValueError):event_contract(event)
