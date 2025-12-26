# services/scout_job_module.py
import sys
import os
import importlib.util

# Set up the path to the actual scout-job directory
current_dir = os.path.dirname(os.path.abspath(__file__))
scout_job_dir = os.path.join(current_dir, 'scout-job')

# Add scout_job_dir to sys.path to allow sibling imports (e.g., scout_cache)
if scout_job_dir not in sys.path:
    sys.path.insert(0, scout_job_dir)

# Import scout_pipeline
pipeline_path = os.path.join(scout_job_dir, 'scout_pipeline.py')
spec = importlib.util.spec_from_file_location("scout_pipeline", pipeline_path)
scout_pipeline = importlib.util.module_from_spec(spec)
sys.modules["scout_pipeline"] = scout_pipeline
spec.loader.exec_module(scout_pipeline)

# Import scout
scout_path = os.path.join(scout_job_dir, 'scout.py')
spec_scout = importlib.util.spec_from_file_location("scout", scout_path)
scout = importlib.util.module_from_spec(spec_scout)
sys.modules["scout"] = scout
spec_scout.loader.exec_module(scout)
