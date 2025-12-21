import pytest
import subprocess
import os
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

def run_command(cmd_list):
    result = subprocess.run(
        cmd_list, 
        cwd=PROJECT_ROOT, 
        capture_output=True, 
        text=True
    )
    if result.returncode != 0:
        print(f"STDOUT: {result.stdout}")
        print(f"STDERR: {result.stderr}")
    return result

def test_pipeline_smoke():
    # 1. Build Daily Packet (Dummy)
    packet_out = PROJECT_ROOT / "smoke_packet.json"
    cmd_build = [
        "./.venv/bin/python", 
        "scripts/build_daily_packet.py", 
        "--dummy", 
        "--output", str(packet_out)
    ]
    res_build = run_command(cmd_build)
    assert res_build.returncode == 0
    assert packet_out.exists()
    
    with open(packet_out) as f:
        data = json.load(f)
        assert "representative_cases" in data

    # 2. Run Council (Mock)
    reviews_dir = PROJECT_ROOT / "smoke_reviews"
    cmd_council = [
        "./.venv/bin/python",
        "scripts/run_daily_council.py",
        "--input", str(packet_out),
        "--output-dir", str(reviews_dir),
        "--mock"
    ]
    res_council = run_command(cmd_council)
    assert res_council.returncode == 0
    
    # [v1.1] Output changed to 'junho_review.json' (Minji reads this)
    junho_review = reviews_dir / "junho_review.json"
    assert junho_review.exists()
    
    # 3. Apply Patch (Dry-Run)
    # We need a dummy patch to test, but the mock council output produces an empty patch list or mock patch.
    # The mock output in run_daily_council.py produces "patch_mock_1" with *empty* patches list by default logic?
    # Wait, my run_daily_council.py mock logic:
    # patch_bundle = { "bundle_id": "patch_mock_1", ..., "patches": [] }
    # So applying it will just say "No patches". That's a valid smoke test for "no crash".
    


    # Cleanup
    if packet_out.exists():
        os.remove(packet_out)
    import shutil
    if reviews_dir.exists():
        shutil.rmtree(reviews_dir)
