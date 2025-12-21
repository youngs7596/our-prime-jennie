#!/bin/sh

# secrets.json에서 토큰 읽기
TOKEN=$(jq -r '.["cloudflare-tunnel-token"] // empty' /config/secrets.json 2>/dev/null)

if [ -z "$TOKEN" ] || [ "$TOKEN" = "null" ]; then
    echo "ℹ️  cloudflare-tunnel-token이 설정되지 않았습니다."
    echo "   외부 접근이 필요하면 secrets.json에 토큰을 추가하세요."
    echo "   컨테이너를 종료합니다 (정상 동작)."
    # 정상 종료하여 Docker가 재시작하지 않도록 함
    # sleep infinity 대신 graceful exit
    exit 0
fi

echo "✅ Cloudflare Tunnel 시작..."
exec cloudflared tunnel --no-autoupdate run --token "$TOKEN"
