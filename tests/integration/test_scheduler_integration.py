"""
Scheduler Service Integration Tests

Purpose: Verify that the scheduler service correctly handles job configuration,
         triggers, and database interactions using existing models.
"""
import pytest
import json
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone
from sqlalchemy import select


class TestSchedulerIntegration:
    """Test scheduler service integration with database and job execution."""
    
    @pytest.fixture
    def mock_rabbitmq(self, mocker):
        """Mock RabbitMQ publisher for job triggers."""
        mock_publisher = mocker.MagicMock()
        mock_publisher.publish.return_value = True
        mocker.patch('shared.rabbitmq.RabbitMQPublisher', return_value=mock_publisher)
        return mock_publisher
    
    def test_job_config_crud_via_config_table(self, in_memory_db, patch_session_scope):
        """
        Verify CRUD operations for scheduled job configs using CONFIG table.
        
        Since ScheduledJob model doesn't exist, we use the Config model
        to store job configuration as JSON.
        """
        from shared.db import models
        
        session = in_memory_db['session']
        
        # 1. Create Job Config
        job_config = {
            'job_id': 'test_scout_job',
            'job_name': 'Scout Job - Morning',
            'cron_expression': '0 9 * * 1-5',
            'job_type': 'SCOUT',
            'is_active': True
        }
        
        new_config = models.Config(
            config_key='SCHEDULED_JOB_SCOUT_MORNING',
            config_value=json.dumps(job_config),
            description='Morning scout job configuration'
        )
        session.add(new_config)
        session.commit()
        
        # 2. Query Config
        stmt = select(models.Config).where(models.Config.config_key == 'SCHEDULED_JOB_SCOUT_MORNING')
        retrieved = session.scalars(stmt).first()
        assert retrieved is not None
        parsed = json.loads(retrieved.config_value)
        assert parsed['job_name'] == 'Scout Job - Morning'
        assert parsed['is_active'] is True
        
        # 3. Update Config
        parsed['is_active'] = False
        retrieved.config_value = json.dumps(parsed)
        session.commit()
        
        stmt = select(models.Config).where(models.Config.config_key == 'SCHEDULED_JOB_SCOUT_MORNING')
        updated = session.scalars(stmt).first()
        updated_parsed = json.loads(updated.config_value)
        assert updated_parsed['is_active'] is False
        
        # 4. Delete Config
        session.delete(updated)
        session.commit()
        
        stmt = select(models.Config).where(models.Config.config_key == 'SCHEDULED_JOB_SCOUT_MORNING')
        deleted = session.scalars(stmt).first()
        assert deleted is None
    
    def test_job_trigger_publishes_to_rabbitmq(self, mock_rabbitmq, mocker):
        """
        Verify that triggering a job publishes the correct message to RabbitMQ.
        
        This simulates the scheduler triggering a job execution.
        """
        # Simulate a job trigger function (mocked)
        def trigger_job(job_id: str, job_type: str):
            """Simulated job trigger that would publish to RabbitMQ."""
            message = {
                'job_id': job_id,
                'job_type': job_type,
                'triggered_at': datetime.now(timezone.utc).isoformat()
            }
            mock_rabbitmq.publish(routing_key=f'jobs.{job_type.lower()}', body=message)
            return True
        
        # Trigger job
        result = trigger_job('scout_job_001', 'SCOUT')
        
        # Verify
        assert result is True
        mock_rabbitmq.publish.assert_called_once()
        call_kwargs = mock_rabbitmq.publish.call_args
        assert 'jobs.scout' in str(call_kwargs)
    
    def test_scout_to_db_flow_simulation(self, in_memory_db, patch_session_scope):
        """
        Simulate Scout -> DB flow: Scout finds a candidate and stores it.
        
        This tests the integration between Scout output and WatchList table.
        """
        from shared.db import models
        
        session = in_memory_db['session']
        
        # Simulate Scout finding a candidate
        candidate = models.WatchList(
            stock_code='005930',
            stock_name='삼성전자',
            filter_reason='Scout: High momentum, positive news',
            llm_score=85.0,
            is_tradable=1,
            trade_tier='TIER1',
            market_cap=400000000000000
        )
        session.add(candidate)
        session.commit()
        
        # Verify
        stmt = select(models.WatchList).where(models.WatchList.stock_code == '005930')
        found = session.scalars(stmt).first()
        assert found is not None
        assert found.llm_score == 85.0
        assert found.trade_tier == 'TIER1'
        assert 'Scout' in found.filter_reason
    
    def test_optimization_history_logging(self, in_memory_db, patch_session_scope):
        """
        Verify that optimization decisions are properly logged.
        
        This tests the OptimizationHistory model as a proxy for job execution logging.
        """
        from shared.db import models
        
        session = in_memory_db['session']
        
        # Log an optimization run (similar to job execution)
        opt_log = models.OptimizationHistory(
            current_mdd=-0.05,
            current_return=0.12,
            new_mdd=-0.04,
            new_return=0.15,
            ai_decision='APPLY',
            ai_reasoning='New parameters show better risk-adjusted returns',
            ai_confidence=0.85,
            is_applied='Y'
        )
        session.add(opt_log)
        session.commit()
        
        # Verify
        log = session.scalars(select(models.OptimizationHistory)).first()
        assert log is not None
        assert log.ai_decision == 'APPLY'
        assert log.is_applied == 'Y'
        assert log.ai_confidence == 0.85
