# tests/services/scheduler-service/test_scheduler.py

import unittest
try:
    import pytest
except ImportError:
    pytest = None

# unittest discover 시 pytest 없으면 전체 모듈 스킵
if pytest is None:
    raise unittest.SkipTest("pytest not installed, skipping pytest-based tests")
from unittest.mock import MagicMock, patch, ANY
import sys
import os
import importlib.util
from datetime import datetime, timezone, timedelta

# Project Root Setup
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../"))
# sys.path.insert(0, PROJECT_ROOT)

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# Setup mocks before importing main
# Use unique DB path per process to avoid race conditions in xdist
os.environ["SCHEDULER_DB_PATH"] = f"/tmp/test_scheduler_{os.getpid()}.db"

with patch('shared.messaging.trading_signals.TradingSignalPublisher'), \
     patch('apscheduler.schedulers.background.BackgroundScheduler'):
    
    # Dynamic import of scheduler-service main
    SCHEDULER_DIR = os.path.join(PROJECT_ROOT, 'services', 'scheduler-service')
    SCHEDULER_PATH = os.path.join(SCHEDULER_DIR, 'main.py')

    spec = importlib.util.spec_from_file_location("scheduler_main", SCHEDULER_PATH)
    scheduler_main = importlib.util.module_from_spec(spec)
    sys.modules["services.scheduler_service.main"] = scheduler_main
    spec.loader.exec_module(scheduler_main)

from services.scheduler_service.main import app, get_db, Job, Base

# Setup In-Memory DB for testing
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}, 
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

@pytest.fixture(scope="function")
def db_session():
    # Ensure clean slate
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)

@pytest.fixture(scope="function")
def client(db_session):
    def override_get_db():
        try:
            yield db_session
        finally:
            pass
    
    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()

class TestSchedulerService:

    def test_health_check(self, client):
        """Test /health endpoint"""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_create_and_list_jobs(self, client):
        """Test Creating and Listing Jobs"""
        payload = {
            "job_id": "test-job-1",
            "description": "Test Description",
            "queue": "test.queue",
            "cron_expr": "*/5 * * * *",
            "enabled": True,
            "reschedule_mode": "scheduler",
            "timeout_sec": 60
        }
        
        # Create
        response = client.post("/jobs", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["job_id"] == "test-job-1"
        assert data["cron_expr"] == "*/5 * * * *"

        # List
        response = client.get("/jobs")
        assert response.status_code == 200
        jobs = response.json()
        assert len(jobs) >= 1
        assert jobs[0]["job_id"] == "test-job-1"

    def test_manual_trigger(self, client):
        """Test manually triggering a job"""
        # Create job first
        payload = {
            "job_id": "manual-job",
            "queue": "test.queue",
            "cron_expr": "0 0 * * *",
            "enabled": True
        }
        client.post("/jobs", json=payload)

        # Trigger run
        run_payload = {"trigger_source": "manual-test"}
        
        # Import main module to patch object
        # Get main module from sys.modules
        scheduler_main_mod = sys.modules["services.scheduler_service.main"]
        
        with patch.object(scheduler_main_mod, "get_publisher") as mock_pub:
            mock_publisher_instance = MagicMock()
            mock_pub.return_value = mock_publisher_instance
            mock_publisher_instance.publish.return_value = "msg-id-123"
            
            response = client.post("/jobs/manual-job/run", json=run_payload)
            
            assert response.status_code == 200
            assert response.json()["message_id"] == "msg-id-123"
            mock_publisher_instance.publish.assert_called_once()

    def test_job_update(self, client):
        """Test updating a job"""
        # Create
        client.post("/jobs", json={
            "job_id": "update-job",
            "queue": "q1",
            "cron_expr": "0 0 * * *"
        })
        
        # Update
        update_payload = {"description": "Updated Desc", "enabled": False}
        response = client.put("/jobs/update-job", json=update_payload)
        
        assert response.status_code == 200
        data = response.json()
        assert data["description"] == "Updated Desc"
        assert data["enabled"] is False

    def test_scheduler_cycle(self, db_session):
        """Test run_scheduler_cycle logic"""
        from services.scheduler_service.main import run_scheduler_cycle, Job
        scheduler_main_mod = sys.modules["services.scheduler_service.main"]
        
        # Determine current time
        # We need to make sure the job looks DUE
        now = datetime.now(timezone.utc)
        
        # Create a job that was run a long time ago (or never)
        job = Job(
            job_id="cycle-job",
            scope="real", # Must match SCHEDULER_SCOPE env default
            queue="cycle.queue",
            cron_expr="* * * * *", # Every minute
            enabled=True,
            reschedule_mode="scheduler",
            last_run_at=now - timedelta(minutes=5), # 5 mins ago
            next_due_at=now - timedelta(minutes=4)  # Overdue
        )
        db_session.add(job)
        db_session.commit()
        
        mock_instance = MagicMock()
        
        # Override SessionLocal used in run_scheduler_cycle to return our test session
        # We need to construct a mock that behaves like a context manager returning db_session
        mock_session_factory = MagicMock()
        mock_session_factory.return_value.__enter__.return_value = db_session
        mock_session_factory.return_value.__exit__.return_value = None

        with patch.object(scheduler_main_mod, "SessionLocal", mock_session_factory), \
             patch.object(scheduler_main_mod, "get_publisher", return_value=mock_instance):
            
            run_scheduler_cycle()
            
            # Should have published
            mock_instance.publish.assert_called()
            
            # Verify job updated
            db_session.refresh(job)
            assert job.last_status == "queued"
            
            last_run = job.last_run_at
            if last_run and last_run.tzinfo is None:
                last_run = last_run.replace(tzinfo=timezone.utc)
            
            assert last_run > now - timedelta(seconds=10) # Recently updated
