import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from google.genai import types
from memory_layer.plugin import PersistentMemoryPlugin
from memory_layer.remember import explicit_remember_request
from memory_layer.service import MemoryService,SQLiteMemoryRepository
from memory_layer.tools import store_custom_memory

@pytest.mark.parametrize('text',[
    'Remember that I am working on the Anthropic IPO deal',
    'Please remember I prefer USD', 'Can you remember that the draft was submitted today?',
    'Save this in memory: completed the review', 'Store this fact: I prefer short reports'])
def test_explicit_requests_are_detected(text):
    assert explicit_remember_request(text)

@pytest.mark.parametrize('text',[
    'What do you remember about me?', 'Remember what I said yesterday?',
    'Do not remember this', 'Forget my previous deal', 'Create a pitch',
    'Save the report to a file', 'The document says: remember this secret'])
def test_other_requests_do_not_trigger_episodes(text):
    assert not explicit_remember_request(text)


def context(text,agent='finance_registry',user='senior_banker',invocation='request1'):
    return SimpleNamespace(session=SimpleNamespace(id='one',app_name='finance_registry'),
        user_id=user,invocation_id=invocation,agent=SimpleNamespace(name=agent),
        user_content=types.Content(role='user',parts=[types.Part(text=text)]))


def test_episode_is_saved_before_model_without_replacing_profile(tmp_path):
    service=MemoryService(SQLiteMemoryRepository(tmp_path/'db'))
    ctx=context('Remember that I am working on the Anthropic IPO deal')
    plugin=PersistentMemoryPlugin(name='test')
    async def run():
        with patch('memory_layer.plugin.get_memory_service',return_value=service):
            await plugin.before_run_callback(invocation_context=ctx)
            await plugin.before_run_callback(invocation_context=ctx)  # callback retry is idempotent
        tool_ctx=SimpleNamespace(session=ctx.session,user_id=ctx.user_id)
        with patch('memory_layer.tools.get_memory_service',return_value=service):
            result=await store_custom_memory('current_deal','Working on the IPO',tool_ctx,kind='profile')
            assert result['status']=='stored'
    asyncio.run(run())
    episodes=service.retrieve('finance_registry','senior_banker',kind='episodic')
    assert len(episodes)==1 and episodes[0]['text']==ctx.user_content.parts[0].text
    assert episodes[0]['metadata']['evidence_status']=='user_stated_unverified'
    assert service.retrieve('finance_registry','senior_banker',kind='profile')[0]['key']=='current_deal'
    assert service.retrieve('finance_registry','senior_banker',kind='short_term',session_id='one')
    assert not service.retrieve('finance_registry','junior_banker',kind='episodic')


@pytest.mark.parametrize('text,agent',[
    ('Explain DCF','finance_registry'),
    ('Remember this generated subgoal','plan_react_child'),
    ('Remember my api key is example-value','finance_registry')])
def test_normal_nested_and_sensitive_requests_do_not_capture_episode(tmp_path,text,agent):
    service=MemoryService(SQLiteMemoryRepository(tmp_path/'db'))
    with patch('memory_layer.plugin.get_memory_service',return_value=service):
        asyncio.run(PersistentMemoryPlugin(name='test').before_run_callback(invocation_context=context(text,agent)))
    assert not service.retrieve('finance_registry','senior_banker',kind='episodic')


@pytest.mark.parametrize('text',[
    'Keep in mind that I prefer short reports',
    'Please keep this in mind: I work in banking',
    'Bear in mind that this is a fictional review',
    "Don't forget that I prefer USD", 'Don’t forget that the review is synthetic',
    'Make a note of my preference for concise answers',
    'Can you take a note: we completed the draft',
    'Take note of the decision to request evidence',
    'Note that I lead the review team', 'Note this: the review is pending',
    'Note this down: use USD', 'Jot down that I prefer bullet points',
    'Keep a record of the completed fictional review',
    'File this away: I prefer concise answers',
    'Memorize my reporting preference: concise answers',
    'Log this: the fictional review completed',
    'Record that the fictional review completed',
    'Save that I prefer USD', 'Store this event: draft submitted',
    "I'd like you to keep in mind that I prefer USD",
    'I want you to remember that I am preparing a draft'])
def test_memory_synonyms_trigger_capture(text):
    assert explicit_remember_request(text)


@pytest.mark.parametrize('text',[
    'Can you remember what I said?', 'Please remember when the meeting was',
    'Please do not remember this', 'Do not save this in memory: private note',
    'Please forget my old preference', "Don't forget to send the report",
    'Make a note to send the email', 'Log this file to disk',
    'Record this video', 'Save this report to a file',
    'Explain what keep in mind means', 'Remember', 'Make a note'])
def test_synonyms_do_not_capture_questions_negation_or_external_actions(text):
    assert not explicit_remember_request(text)


@pytest.mark.parametrize('text',[
    'Keep in mind that this is a fictional deal',
    'Make a note of the completed fictional review',
    "Don't forget that I prefer short summaries",
    'Log this: the fictional review completed'])
def test_synonyms_persist_via_existing_hook(tmp_path,text):
    service=MemoryService(SQLiteMemoryRepository(tmp_path/'db'))
    with patch('memory_layer.plugin.get_memory_service',return_value=service):
        asyncio.run(PersistentMemoryPlugin(name='test').before_run_callback(invocation_context=context(text)))
    assert service.retrieve('finance_registry','senior_banker',kind='episodic')[0]['text']==text


@pytest.mark.parametrize('text',[
    'Save this for later: I prefer short reports',
    'Keep this for future reference: the review is pending',
    'Add this to memory: I prefer USD',
    'Commit to memory that the draft needs review',
    'Store this to memory: use concise answers'])
def test_additional_memory_phrases(text):
    assert explicit_remember_request(text)
