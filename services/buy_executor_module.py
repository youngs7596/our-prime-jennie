# services/buy_executor_module.py
import sys
import os
import importlib.util

# Set up the path to the actual directory
current_dir = os.path.dirname(os.path.abspath(__file__))
# Note: In docker, it might be /app/services/buy-executor. Locally /home/.../services/buy-executor
target_dir = os.path.join(current_dir, 'buy-executor')

# Add target_dir to sys.path to allow sibling imports
if target_dir not in sys.path:
    sys.path.insert(0, target_dir)

# Import executor.py
pipeline_path = os.path.join(target_dir, 'executor.py')
spec = importlib.util.spec_from_file_location("buy_executor", pipeline_path)
buy_executor = importlib.util.module_from_spec(spec)
sys.modules["buy_executor"] = buy_executor
spec.loader.exec_module(buy_executor)
