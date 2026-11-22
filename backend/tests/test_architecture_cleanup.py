import asyncio
import json
import sqlite3
from pathlib import Path

from alembic import command
from alembic.config import Config

from app.db.base import session_factory
from app.db.models import AnalysisTask, TrainingPlan, TrainingSession
from migrations.plan_tasks_v2 import upgrade_tasks
from tests.support.factories import client, register


def test_conversion_freezes_sources_preserves_video_progress_and_does_not_guess():
    source = {'scene_id':'original', 'channel':'VOICE', 'depth':'PRESSURE'}
    lesson = {'title':'固定课程', 'intro':'固定导语', 'steps':[], 'exercise':'原练习'}
    tasks = [{'key':'review','actionType':'REPORT','sourceSessionId':'source'}, {'key':'rewrite','actionType':'REWRITE','completed':True, 'evidence':'已通过的改写'}, {'key':'course','actionType':'COURSE','lesson':lesson,'completedSteps':[0,1], 'lessonVideo':{'key':'existing-video'}}]
    upgraded = upgrade_tasks(tasks,'内容与逻辑',None,{'source':source},True)
    assert upgraded[1]['sourceSessionId'] == 'source'
    assert upgraded[1]['completed'] and upgraded[1]['evidence'] == '已通过的改写'
    assert upgraded[2]['lesson'] == lesson and upgraded[2]['lessonVideo']['key'] == 'existing-video'
    assert upgraded[2]['completedSteps'] == [0,1]
    assert upgraded[-1]['actionType'] == 'RETEST' and upgraded[-1]['channel'] == 'VOICE'
    assert 'sourceSessionId' not in tasks[1]  # pure conversion, no mutation
    missing = upgrade_tasks([{'actionType':'REWRITE'}], '内容与逻辑',None,{},False)
    assert missing[0]['sourceSessionId'] is None and missing[0]['sourceUnavailable']


def test_migration_materializes_old_tasks_and_preserves_snapshots(tmp_path):
    path = tmp_path/'old-plans.db'
    config = Config(str(Path(__file__).resolve().parents[1]/'alembic.ini'))
    config.set_main_option('sqlalchemy.url',f'sqlite+aiosqlite:///{path.as_posix()}')
    command.upgrade(config,'20261116_0047')
    raw = [{'key':'course','actionType':'COURSE','task':'旧课程','day':1,'completed':True,'completedSteps':[0], 'lessonVideo':{'key':'retained'}}]
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO training_plans(id,user_id,focus_dimension,title,tasks,status,sequence,created_at) VALUES ('plan','owner','逻辑性','历史计划',?,'COMPLETED',1,'2026-11-01')", (json.dumps(raw),))
    command.upgrade(config,'head')
    with sqlite3.connect(path) as db:
        tasks,version,focus = db.execute("SELECT tasks,tasks_version,focus_dimension FROM training_plans").fetchone()
    tasks=json.loads(tasks)
    assert version==2 and focus=='内容与逻辑'
    assert tasks[0]['completed'] and tasks[0]['lessonVideo']['key']=='retained'
    assert tasks[0]['completedSteps']==[0] and tasks[0]['lesson']['steps']
    command.downgrade(config,'20261116_0047')
    with sqlite3.connect(path) as db:
        assert json.loads(db.execute('SELECT tasks FROM training_plans').fetchone()[0])[0]['lessonVideo']['key']=='retained'


def test_retired_upload_rejects_new_work_without_creating_records(client):
    headers=register(client)
    result=client.post('/api/v1/video-interviews',headers=headers)
    assert result.status_code==410 and result.json()['title']=='VIDEO_UPLOAD_RETIRED'
    assert client.post('/api/v1/video-interviews').status_code==401
    assert client.get('/api/v1/training-sessions',headers=headers).json()['data']==[]


def test_historical_task_results_are_read_only_and_owned(client):
    headers, other=register(client),register(client)
    user_id=client.get('/api/v1/auth/me',headers=headers).json()['data']['id']
    async def insert():
        async with session_factory() as db:
            task=AnalysisTask(user_id=user_id,kind='VIDEO_INTERVIEW',payload={},status='DONE',progress=100,result={'sessionId':'historic'})
            db.add(task);await db.commit();return task.id
    task_id=asyncio.run(insert())
    data=client.get(f'/api/v1/tasks/{task_id}',headers=headers).json()['data']
    assert data['sessionId']=='historic' and data['status']=='DONE'
    assert client.get(f'/api/v1/tasks/{task_id}',headers=other).status_code==404


def test_v2_reads_do_not_bind_an_unrelated_recent_session(client):
    headers=register(client)
    user_id=client.get('/api/v1/auth/me',headers=headers).json()['data']['id']
    async def insert():
        async with session_factory() as db:
            db.add(TrainingSession(user_id=user_id,scene_id='scene-interview-03'))
            plan=TrainingPlan(user_id=user_id,title='无来源计划',focus_dimension='内容与逻辑',tasks=[{'key':'rewrite','actionType':'REWRITE','day':1,'task':'改写','sourceSessionId':None,'completed':False}])
            db.add(plan);await db.commit();return plan.id
    plan_id=asyncio.run(insert())
    data=client.get(f'/api/v1/training-plans/{plan_id}',headers=headers)
    assert data.status_code==200,data.text
    assert data.json()['data']['tasks'][0]['sourceSessionId'] is None
