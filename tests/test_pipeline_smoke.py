"""
tests/test_pipeline_smoke.py - 파이프라인 스모크 테스트
=====================================================

전체 파이프라인(패킷 생성 → Council 실행)이 정상적으로 동작하는지 확인합니다.
"""

import pytest
import subprocess
import sys
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
    """전체 파이프라인 스모크 테스트"""
    # 1. Build Weekly Packet (Dummy)
    packet_out = PROJECT_ROOT / "smoke_packet.json"
    cmd_build = [
        sys.executable, # Changed from "./venv/bin/python"
        "scripts/build_weekly_packet.py", 
        "--dummy", 
        "--output", str(packet_out)
    ]
    res_build = run_command(cmd_build)
    assert res_build.returncode == 0, f"패킷 생성 실패: {res_build.stderr}"
    assert packet_out.exists(), "패킷 파일이 생성되지 않았습니다"
    
    with open(packet_out) as f:
        data = json.load(f)
        assert "representative_cases" in data, "패킷에 representative_cases 키가 없습니다"

    # 2. Run Council (Mock)
    reviews_dir = PROJECT_ROOT / "smoke_reviews"
    cmd_council = [
        "./venv/bin/python",
        "scripts/run_weekly_council.py",
        "--input", str(packet_out),
        "--output-dir", str(reviews_dir),
        "--mock"
    ]
    res_council = run_command(cmd_council)
    assert res_council.returncode == 0, f"Council 실행 실패: {res_council.stderr}"
    
    # Output: 'junho_review.json' (Minji reads this)
    junho_review = reviews_dir / "junho_review.json"
    assert junho_review.exists(), "junho_review.json이 생성되지 않았습니다"

    # Cleanup
    if packet_out.exists():
        os.remove(packet_out)
    import shutil
    if reviews_dir.exists():
        shutil.rmtree(reviews_dir)
