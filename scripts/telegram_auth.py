#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
scripts/telegram_auth.py
------------------------
텔레그램 API 인증 스크립트.
최초 1회 실행하여 세션 파일을 생성합니다.
"""

import os
import sys
import json
import asyncio

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

def load_secrets():
    """secrets.json에서 설정 로드"""
    secrets_path = os.path.join(PROJECT_ROOT, "secrets.json")
    if os.path.exists(secrets_path):
        with open(secrets_path, "r") as f:
            return json.load(f)
    return {}

async def main():
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        print("Telethon이 설치되어 있지 않습니다.")
        print("설치: pip install telethon")
        return

    secrets = load_secrets()
    api_id = secrets.get("telegram_api_id")
    api_hash = secrets.get("telegram_api_hash")

    if not api_id or not api_hash:
        print("secrets.json에 telegram_api_id와 telegram_api_hash가 없습니다.")
        return

    session_dir = os.path.join(PROJECT_ROOT, ".telegram_sessions")
    os.makedirs(session_dir, exist_ok=True)
    session_path = os.path.join(session_dir, "telegram_collector")

    print("=" * 60)
    print("텔레그램 API 인증")
    print("=" * 60)
    print(f"API ID: {api_id}")
    print(f"Session: {session_path}")
    print("=" * 60)
    print()

    client = TelegramClient(session_path, int(api_id), api_hash)

    await client.connect()

    if not await client.is_user_authorized():
        phone = input("전화번호 입력 (+821012345678 형식): ")
        await client.send_code_request(phone)

        try:
            code = input("인증코드 입력: ")
            await client.sign_in(phone, code)
        except SessionPasswordNeededError:
            password = input("2단계 인증 비밀번호 입력: ")
            await client.sign_in(password=password)

    me = await client.get_me()
    print()
    print("=" * 60)
    print(f"인증 성공!")
    print(f"사용자: {me.first_name} {me.last_name or ''}")
    print(f"Username: @{me.username or 'N/A'}")
    print(f"Phone: {me.phone}")
    print("=" * 60)
    print()
    print(f"세션 파일 생성됨: {session_path}.session")

    # 채널 접근 테스트
    print()
    print("채널 접근 테스트...")
    channels = ["hedgecat0301", "HanaResearch", "meritz_research"]

    for username in channels:
        try:
            entity = await client.get_entity(username)
            print(f"  ✅ @{username}: {entity.title}")
        except Exception as e:
            print(f"  ❌ @{username}: {e}")

    await client.disconnect()

if __name__ == "__main__":
    asyncio.run(main())
