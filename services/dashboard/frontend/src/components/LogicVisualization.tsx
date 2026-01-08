import React, { useState } from 'react';

// 60일 가상 데이터 생성
const generateMockData = () => {
    const data = [];
    let basePrice = 60000;
    let rsi = 50;

    for (let i = 60; i >= 0; i--) {
        const day = i;
        let open, high, low, close, volume, foreignBuy, institutionBuy;

        // 스토리라인에 따른 가격 시뮬레이션
        if (day >= 40) {
            // D-60 ~ D-40: 상승 추세
            const progress = (60 - day) / 20;
            basePrice = 60000 + progress * 15000;
            rsi = 50 + progress * 15;
            foreignBuy = Math.random() * 50000 + 10000;
            institutionBuy = Math.random() * 30000;
        } else if (day >= 25) {
            // D-40 ~ D-25: 조정 국면
            const progress = (40 - day) / 15;
            basePrice = 75000 - progress * 10000;
            rsi = 65 - progress * 40;
            if (day === 32) {
                rsi = 28; // RSI 과매도
                foreignBuy = 150000; // 외국인 순매수 급증
            } else {
                foreignBuy = Math.random() * 20000 - 10000;
            }
            institutionBuy = Math.random() * 20000 - 10000;
        } else if (day >= 15) {
            // D-25 ~ D-15: 바닥 다지기
            basePrice = 65000 + (Math.random() - 0.5) * 2000;
            rsi = 35 + Math.random() * 10;
            foreignBuy = Math.random() * 30000;
            institutionBuy = Math.random() * 20000;
        } else {
            // D-15 ~ D-Day: 재상승
            const progress = (15 - day) / 15;
            basePrice = 65000 + progress * 7000;
            rsi = 40 + progress * 20;
            foreignBuy = Math.random() * 60000 + 20000;
            institutionBuy = Math.random() * 40000 + 10000;
        }

        const volatility = basePrice * 0.02;
        open = basePrice + (Math.random() - 0.5) * volatility;
        close = basePrice + (Math.random() - 0.5) * volatility;
        high = Math.max(open, close) + Math.random() * volatility * 0.5;
        low = Math.min(open, close) - Math.random() * volatility * 0.5;

        // 특수 이벤트 날짜
        if (day === 20) {
            low = 63500; // BB 하단 터치
        }

        volume = 500000 + Math.random() * 300000;
        if (day === 10 || day === 32) {
            volume = 1200000; // 거래량 급증
        }

        data.push({
            day: -day,
            date: `D${day === 0 ? '' : '-' + day}`,
            open: Math.round(open),
            high: Math.round(high),
            low: Math.round(low),
            close: Math.round(close),
            volume: Math.round(volume),
            rsi: Math.min(70, Math.max(25, rsi + (Math.random() - 0.5) * 5)),
            foreignBuy: Math.round(foreignBuy),
            institutionBuy: Math.round(institutionBuy),
        });
    }

    return data.reverse();
};

interface MockDataPoint {
    day: number;
    date: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
    rsi: number;
    foreignBuy: number;
    institutionBuy: number;
}

// 이동평균 계산
const calculateMA = (data: MockDataPoint[], period: number): (number | null)[] => {
    return data.map((_, idx) => {
        if (idx < period - 1) return null;
        const slice = data.slice(idx - period + 1, idx + 1);
        return slice.reduce((sum, d) => sum + d.close, 0) / period;
    });
};

// 볼린저 밴드 계산
const calculateBB = (data: MockDataPoint[], period: number = 20) => {
    const ma = calculateMA(data, period);
    return data.map((_, idx) => {
        if (idx < period - 1) return { upper: null, lower: null, middle: null };
        const slice = data.slice(idx - period + 1, idx + 1);
        const avg = ma[idx];
        if (avg === null) return { upper: null, lower: null, middle: null };
        const variance = slice.reduce((sum, d) => sum + Math.pow(d.close - avg, 2), 0) / period;
        const stdDev = Math.sqrt(variance);
        return {
            upper: avg + stdDev * 2,
            lower: avg - stdDev * 2,
            middle: avg,
        };
    });
};

const PrimeJennieChart: React.FC = () => {
    const [data] = useState<MockDataPoint[]>(generateMockData());
    const ma5 = calculateMA(data, 5);
    const ma20 = calculateMA(data, 20);
    const ma120 = calculateMA(data, 120);
    const bb = calculateBB(data, 20);
    const avgVolume = data.reduce((sum, d) => sum + d.volume, 0) / data.length;

    // 매수 시그널 정의
    const signals = [
        { day: 32, type: 'RSI_FOREIGN', label: 'RSI+외인', color: '#FF9500', icon: '◆', stars: 4 },
        { day: 20, type: 'BB_LOWER', label: 'BB 하단', color: '#007AFF', icon: '●', stars: 2 },
        { day: 10, type: 'GOLDEN_CROSS', label: '골든크로스', color: '#34C759', icon: '▲', stars: 3 },
    ];

    // 차트 영역 설정
    const chartWidth = 1100;
    const mainChartHeight = 400;
    const panelHeight = 120;
    const margin = { top: 40, right: 80, bottom: 30, left: 80 };

    const priceMin = Math.min(...data.map(d => d.low)) * 0.98;
    const priceMax = Math.max(...data.map(d => d.high)) * 1.02;

    const xScale = (idx: number) => margin.left + (idx / (data.length - 1)) * (chartWidth - margin.left - margin.right);
    const yScale = (price: number) => margin.top + ((priceMax - price) / (priceMax - priceMin)) * (mainChartHeight - margin.top - margin.bottom);

    const rsiScale = (rsi: number) => 20 + ((70 - rsi) / 50) * 80;
    const volumeMax = Math.max(...data.map(d => d.volume));
    const volumeScale = (vol: number) => 100 - (vol / volumeMax) * 80;

    const flowMax = Math.max(...data.map(d => Math.max(Math.abs(d.foreignBuy), Math.abs(d.institutionBuy))));
    const flowScale = (flow: number) => 60 - (flow / flowMax) * 40;

    // 외국인 3일 연속 순매수 체크
    const foreignStreaks = data.map((_, idx) => {
        if (idx < 2) return false;
        return data[idx].foreignBuy > 0 && data[idx - 1].foreignBuy > 0 && data[idx - 2].foreignBuy > 0;
    });

    return (
        <div style={{
            background: 'linear-gradient(180deg, #0D0D0F 0%, #1A1A1F 50%, #0D0D0F 100%)',
            minHeight: '100vh',
            padding: '40px',
            fontFamily: "'Pretendard', 'Noto Sans KR', -apple-system, sans-serif",
            color: '#E5E5EA',
        }}>
            {/* 헤더 */}
            <div style={{ maxWidth: '1200px', margin: '0 auto' }}>
                <div style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '20px',
                    marginBottom: '12px',
                }}>
                    <div style={{
                        background: 'linear-gradient(135deg, #FF6B35 0%, #FF9500 100%)',
                        borderRadius: '12px',
                        padding: '12px 16px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                    }}>
                        <span style={{ fontSize: '24px' }}>🤖</span>
                        <span style={{ fontWeight: '700', fontSize: '18px', color: '#fff' }}>Prime Jennie</span>
                    </div>
                    <div>
                        <h1 style={{
                            fontSize: '32px',
                            fontWeight: '800',
                            margin: 0,
                            background: 'linear-gradient(90deg, #fff 0%, #8E8E93 100%)',
                            WebkitBackgroundClip: 'text',
                            WebkitTextFillColor: 'transparent',
                        }}>
                            매수 조건 시각화 차트
                        </h1>
                        <p style={{ margin: '4px 0 0', color: '#8E8E93', fontSize: '14px' }}>
                            AI Trading System Buy Signal Analysis
                        </p>
                    </div>
                </div>

                {/* 종목 정보 */}
                <div style={{
                    display: 'flex',
                    gap: '24px',
                    marginBottom: '32px',
                    padding: '20px 24px',
                    background: 'rgba(255,255,255,0.03)',
                    borderRadius: '16px',
                    border: '1px solid rgba(255,255,255,0.06)',
                }}>
                    <div>
                        <span style={{ color: '#8E8E93', fontSize: '12px' }}>종목명</span>
                        <div style={{ fontSize: '20px', fontWeight: '700', color: '#fff' }}>테크프라임</div>
                        <span style={{ color: '#636366', fontSize: '13px' }}>007070</span>
                    </div>
                    <div style={{ borderLeft: '1px solid rgba(255,255,255,0.1)', paddingLeft: '24px' }}>
                        <span style={{ color: '#8E8E93', fontSize: '12px' }}>현재가</span>
                        <div style={{ fontSize: '20px', fontWeight: '700', color: '#FF3B30' }}>72,000원</div>
                        <span style={{ color: '#FF3B30', fontSize: '13px' }}>+1.41%</span>
                    </div>
                    <div style={{ borderLeft: '1px solid rgba(255,255,255,0.1)', paddingLeft: '24px' }}>
                        <span style={{ color: '#8E8E93', fontSize: '12px' }}>섹터</span>
                        <div style={{ fontSize: '20px', fontWeight: '700', color: '#fff' }}>IT/반도체</div>
                    </div>
                    <div style={{ borderLeft: '1px solid rgba(255,255,255,0.1)', paddingLeft: '24px' }}>
                        <span style={{ color: '#8E8E93', fontSize: '12px' }}>분석 기간</span>
                        <div style={{ fontSize: '20px', fontWeight: '700', color: '#fff' }}>60일</div>
                        <span style={{ color: '#636366', fontSize: '13px' }}>D-60 ~ D-Day</span>
                    </div>
                </div>

                {/* 매수 시그널 범례 */}
                <div style={{
                    display: 'flex',
                    gap: '16px',
                    marginBottom: '24px',
                    flexWrap: 'wrap',
                }}>
                    {signals.map((sig, idx) => (
                        <div key={idx} style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '8px',
                            padding: '10px 16px',
                            background: `${sig.color}15`,
                            border: `1px solid ${sig.color}40`,
                            borderRadius: '10px',
                        }}>
                            <span style={{ color: sig.color, fontSize: '18px', fontWeight: '700' }}>{sig.icon}</span>
                            <span style={{ color: sig.color, fontWeight: '600' }}>{sig.label}</span>
                            <span style={{ color: '#FFD60A' }}>{'★'.repeat(sig.stars)}</span>
                        </div>
                    ))}
                </div>

                {/* 매수 시그널 상세 설명 */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '16px',
                    marginBottom: '24px',
                }}>
                    {/* 골든크로스 설명 */}
                    <div style={{
                        background: 'rgba(52,199,89,0.1)',
                        border: '1px solid rgba(52,199,89,0.3)',
                        borderRadius: '12px',
                        padding: '16px',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                            <span style={{ color: '#34C759', fontSize: '20px', fontWeight: '700' }}>▲</span>
                            <span style={{ color: '#34C759', fontWeight: '700', fontSize: '14px' }}>골든크로스</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.6', color: '#C7C7CC' }}>
                            <strong style={{ color: '#34C759' }}>단기(5일) 이동평균선</strong>이
                            <strong style={{ color: '#FF9500' }}> 중기(20일) 이동평균선</strong>을
                            <strong style={{ color: '#fff' }}> 아래에서 위로 돌파</strong>하는 순간.
                            <br /><br />
                            이는 <strong style={{ color: '#fff' }}>상승 추세 전환 신호</strong>로,
                            최근 주가 흐름이 과거 평균보다 강해지고 있음을 의미합니다.
                        </p>
                    </div>

                    {/* BB 하단 설명 */}
                    <div style={{
                        background: 'rgba(0,122,255,0.1)',
                        border: '1px solid rgba(0,122,255,0.3)',
                        borderRadius: '12px',
                        padding: '16px',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                            <span style={{ color: '#007AFF', fontSize: '20px', fontWeight: '700' }}>●</span>
                            <span style={{ color: '#007AFF', fontWeight: '700', fontSize: '14px' }}>BB 하단 터치</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.6', color: '#C7C7CC' }}>
                            주가가 <strong style={{ color: '#5AC8FA' }}>볼린저 밴드 하단선</strong>에 닿거나
                            그 아래로 내려간 상태.
                            <br /><br />
                            통계적으로 주가가 <strong style={{ color: '#fff' }}>과도하게 하락</strong>했음을 의미하며,
                            <strong style={{ color: '#34C759' }}> 반등 가능성</strong>이 높아지는 구간입니다.
                        </p>
                    </div>

                    {/* RSI+외인 설명 */}
                    <div style={{
                        background: 'rgba(255,149,0,0.1)',
                        border: '1px solid rgba(255,149,0,0.3)',
                        borderRadius: '12px',
                        padding: '16px',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '12px' }}>
                            <span style={{ color: '#FF9500', fontSize: '20px', fontWeight: '700' }}>◆</span>
                            <span style={{ color: '#FF9500', fontWeight: '700', fontSize: '14px' }}>RSI 과매도 + 외국인 매수</span>
                        </div>
                        <p style={{ margin: 0, fontSize: '12px', lineHeight: '1.6', color: '#C7C7CC' }}>
                            <strong style={{ color: '#AF52DE' }}>RSI 지표가 30 이하</strong>(과매도 구간)이면서
                            동시에 <strong style={{ color: '#007AFF' }}>외국인이 순매수</strong>하는 상황.
                            <br /><br />
                            시장이 공포에 빠져있지만, <strong style={{ color: '#fff' }}>스마트머니(외국인)</strong>는
                            오히려 매수하는 <strong style={{ color: '#FFD60A' }}>역발상 투자</strong> 기회입니다.
                        </p>
                    </div>
                </div>

                {/* 메인 캔들 차트 */}
                <div style={{
                    background: 'rgba(0,0,0,0.4)',
                    borderRadius: '20px',
                    padding: '24px',
                    marginBottom: '20px',
                    border: '1px solid rgba(255,255,255,0.06)',
                }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                        <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700' }}>📈 가격 차트 + 이동평균선</h2>
                        <div style={{ display: 'flex', gap: '16px', fontSize: '13px' }}>
                            <span><span style={{ color: '#007AFF' }}>━━</span> MA5</span>
                            <span><span style={{ color: '#FF9500' }}>━━</span> MA20</span>
                            <span><span style={{ color: '#636366' }}>┅┅</span> MA120</span>
                            <span><span style={{ color: '#5AC8FA', opacity: 0.3 }}>▓▓</span> BB</span>
                        </div>
                    </div>

                    <svg width={chartWidth} height={mainChartHeight} style={{ overflow: 'visible' }}>
                        {/* 볼린저 밴드 영역 */}
                        <defs>
                            <linearGradient id="bbGradient" x1="0" y1="0" x2="0" y2="1">
                                <stop offset="0%" stopColor="#5AC8FA" stopOpacity="0.15" />
                                <stop offset="50%" stopColor="#5AC8FA" stopOpacity="0.05" />
                                <stop offset="100%" stopColor="#5AC8FA" stopOpacity="0.15" />
                            </linearGradient>
                        </defs>
                        <path
                            d={data.map((_, idx) => {
                                if (!bb[idx].upper) return '';
                                const x = xScale(idx);
                                return `${idx === 19 ? 'M' : 'L'} ${x} ${yScale(bb[idx].upper!)}`;
                            }).join(' ') + data.slice().reverse().map((_, idx) => {
                                const origIdx = data.length - 1 - idx;
                                if (!bb[origIdx].lower) return '';
                                const x = xScale(origIdx);
                                return `L ${x} ${yScale(bb[origIdx].lower!)}`;
                            }).join(' ') + ' Z'}
                            fill="url(#bbGradient)"
                        />

                        {/* 가격 Y축 그리드 */}
                        {[60000, 65000, 70000, 75000, 80000].map(price => (
                            <g key={price}>
                                <line
                                    x1={margin.left}
                                    y1={yScale(price)}
                                    x2={chartWidth - margin.right}
                                    y2={yScale(price)}
                                    stroke="rgba(255,255,255,0.05)"
                                    strokeDasharray="4,4"
                                />
                                <text
                                    x={margin.left - 10}
                                    y={yScale(price)}
                                    textAnchor="end"
                                    alignmentBaseline="middle"
                                    fill="#636366"
                                    fontSize="11"
                                >
                                    {(price / 1000).toFixed(0)}K
                                </text>
                            </g>
                        ))}

                        {/* MA120 */}
                        <path
                            d={data.map((_, idx) => {
                                if (!ma120[idx]) return '';
                                return `${ma120[idx - 1] ? 'L' : 'M'} ${xScale(idx)} ${yScale(ma120[idx]!)}`;
                            }).join(' ')}
                            fill="none"
                            stroke="#636366"
                            strokeWidth="1.5"
                            strokeDasharray="4,4"
                        />

                        {/* MA20 */}
                        <path
                            d={data.map((_, idx) => {
                                if (!ma20[idx]) return '';
                                return `${ma20[idx - 1] ? 'L' : 'M'} ${xScale(idx)} ${yScale(ma20[idx]!)}`;
                            }).join(' ')}
                            fill="none"
                            stroke="#FF9500"
                            strokeWidth="2"
                        />

                        {/* MA5 */}
                        <path
                            d={data.map((_, idx) => {
                                if (!ma5[idx]) return '';
                                return `${ma5[idx - 1] ? 'L' : 'M'} ${xScale(idx)} ${yScale(ma5[idx]!)}`;
                            }).join(' ')}
                            fill="none"
                            stroke="#007AFF"
                            strokeWidth="2"
                        />

                        {/* 캔들스틱 */}
                        {data.map((d, idx) => {
                            const x = xScale(idx);
                            const candleWidth = Math.max(4, (chartWidth - margin.left - margin.right) / data.length * 0.6);
                            const isUp = d.close >= d.open;
                            const color = isUp ? '#FF3B30' : '#007AFF';

                            return (
                                <g key={idx}>
                                    {/* 심지 */}
                                    <line
                                        x1={x}
                                        y1={yScale(d.high)}
                                        x2={x}
                                        y2={yScale(d.low)}
                                        stroke={color}
                                        strokeWidth="1"
                                    />
                                    {/* 몸통 */}
                                    <rect
                                        x={x - candleWidth / 2}
                                        y={yScale(Math.max(d.open, d.close))}
                                        width={candleWidth}
                                        height={Math.max(2, Math.abs(yScale(d.open) - yScale(d.close)))}
                                        fill={isUp ? color : 'transparent'}
                                        stroke={color}
                                        strokeWidth="1"
                                    />
                                </g>
                            );
                        })}

                        {/* 매수 시그널 표시 */}
                        {signals.map((sig, idx) => {
                            const dataIdx = data.findIndex(d => d.day === -sig.day);
                            if (dataIdx === -1) return null;
                            const x = xScale(dataIdx);
                            const d = data[dataIdx];
                            const y = yScale(d.low) + 30;

                            return (
                                <g key={idx}>
                                    <circle
                                        cx={x}
                                        cy={y}
                                        r="18"
                                        fill={`${sig.color}30`}
                                        stroke={sig.color}
                                        strokeWidth="2"
                                    />
                                    <text
                                        x={x}
                                        y={y + 1}
                                        textAnchor="middle"
                                        alignmentBaseline="middle"
                                        fill={sig.color}
                                        fontSize="16"
                                        fontWeight="700"
                                    >
                                        {sig.icon}
                                    </text>
                                    <text
                                        x={x}
                                        y={y + 40}
                                        textAnchor="middle"
                                        fill={sig.color}
                                        fontSize="11"
                                        fontWeight="600"
                                    >
                                        {sig.label}
                                    </text>
                                    <line
                                        x1={x}
                                        y1={y - 18}
                                        x2={x}
                                        y2={yScale(d.low) + 5}
                                        stroke={sig.color}
                                        strokeWidth="1"
                                        strokeDasharray="3,3"
                                    />
                                </g>
                            );
                        })}

                        {/* X축 날짜 레이블 */}
                        {data.filter((_, idx) => idx % 10 === 0).map((d, idx) => (
                            <text
                                key={idx}
                                x={xScale(idx * 10)}
                                y={mainChartHeight - 5}
                                textAnchor="middle"
                                fill="#636366"
                                fontSize="11"
                            >
                                {d.date}
                            </text>
                        ))}
                    </svg>
                </div>

                {/* 보조 지표 패널들 */}
                <div style={{ display: 'flex', gap: '20px', marginBottom: '32px' }}>
                    {/* RSI 패널 */}
                    <div style={{
                        flex: 1,
                        background: 'rgba(0,0,0,0.4)',
                        borderRadius: '16px',
                        padding: '20px',
                        border: '1px solid rgba(255,255,255,0.06)',
                    }}>
                        <h3 style={{ margin: '0 0 12px', fontSize: '14px', fontWeight: '600', color: '#AF52DE' }}>
                            📊 RSI (14일)
                        </h3>
                        <svg width="100%" height={panelHeight} viewBox={`0 0 ${chartWidth} ${panelHeight}`} preserveAspectRatio="none">
                            {/* RSI 구간 배경 */}
                            <rect x={margin.left} y={rsiScale(70)} width={chartWidth - margin.left - margin.right} height={rsiScale(30) - rsiScale(70)} fill="rgba(175,82,222,0.05)" />

                            {/* 과매도 구간 강조 */}
                            {data.map((d, idx) => {
                                if (d.rsi > 30) return null;
                                const x = xScale(idx);
                                const width = (chartWidth - margin.left - margin.right) / data.length;
                                return (
                                    <rect
                                        key={idx}
                                        x={x - width / 2}
                                        y={rsiScale(70)}
                                        width={width}
                                        height={rsiScale(30) - rsiScale(70)}
                                        fill="rgba(52,199,89,0.2)"
                                    />
                                );
                            })}

                            {/* 임계선 */}
                            <line x1={margin.left} y1={rsiScale(70)} x2={chartWidth - margin.right} y2={rsiScale(70)} stroke="#636366" strokeDasharray="4,4" strokeWidth="1" />
                            <line x1={margin.left} y1={rsiScale(40)} x2={chartWidth - margin.right} y2={rsiScale(40)} stroke="#FF9500" strokeDasharray="4,4" strokeWidth="1" />
                            <line x1={margin.left} y1={rsiScale(30)} x2={chartWidth - margin.right} y2={rsiScale(30)} stroke="#FF3B30" strokeDasharray="4,4" strokeWidth="1" />

                            {/* RSI 라인 */}
                            <path
                                d={data.map((d, idx) => `${idx === 0 ? 'M' : 'L'} ${xScale(idx)} ${rsiScale(d.rsi)}`).join(' ')}
                                fill="none"
                                stroke="#AF52DE"
                                strokeWidth="2"
                            />

                            {/* 레이블 */}
                            <text x={chartWidth - margin.right + 8} y={rsiScale(70)} fill="#636366" fontSize="10" alignmentBaseline="middle">70</text>
                            <text x={chartWidth - margin.right + 8} y={rsiScale(40)} fill="#FF9500" fontSize="10" alignmentBaseline="middle">40</text>
                            <text x={chartWidth - margin.right + 8} y={rsiScale(30)} fill="#FF3B30" fontSize="10" alignmentBaseline="middle">30</text>
                        </svg>
                    </div>
                </div>

                <div style={{ display: 'flex', gap: '20px', marginBottom: '32px' }}>
                    {/* 수급 패널 */}
                    <div style={{
                        flex: 1,
                        background: 'rgba(0,0,0,0.4)',
                        borderRadius: '16px',
                        padding: '20px',
                        border: '1px solid rgba(255,255,255,0.06)',
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <h3 style={{ margin: 0, fontSize: '14px', fontWeight: '600' }}>
                                💰 수급 (외국인 + 기관)
                            </h3>
                            <div style={{ display: 'flex', gap: '12px', fontSize: '11px' }}>
                                <span><span style={{ color: '#007AFF' }}>■</span> 외국인</span>
                                <span><span style={{ color: '#FF9500' }}>■</span> 기관</span>
                            </div>
                        </div>
                        <svg width="100%" height={panelHeight} viewBox={`0 0 ${chartWidth} ${panelHeight}`} preserveAspectRatio="none">
                            <line x1={margin.left} y1="60" x2={chartWidth - margin.right} y2="60" stroke="rgba(255,255,255,0.1)" strokeWidth="1" />

                            {data.map((d, idx) => {
                                const x = xScale(idx);
                                const barWidth = Math.max(3, (chartWidth - margin.left - margin.right) / data.length * 0.35);

                                return (
                                    <g key={idx}>
                                        {/* 외국인 */}
                                        <rect
                                            x={x - barWidth - 1}
                                            y={d.foreignBuy > 0 ? flowScale(d.foreignBuy) : 60}
                                            width={barWidth}
                                            height={Math.abs(flowScale(d.foreignBuy) - 60)}
                                            fill={d.foreignBuy > 0 ? '#007AFF' : '#007AFF80'}
                                            opacity={d.foreignBuy > 0 ? 1 : 0.5}
                                        />
                                        {/* 기관 */}
                                        <rect
                                            x={x + 1}
                                            y={d.institutionBuy > 0 ? flowScale(d.institutionBuy) : 60}
                                            width={barWidth}
                                            height={Math.abs(flowScale(d.institutionBuy) - 60)}
                                            fill={d.institutionBuy > 0 ? '#FF9500' : '#FF950080'}
                                            opacity={d.institutionBuy > 0 ? 1 : 0.5}
                                        />
                                        {/* 3일 연속 순매수 표시 */}
                                        {foreignStreaks[idx] && (
                                            <text x={x} y="15" textAnchor="middle" fill="#FFD60A" fontSize="14">★</text>
                                        )}
                                    </g>
                                );
                            })}
                        </svg>
                    </div>

                    {/* 거래량 패널 */}
                    <div style={{
                        flex: 1,
                        background: 'rgba(0,0,0,0.4)',
                        borderRadius: '16px',
                        padding: '20px',
                        border: '1px solid rgba(255,255,255,0.06)',
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                            <h3 style={{ margin: 0, fontSize: '14px', fontWeight: '600' }}>
                                📊 거래량
                            </h3>
                            <span style={{ fontSize: '11px' }}><span style={{ color: '#FF3B30' }}>━</span> 20일 평균</span>
                        </div>
                        <svg width="100%" height={panelHeight} viewBox={`0 0 ${chartWidth} ${panelHeight}`} preserveAspectRatio="none">
                            {/* 20일 평균선 */}
                            <line
                                x1={margin.left}
                                y1={volumeScale(avgVolume)}
                                x2={chartWidth - margin.right}
                                y2={volumeScale(avgVolume)}
                                stroke="#FF3B30"
                                strokeWidth="1.5"
                            />

                            {data.map((d, idx) => {
                                const x = xScale(idx);
                                const barWidth = Math.max(4, (chartWidth - margin.left - margin.right) / data.length * 0.6);
                                const isHigh = d.volume >= avgVolume * 1.2;

                                return (
                                    <rect
                                        key={idx}
                                        x={x - barWidth / 2}
                                        y={volumeScale(d.volume)}
                                        width={barWidth}
                                        height={100 - volumeScale(d.volume)}
                                        fill={isHigh ? '#5AC8FA' : '#5AC8FA60'}
                                    />
                                );
                            })}
                        </svg>
                    </div>
                </div>

                {/* 시스템 단계별 설명 */}
                <div style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(3, 1fr)',
                    gap: '20px',
                    marginBottom: '32px',
                }}>
                    {/* Scout 단계 */}
                    <div style={{
                        background: 'linear-gradient(135deg, rgba(255,107,53,0.1) 0%, rgba(255,149,0,0.05) 100%)',
                        borderRadius: '16px',
                        padding: '24px',
                        border: '1px solid rgba(255,107,53,0.2)',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                            <span style={{ fontSize: '24px' }}>🔍</span>
                            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#FF6B35' }}>Scout 단계</h3>
                        </div>
                        <p style={{ margin: '0 0 12px', fontSize: '13px', color: '#8E8E93' }}>종목 발굴</p>
                        <ul style={{ margin: 0, padding: '0 0 0 16px', fontSize: '12px', lineHeight: '1.8', color: '#C7C7CC' }}>
                            <li><strong style={{ color: '#FF9500' }}>Hunter AI</strong>: 뉴스/공시 기반 정성 점수</li>
                            <li><strong style={{ color: '#FF9500' }}>Judge AI</strong>: 최종 거래 승인 결정</li>
                            <li>Hunter Score ≥ 70점: 매수 대상</li>
                            <li>Hunter Score ≥ 90점: Super Prime (+15%)</li>
                            <li>Trade Tier: TIER1, TIER2, RECON, BLOCKED</li>
                        </ul>
                    </div>

                    {/* buy-scanner 단계 */}
                    <div style={{
                        background: 'linear-gradient(135deg, rgba(0,122,255,0.1) 0%, rgba(90,200,250,0.05) 100%)',
                        borderRadius: '16px',
                        padding: '24px',
                        border: '1px solid rgba(0,122,255,0.2)',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                            <span style={{ fontSize: '24px' }}>📡</span>
                            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#007AFF' }}>buy-scanner 단계</h3>
                        </div>
                        <p style={{ margin: '0 0 12px', fontSize: '13px', color: '#8E8E93' }}>신호 탐지</p>
                        <div style={{ fontSize: '12px', lineHeight: '1.8', color: '#C7C7CC' }}>
                            <div style={{ marginBottom: '8px' }}>
                                <strong style={{ color: '#5AC8FA' }}>신호 종류:</strong>
                            </div>
                            <ul style={{ margin: 0, padding: '0 0 0 16px' }}>
                                <li>GOLDEN_CROSS: 5일 MA {'>'} 20일 MA</li>
                                <li>RSI_OVERSOLD: RSI ≤ 30</li>
                                <li>BB_LOWER: 볼린저 밴드 하단 터치</li>
                                <li>MOMENTUM: 5일 모멘텀 ≥ 3%</li>
                            </ul>
                            <div style={{ marginTop: '8px' }}>
                                <strong style={{ color: '#34C759' }}>Tier2 안전장치:</strong> 최소 3개 조건
                            </div>
                        </div>
                    </div>

                    {/* buy-executor 단계 */}
                    <div style={{
                        background: 'linear-gradient(135deg, rgba(52,199,89,0.1) 0%, rgba(48,209,88,0.05) 100%)',
                        borderRadius: '16px',
                        padding: '24px',
                        border: '1px solid rgba(52,199,89,0.2)',
                    }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
                            <span style={{ fontSize: '24px' }}>⚡</span>
                            <h3 style={{ margin: 0, fontSize: '16px', fontWeight: '700', color: '#34C759' }}>buy-executor 단계</h3>
                        </div>
                        <p style={{ margin: '0 0 12px', fontSize: '13px', color: '#8E8E93' }}>주문 실행</p>
                        <div style={{ fontSize: '12px', lineHeight: '1.8', color: '#C7C7CC' }}>
                            <div style={{ marginBottom: '8px' }}>
                                <strong style={{ color: '#30D158' }}>안전장치:</strong>
                            </div>
                            <ul style={{ margin: 0, padding: '0 0 0 16px' }}>
                                <li>일일 최대 매수: 3회</li>
                                <li>최대 포지션 비중: 15%</li>
                                <li>섹터 비중 제한: 30%</li>
                                <li>현금 비중 유지: 10%</li>
                                <li>중복 매수 방지 (Redis Lock)</li>
                            </ul>
                        </div>
                    </div>
                </div>

                {/* Factor Score 가중치 */}
                <div style={{
                    background: 'rgba(0,0,0,0.4)',
                    borderRadius: '16px',
                    padding: '24px',
                    border: '1px solid rgba(255,255,255,0.06)',
                    marginBottom: '32px',
                }}>
                    <h3 style={{ margin: '0 0 20px', fontSize: '16px', fontWeight: '700' }}>
                        🎯 Factor Score 가중치
                    </h3>
                    <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap' }}>
                        {[
                            { name: '모멘텀', score: 25, color: '#FF3B30' },
                            { name: '품질', score: 20, color: '#FF9500' },
                            { name: '가치', score: 15, color: '#FFD60A' },
                            { name: '기술적', score: 10, color: '#34C759' },
                            { name: '수급/뉴스', score: 5, color: '#007AFF' },
                            { name: '복합조건', score: 5, color: '#AF52DE', bonus: true },
                        ].map((factor, idx) => (
                            <div key={idx} style={{
                                flex: '1 1 calc(16.66% - 12px)',
                                minWidth: '120px',
                                background: `${factor.color}15`,
                                border: `1px solid ${factor.color}40`,
                                borderRadius: '12px',
                                padding: '16px',
                                textAlign: 'center',
                            }}>
                                <div style={{ fontSize: '24px', fontWeight: '800', color: factor.color }}>
                                    {factor.bonus ? '+' : ''}{factor.score}점
                                </div>
                                <div style={{ fontSize: '13px', color: '#C7C7CC', marginTop: '4px' }}>
                                    {factor.name} {factor.bonus && '보너스'}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* 시스템 철학 */}
                <div style={{
                    background: 'linear-gradient(135deg, rgba(175,82,222,0.1) 0%, rgba(191,90,242,0.05) 100%)',
                    borderRadius: '16px',
                    padding: '24px',
                    border: '1px solid rgba(175,82,222,0.2)',
                }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '16px', fontWeight: '700', color: '#BF5AF2' }}>
                        💡 Prime Jennie 핵심 철학
                    </h3>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '16px' }}>
                        {[
                            { icon: '🛡️', title: '보수적 접근', desc: '여러 조건이 복합적으로 충족될 때만 매수' },
                            { icon: '💹', title: '수급 중시', desc: '외국인 순매수는 55.5% 승률의 핵심 지표' },
                            { icon: '🤖', title: '기술적 + AI 융합', desc: '정량 지표(RSI, MA)와 LLM 뉴스 분석 조합' },
                            { icon: '⚖️', title: '리스크 관리', desc: '포지션 분산, 상관관계 체크, 역신호 필터링' },
                        ].map((item, idx) => (
                            <div key={idx} style={{
                                display: 'flex',
                                alignItems: 'flex-start',
                                gap: '12px',
                                padding: '12px',
                                background: 'rgba(0,0,0,0.2)',
                                borderRadius: '10px',
                            }}>
                                <span style={{ fontSize: '24px' }}>{item.icon}</span>
                                <div>
                                    <div style={{ fontWeight: '600', marginBottom: '4px' }}>{item.title}</div>
                                    <div style={{ fontSize: '12px', color: '#8E8E93' }}>{item.desc}</div>
                                </div>
                            </div>
                        ))}
                    </div>
                </div>

                {/* 푸터 */}
                <div style={{
                    marginTop: '32px',
                    padding: '20px',
                    textAlign: 'center',
                    color: '#636366',
                    fontSize: '12px',
                    borderTop: '1px solid rgba(255,255,255,0.06)',
                }}>
                    <div style={{ marginBottom: '8px' }}>
                        <strong style={{ color: '#8E8E93' }}>my-prime-jennie</strong> Trading System
                    </div>
                    <div>Generated: 2026-01-08 | Carbon & Silicons Team</div>
                </div>
            </div>
        </div>
    );
};

export default PrimeJennieChart;
