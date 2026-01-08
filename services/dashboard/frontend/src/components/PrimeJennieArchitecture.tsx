import React, { useMemo, useState } from 'react';

/**
 * Prime Jennie Architecture (v2)
 * - Swimlane layout (좌표 하드코딩 최소화, 사람이 읽기 쉬운 흐름)
 * - 노드 클릭 시 우측 "Details" 패널에 설명/연결(입출력) 표시
 * - Flow 필터(Scout/Trading/Data/All) + Focus(선택 노드 중심 강조)
 *
 * Drop-in replacement for prime-jennie-architecture.jsx
 */
const PrimeJennieArchitecture = () => {
    const [hoveredNode, setHoveredNode] = useState<string | null>(null);
    const [selectedNode, setSelectedNode] = useState<string | null>(null);
    const [selectedFlow, setSelectedFlow] = useState<string>('all'); // 'all' | 'scout' | 'trading' | 'data'

    // ---- Visual constants (single source of truth) ----
    const VIEWBOX = { w: 1240, h: 720 };

    const NODE = { w: 168, h: 66, rx: 10 };
    const HALF = { w: NODE.w / 2, h: NODE.h / 2 };

    const palette = {
        bg0: '#0D0D0F',
        bg1: '#111827',
        bg2: '#0B1220',
        text: '#E5E7EB',
        muted: '#9CA3AF',
        border: 'rgba(255,255,255,0.06)',
    };

    // ---- Categories (kept compatible with v1) ----
    const categoryColors: Record<string, { bg: string; border: string; text: string }> = {
        'core-infra': { bg: '#102A43', border: '#3B82F6', text: '#BFDBFE' },
        'ai-pipeline': { bg: '#2B1642', border: '#A855F7', text: '#E9D5FF' },
        'trading': { bg: '#143025', border: '#22C55E', text: '#BBF7D0' },
        'monitoring': { bg: '#3B2A12', border: '#EAB308', text: '#FEF08A' },
        'worker': { bg: '#202225', border: '#6B7280', text: '#E5E7EB' },
        'data': { bg: '#0F2F3A', border: '#06B6D4', text: '#CFFAFE' },
        'interface': { bg: '#3B1330', border: '#EC4899', text: '#FBCFE8' },
        'reporting': { bg: '#3B2414', border: '#F97316', text: '#FED7AA' },
        'infra': { bg: '#121633', border: '#8B5CF6', text: '#DDD6FE' },
        'llm': { bg: '#2A1212', border: '#EF4444', text: '#FECACA' },
        'external': { bg: '#0B0F16', border: '#30363D', text: '#CBD5E1' },
    };

    const flowColors: Record<string, string> = {
        scout: '#A855F7',
        trading: '#22C55E',
        data: '#06B6D4',
        all: '#6B7280',
    };

    // ---- Swimlanes ----
    const lanes = [
        { id: 'sources', title: 'External & Sources', x: 40, y: 120, w: 230, h: 560, accent: '#475569' },
        { id: 'orchestration', title: 'Orchestration', x: 290, y: 120, w: 230, h: 220, accent: '#3B82F6' },
        { id: 'ai', title: 'AI / Scout', x: 540, y: 40, w: 310, h: 300, accent: '#A855F7' },
        { id: 'trading', title: 'Trading Engines', x: 870, y: 120, w: 310, h: 300, accent: '#22C55E' },
        { id: 'infra', title: 'Infra & Storage', x: 290, y: 360, w: 890, h: 140, accent: '#8B5CF6' },
        { id: 'interfaces', title: 'Interfaces & Reporting', x: 290, y: 520, w: 890, h: 160, accent: '#EC4899' },
    ];

    // ---- Nodes (center-based coordinates) ----
    const nodes = useMemo(() => {
        const lane = Object.fromEntries(lanes.map(l => [l.id, l]));

        const place = (laneId: string, col: number, row: number, cols = 1, rows = 1) => {
            const L = lane[laneId];
            const padX = 22;
            const padY = 38;
            const usableW = L.w - padX * 2;
            const usableH = L.h - padY * 2;
            const x = L.x + padX + (usableW / Math.max(cols, 1)) * (col + 0.5);
            const y = L.y + padY + (usableH / Math.max(rows, 1)) * (row + 0.5);
            return { x, y };
        };

        // Sources lane: 3 rows
        const pNews = place('sources', 0, 0, 1, 3);
        const pKis = place('sources', 0, 1, 1, 3);
        const pTg = place('sources', 0, 2, 1, 3);

        // Orchestration lane: 2 rows
        const pSched = place('orchestration', 0, 0, 1, 2);
        const pSchedW = place('orchestration', 0, 1, 1, 2);

        // AI lane: 2 cols x 2 rows
        const pOllama = place('ai', 0, 0, 2, 2);
        const pCloud = place('ai', 1, 0, 2, 2);
        const pScoutJob = place('ai', 0, 1, 2, 2);
        const pScoutWorker = place('ai', 1, 1, 2, 2);

        // Trading lane: 2 cols x 2 rows
        const pBuyScanner = place('trading', 0, 0, 2, 2);
        const pPriceMon = place('trading', 1, 0, 2, 2);
        const pBuyExec = place('trading', 0, 1, 2, 2);
        const pSellExec = place('trading', 1, 1, 2, 2);

        // Infra lane: 4 cols x 1 row
        const pMaria = place('infra', 0, 0, 4, 1);
        const pRedis = place('infra', 1, 0, 4, 1);
        const pRabbit = place('infra', 2, 0, 4, 1);
        const pChroma = place('infra', 3, 0, 4, 1);

        // Interfaces lane: 4 cols x 1 row
        const pCommand = place('interfaces', 0, 0, 4, 1);
        const pDaily = place('interfaces', 1, 0, 4, 1);
        const pDashApi = place('interfaces', 2, 0, 4, 1);
        const pDashUi = place('interfaces', 3, 0, 4, 1);

        // Broker gateway sits between Trading and KIS API
        const pGateway = { x: 1050, y: 470 };

        return {
            // External & Sources
            'news-sources': { ...pNews, category: 'external', label: 'News Sources', icon: '🌐', desc: '금융 뉴스 소스\n네이버, 한경 등' },
            'kis-api': { ...pKis, category: 'external', label: 'KIS API', icon: '🏦', desc: '한국투자증권 API\n주문/시세 조회' },
            'telegram': { ...pTg, category: 'external', label: 'Telegram', icon: '✈️', desc: '사용자 알림\n명령어 수신' },

            // Orchestration
            'scheduler-service': { ...pSched, category: 'core-infra', label: 'Scheduler', icon: '⏰', desc: '중앙 스케줄러\nCron 기반 작업 트리거' },
            'scheduler-worker': { ...pSchedW, category: 'worker', label: 'Scheduler Worker', icon: '⚙️', desc: '스케줄러가 트리거한\n스크립트 실행' },

            // AI / Scout
            'ollama': { ...pOllama, category: 'llm', label: 'Ollama (Local)', icon: '🦙', desc: 'exaone3.5 (Fast)\ngpt-oss (Reasoning)' },
            'cloud-llm': { ...pCloud, category: 'llm', label: 'Cloud LLMs', icon: '☁️', desc: 'Gemini / OpenAI\n고난도 태스크' },
            'scout-job': { ...pScoutJob, category: 'ai-pipeline', label: 'Scout Job', icon: '🔍', desc: 'The Hunter\nQuant→Hunter→Judge' },
            'scout-worker': { ...pScoutWorker, category: 'worker', label: 'Scout Worker', icon: '🤖', desc: 'LLM/Scoring 병렬 처리' },

            // Trading
            'buy-scanner': { ...pBuyScanner, category: 'trading', label: 'Buy Scanner', icon: '📡', desc: '매수 신호 탐지\nGC, RSI, BB 등' },
            'price-monitor': { ...pPriceMon, category: 'monitoring', label: 'Price Monitor', icon: '📈', desc: '실시간 가격 추적\nRedis/DB 업데이트' },
            'buy-executor': { ...pBuyExec, category: 'trading', label: 'Buy Executor', icon: '💰', desc: '주문 실행\nRisk/Lock 체크' },
            'sell-executor': { ...pSellExec, category: 'trading', label: 'Sell Executor', icon: '📤', desc: '매도 로직 실행\nSL/TP 등' },
            'kis-gateway': { ...pGateway, category: 'core-infra', label: 'KIS Gateway', icon: '🔌', desc: 'KIS API 추상화\n토큰/RateLimit' },

            // Infra & Storage
            'mariadb': { ...pMaria, category: 'infra', label: 'MariaDB', icon: '🐬', desc: '영속 저장소\n거래/종목 데이터' },
            'redis': { ...pRedis, category: 'infra', label: 'Redis', icon: '🔴', desc: '캐싱/분산락\n실시간 상태 공유' },
            'rabbitmq': { ...pRabbit, category: 'infra', label: 'RabbitMQ', icon: '🐰', desc: '메시지 큐\n서비스 간 통신' },
            'chromadb': { ...pChroma, category: 'infra', label: 'ChromaDB', icon: '🧠', desc: 'Vector DB / RAG\n뉴스/문서 검색' },

            // Interfaces & Reporting
            'command-handler': { ...pCommand, category: 'interface', label: 'Command Handler', icon: '🤳', desc: '텔레그램 봇\n수동 매매/조회' },
            'daily-briefing': { ...pDaily, category: 'reporting', label: 'Daily Briefing', icon: '📋', desc: '일일 리포트\nLLM 기반 생성' },
            'dashboard-backend': { ...pDashApi, category: 'interface', label: 'Dashboard API', icon: '🖥️', desc: '웹 대시보드 API\n상태/성과 집계' },
            'dashboard-frontend': { ...pDashUi, category: 'interface', label: 'Dashboard UI', icon: '🎨', desc: 'React 웹 UI\n모니터링 & 제어' },
        };
    }, []);

    // ---- Flows ----
    const dataFlows = useMemo(() => ([
        // Scout
        { from: 'scheduler-service', to: 'scout-job', type: 'control', flow: 'scout', label: 'Trigger' },
        { from: 'scout-job', to: 'scout-worker', type: 'data', flow: 'scout', label: 'Tasks' },
        { from: 'scout-worker', to: 'mariadb', type: 'data', flow: 'scout' },
        { from: 'scout-worker', to: 'chromadb', type: 'data', flow: 'scout', label: 'RAG' },
        { from: 'ollama', to: 'scout-worker', type: 'data', flow: 'scout', label: 'LLM' },
        { from: 'cloud-llm', to: 'scout-worker', type: 'data', flow: 'scout' },

        // Trading
        { from: 'scout-job', to: 'buy-scanner', type: 'data', flow: 'trading', label: 'Candidates' },
        { from: 'buy-scanner', to: 'rabbitmq', type: 'signal', flow: 'trading', label: 'BuySignal' },
        { from: 'rabbitmq', to: 'buy-executor', type: 'signal', flow: 'trading' },
        { from: 'buy-executor', to: 'redis', type: 'data', flow: 'trading', label: 'Lock' },
        { from: 'buy-executor', to: 'kis-gateway', type: 'data', flow: 'trading', label: 'Order' },
        { from: 'sell-executor', to: 'kis-gateway', type: 'data', flow: 'trading' },
        { from: 'price-monitor', to: 'kis-gateway', type: 'data', flow: 'trading', label: 'Quotes' },
        { from: 'price-monitor', to: 'redis', type: 'data', flow: 'trading' },
        { from: 'buy-scanner', to: 'price-monitor', type: 'data', flow: 'trading' },
        { from: 'kis-gateway', to: 'kis-api', type: 'data', flow: 'trading' },

        // Data ingestion (minimal)
        { from: 'news-sources', to: 'chromadb', type: 'data', flow: 'data', label: 'News→RAG' },
        { from: 'news-sources', to: 'mariadb', type: 'data', flow: 'data', label: 'NewsMeta' },
        { from: 'scheduler-service', to: 'scheduler-worker', type: 'control', flow: 'data', label: 'Cron' },
        { from: 'scheduler-worker', to: 'mariadb', type: 'data', flow: 'data' },

        // Interfaces
        { from: 'telegram', to: 'command-handler', type: 'data', flow: 'all', label: 'Commands' },
        { from: 'buy-executor', to: 'command-handler', type: 'signal', flow: 'trading', label: 'Notify' },
        { from: 'daily-briefing', to: 'command-handler', type: 'data', flow: 'all' },
        { from: 'daily-briefing', to: 'cloud-llm', type: 'data', flow: 'all', label: 'Gen' },
        { from: 'dashboard-backend', to: 'mariadb', type: 'data', flow: 'all' },
        { from: 'dashboard-backend', to: 'redis', type: 'data', flow: 'all' },
        { from: 'dashboard-frontend', to: 'dashboard-backend', type: 'data', flow: 'all' },
    ]), []);

    // ---- Derived ----
    const nodeById = nodes as unknown as Record<string, any>;

    const visibleFlows = useMemo(() => {
        return dataFlows.filter((f: any) => {
            if (selectedFlow !== 'all' && f.flow !== selectedFlow && f.flow !== 'all') return false;
            if (selectedNode && f.from !== selectedNode && f.to !== selectedNode) return false;
            return true;
        });
    }, [dataFlows, selectedFlow, selectedNode]);

    const edgeStyle = (f: any) => {
        const color = flowColors[f.flow] || flowColors.all;
        const baseOpacity = selectedFlow === 'all' ? 0.35 : 0.85;
        const hoveredBoost = hoveredNode && (f.from === hoveredNode || f.to === hoveredNode) ? 0.95 : baseOpacity;
        const width = selectedFlow !== 'all' && (f.flow === selectedFlow) ? 2.6 : 1.6;
        const dash =
            f.type === 'control' ? '7,5' :
                f.type === 'signal' ? '3,3' :
                    null;

        return { color, opacity: hoveredBoost, width, dash };
    };

    const getPort = (from: any, to: any) => {
        const dx = to.x - from.x;
        const dy = to.y - from.y;

        const horizontal = Math.abs(dx) >= Math.abs(dy);

        const sx = from.x + (dx >= 0 ? HALF.w : -HALF.w);
        const sy = from.y + (horizontal ? 0 : (dy >= 0 ? HALF.h : -HALF.h));

        const tx = to.x + (dx >= 0 ? -HALF.w : HALF.w);
        const ty = to.y + (horizontal ? 0 : (dy >= 0 ? -HALF.h : HALF.h));

        return { sx, sy, tx, ty };
    };

    const buildElbowPath = (sx: number, sy: number, tx: number, ty: number) => {
        const midX = (sx + tx) / 2;
        return `M ${sx} ${sy} L ${midX} ${sy} L ${midX} ${ty} L ${tx} ${ty}`;
    };

    const renderLane = (L: any) => (
        <g key={L.id}>
            <rect
                x={L.x}
                y={L.y}
                width={L.w}
                height={L.h}
                rx="14"
                fill="url(#laneBg)"
                stroke={L.accent}
                strokeWidth="1"
                opacity="0.9"
                strokeOpacity="0.25"
            />
            <text x={L.x + 14} y={L.y + 22} fill={L.accent} fontSize="11" fontWeight="700" opacity="0.8">
                {L.title}
            </text>
            <line x1={L.x + 12} y1={L.y + 30} x2={L.x + L.w - 12} y2={L.y + 30} stroke={L.accent} strokeOpacity="0.12" />
        </g>
    );

    const renderNode = (id: string, node: any) => {
        const colors = categoryColors[node.category] || categoryColors.infra;
        const isHovered = hoveredNode === id;
        const isSelected = selectedNode === id;
        const scale = isHovered || isSelected ? 1.04 : 1;

        return (
            <g
                key={id}
                transform={`translate(${node.x}, ${node.y}) scale(${scale})`}
                style={{ cursor: 'pointer', transition: 'transform 120ms ease' }}
                onMouseEnter={() => setHoveredNode(id)}
                onMouseLeave={() => setHoveredNode(null)}
                onClick={() => setSelectedNode(prev => (prev === id ? null : id))}
            >
                <rect
                    x={-HALF.w}
                    y={-HALF.h}
                    width={NODE.w}
                    height={NODE.h}
                    rx={NODE.rx}
                    fill={colors.bg}
                    stroke={colors.border}
                    strokeWidth={isSelected ? 3 : 2}
                    filter={isHovered || isSelected ? 'url(#glow)' : 'none'}
                />
                <text y={-10} textAnchor="middle" fill={colors.text} fontSize="20">{node.icon}</text>
                <text y={14} textAnchor="middle" fill={colors.text} fontSize="12" fontWeight="700">{node.label}</text>
            </g>
        );
    };

    const renderFlow = (f: any, idx: number) => {
        const from = nodeById[f.from];
        const to = nodeById[f.to];
        if (!from || !to) return null;

        const { sx, sy, tx, ty } = getPort(from, to);
        const d = buildElbowPath(sx, sy, tx, ty);
        const st = edgeStyle(f);
        const isHot = hoveredNode && (f.from === hoveredNode || f.to === hoveredNode);

        const midX = (sx + tx) / 2;
        const midY = (sy + ty) / 2;

        return (
            <g key={idx}>
                <path
                    d={d}
                    fill="none"
                    stroke={st.color}
                    strokeWidth={st.width}
                    strokeOpacity={st.opacity}
                    strokeDasharray={st.dash || undefined}
                    markerEnd={`url(#arrow-${f.flow})`}
                    style={{ transition: 'stroke-opacity 120ms ease, stroke-width 120ms ease' }}
                />
                {f.label && (
                    <text
                        x={midX}
                        y={midY - 6}
                        textAnchor="middle"
                        fill={st.color}
                        fontSize="10"
                        fontWeight="600"
                        opacity={isHot ? 0.95 : Math.min(0.85, st.opacity + 0.25)}
                    >
                        {f.label}
                    </text>
                )}
            </g>
        );
    };

    const selected = selectedNode ? nodeById[selectedNode] : null;

    const selectedConnections = useMemo(() => {
        if (!selectedNode) return { inb: [], out: [] };
        const inb = dataFlows.filter(f => f.to === selectedNode);
        const out = dataFlows.filter(f => f.from === selectedNode);
        return { inb, out };
    }, [selectedNode, dataFlows]);

    const FlowTag = ({ flow }: { flow: string }) => (
        <span style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 6,
            padding: '2px 8px',
            borderRadius: 999,
            border: `1px solid ${(flowColors[flow] || flowColors.all)}55`,
            background: `${(flowColors[flow] || flowColors.all)}1A`,
            color: flowColors[flow] || flowColors.all,
            fontSize: 11,
            fontWeight: 700,
            lineHeight: '18px',
        }}>
            <span style={{ width: 8, height: 8, borderRadius: 99, background: flowColors[flow] || flowColors.all }} />
            {flow.toUpperCase()}
        </span>
    );

    return (
        <div style={{
            background: 'linear-gradient(135deg, #0D0D0F 0%, #0B1220 55%, #0D0D0F 100%)',
            minHeight: '100vh',
            padding: 28,
            fontFamily: "'Pretendard', 'Noto Sans KR', -apple-system, sans-serif",
            color: palette.text,
        }}>
            <div style={{ maxWidth: 1500, margin: '0 auto' }}>
                {/* Header */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 10 }}>
                    <div style={{
                        background: 'linear-gradient(135deg, #FF6B35 0%, #FF9500 100%)',
                        borderRadius: 12,
                        padding: '10px 14px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: 8,
                        boxShadow: '0 10px 30px rgba(255,149,0,0.10)',
                    }}>
                        <span style={{ fontSize: 20 }}>🤖</span>
                        <span style={{ fontWeight: 800, fontSize: 16, color: '#fff' }}>Prime Jennie</span>
                    </div>
                    <div>
                        <div style={{
                            fontSize: 28,
                            fontWeight: 900,
                            margin: 0,
                            background: 'linear-gradient(90deg, #fff 0%, #9CA3AF 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                        }}>
                            시스템 아키텍처
                        </div>
                        <div style={{ marginTop: 2, color: '#6B7280', fontSize: 13 }}>
                            Swimlane Diagram · Click a node to focus & inspect connections
                        </div>
                    </div>
                </div>

                {/* Controls */}
                <div style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    gap: 12,
                    margin: '18px 0 14px',
                    flexWrap: 'wrap',
                }}>
                    <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                        {[
                            { id: 'all', label: '전체', icon: '🔄' },
                            { id: 'scout', label: 'Scout', icon: '🔍' },
                            { id: 'trading', label: 'Trading', icon: '💰' },
                            { id: 'data', label: 'Data', icon: '📊' },
                        ].map(btn => (
                            <button
                                key={btn.id}
                                onClick={() => setSelectedFlow(btn.id)}
                                style={{
                                    padding: '10px 14px',
                                    borderRadius: 10,
                                    border: `1px solid ${(selectedFlow === btn.id ? flowColors[btn.id] : 'rgba(255,255,255,0.08)')}`,
                                    background: selectedFlow === btn.id ? `${flowColors[btn.id]}20` : 'rgba(255,255,255,0.04)',
                                    color: selectedFlow === btn.id ? flowColors[btn.id] : palette.muted,
                                    cursor: 'pointer',
                                    fontSize: 13,
                                    fontWeight: 800,
                                    display: 'inline-flex',
                                    alignItems: 'center',
                                    gap: 8,
                                }}
                            >
                                <span>{btn.icon}</span>{btn.label}
                            </button>
                        ))}
                    </div>

                    <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
                        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
                            <span style={{ color: palette.muted, fontSize: 12, fontWeight: 700 }}>Edge:</span>
                            <span style={{ color: palette.muted, fontSize: 12 }}>
                                <span style={{ borderBottom: `2px dashed ${palette.muted}`, paddingBottom: 1 }}>control</span> ·
                                <span style={{ borderBottom: `2px dotted ${palette.muted}`, paddingBottom: 1, marginLeft: 8 }}>signal</span> ·
                                <span style={{ borderBottom: `2px solid ${palette.muted}`, paddingBottom: 1, marginLeft: 8 }}>data</span>
                            </span>
                        </div>

                        <button
                            onClick={() => setSelectedNode(null)}
                            disabled={!selectedNode}
                            style={{
                                padding: '10px 14px',
                                borderRadius: 10,
                                border: '1px solid rgba(255,255,255,0.10)',
                                background: selectedNode ? 'rgba(255,255,255,0.05)' : 'rgba(255,255,255,0.02)',
                                color: selectedNode ? palette.text : '#6B7280',
                                cursor: selectedNode ? 'pointer' : 'not-allowed',
                                fontSize: 13,
                                fontWeight: 800,
                            }}
                            title="선택(포커스) 해제"
                        >
                            ✖ Focus 해제
                        </button>
                    </div>
                </div>

                {/* Diagram + Details */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr 360px',
                    gap: 14,
                    alignItems: 'start',
                }}>
                    {/* Diagram Card */}
                    <div style={{
                        background: 'rgba(0,0,0,0.35)',
                        borderRadius: 16,
                        border: `1px solid ${palette.border}`,
                        padding: 16,
                        boxShadow: '0 18px 60px rgba(0,0,0,0.45)',
                    }}>
                        <svg width="100%" height="720" viewBox={`0 0 ${VIEWBOX.w} ${VIEWBOX.h}`} style={{ overflow: 'visible' }}>
                            <defs>
                                <filter id="glow" x="-50%" y="-50%" width="200%" height="200%">
                                    <feGaussianBlur stdDeviation="4" result="coloredBlur" />
                                    <feMerge>
                                        <feMergeNode in="coloredBlur" />
                                        <feMergeNode in="SourceGraphic" />
                                    </feMerge>
                                </filter>

                                <linearGradient id="laneBg" x1="0%" y1="0%" x2="100%" y2="100%">
                                    <stop offset="0%" stopColor="#0B1220" stopOpacity="0.55" />
                                    <stop offset="100%" stopColor="#0D0D0F" stopOpacity="0.85" />
                                </linearGradient>

                                {Object.entries(flowColors).map(([key, color]) => (
                                    <marker
                                        key={key}
                                        id={`arrow-${key}`}
                                        markerWidth="10"
                                        markerHeight="10"
                                        refX="9"
                                        refY="3"
                                        orient="auto"
                                        markerUnits="strokeWidth"
                                    >
                                        <path d="M0,0 L0,6 L9,3 z" fill={color} />
                                    </marker>
                                ))}
                            </defs>

                            {/* Lanes */}
                            {lanes.map(renderLane)}

                            {/* Flows */}
                            <g>{visibleFlows.map((f: any, idx: number) => renderFlow(f, idx))}</g>

                            {/* Nodes */}
                            {Object.entries(nodeById).map(([id, n]) => renderNode(id, n))}
                        </svg>
                    </div>

                    {/* Details Panel */}
                    <div style={{
                        background: 'rgba(0,0,0,0.35)',
                        borderRadius: 16,
                        border: `1px solid ${palette.border}`,
                        padding: 16,
                        boxShadow: '0 18px 60px rgba(0,0,0,0.45)',
                        position: 'sticky',
                        top: 18,
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
                            <div style={{ fontSize: 14, fontWeight: 900, color: palette.text }}>Details</div>
                            <FlowTag flow={selectedFlow} />
                        </div>

                        {!selected ? (
                            <div style={{
                                color: palette.muted,
                                fontSize: 13,
                                lineHeight: 1.7,
                                background: 'rgba(255,255,255,0.03)',
                                border: '1px solid rgba(255,255,255,0.06)',
                                borderRadius: 12,
                                padding: 14,
                            }}>
                                <div style={{ fontWeight: 800, color: palette.text, marginBottom: 8 }}>사용 방법</div>
                                <ul style={{ margin: 0, paddingLeft: 18 }}>
                                    <li>노드를 클릭하면 해당 노드 중심으로 연결만 강조됩니다.</li>
                                    <li>상단에서 Scout/Trading/Data로 플로우를 필터링하세요.</li>
                                    <li>Focus 해제로 전체 뷰로 복귀할 수 있습니다.</li>
                                </ul>
                            </div>
                        ) : (
                            <div>
                                <div style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 10,
                                    padding: 12,
                                    borderRadius: 12,
                                    border: '1px solid rgba(255,255,255,0.08)',
                                    background: 'rgba(255,255,255,0.03)',
                                    marginBottom: 12,
                                }}>
                                    <div style={{ fontSize: 22 }}>{selected.icon}</div>
                                    <div style={{ flex: 1 }}>
                                        <div style={{ fontSize: 14, fontWeight: 900 }}>{selected.label}</div>
                                        <div style={{ fontSize: 12, color: palette.muted, marginTop: 2 }}>{selected.category}</div>
                                    </div>
                                </div>

                                <div style={{ fontSize: 13, lineHeight: 1.6, marginBottom: 12 }}>
                                    {selected.desc.split('\n').map((line: string, i: number) => (
                                        <div key={i} style={{ color: i === 0 ? palette.text : palette.muted }}>{line}</div>
                                    ))}
                                </div>

                                <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 12 }}>
                                    <div style={{
                                        borderRadius: 12,
                                        border: '1px solid rgba(255,255,255,0.08)',
                                        background: 'rgba(255,255,255,0.03)',
                                        padding: 12,
                                    }}>
                                        <div style={{ fontSize: 12, fontWeight: 900, color: palette.text, marginBottom: 8 }}>
                                            Outbound ({selectedConnections.out.length})
                                        </div>
                                        {selectedConnections.out.length === 0 ? (
                                            <div style={{ color: palette.muted, fontSize: 12 }}>없음</div>
                                        ) : (
                                            <ul style={{ margin: 0, paddingLeft: 18, color: palette.muted, fontSize: 12, lineHeight: 1.7 }}>
                                                {selectedConnections.out.map((f: any, i: number) => (
                                                    <li key={i}>
                                                        <span style={{ color: flowColors[f.flow] || flowColors.all, fontWeight: 800 }}>{f.flow}</span>
                                                        {' → '}
                                                        <span style={{ color: palette.text }}>{nodeById[f.to]?.label || f.to}</span>
                                                        {f.label ? <span style={{ color: palette.muted }}> ({f.label})</span> : null}
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>

                                    <div style={{
                                        borderRadius: 12,
                                        border: '1px solid rgba(255,255,255,0.08)',
                                        background: 'rgba(255,255,255,0.03)',
                                        padding: 12,
                                    }}>
                                        <div style={{ fontSize: 12, fontWeight: 900, color: palette.text, marginBottom: 8 }}>
                                            Inbound ({selectedConnections.inb.length})
                                        </div>
                                        {selectedConnections.inb.length === 0 ? (
                                            <div style={{ color: palette.muted, fontSize: 12 }}>없음</div>
                                        ) : (
                                            <ul style={{ margin: 0, paddingLeft: 18, color: palette.muted, fontSize: 12, lineHeight: 1.7 }}>
                                                {selectedConnections.inb.map((f: any, i: number) => (
                                                    <li key={i}>
                                                        <span style={{ color: palette.text }}>{nodeById[f.from]?.label || f.from}</span>
                                                        {' → '}
                                                        <span style={{ color: flowColors[f.flow] || flowColors.all, fontWeight: 800 }}>{f.flow}</span>
                                                        {f.label ? <span style={{ color: palette.muted }}> ({f.label})</span> : null}
                                                    </li>
                                                ))}
                                            </ul>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Footer */}
                <div style={{
                    marginTop: 16,
                    padding: 14,
                    textAlign: 'center',
                    color: '#6B7280',
                    fontSize: 11,
                    borderTop: '1px solid rgba(255,255,255,0.06)',
                }}>
                    <strong style={{ color: '#9CA3AF' }}>my-prime-jennie</strong> Architecture · Tech Stack: Docker Compose, FastAPI, React, Ollama, MariaDB, Redis, RabbitMQ, ChromaDB
                </div>
            </div>
        </div>
    );
};

export default PrimeJennieArchitecture;
