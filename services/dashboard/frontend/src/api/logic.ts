
import { api } from '../lib/api';

// Sell Logic Snapshot (from Price Monitor)
export interface LogicSnapshot {
    timestamp: string;
    stock_code: string;
    stock_name: string;
    current_price: number;
    buy_price: number;
    profit_pct: number;
    rsi: number | null;
    atr: number | null;
    stop_loss_price: number | null;
    take_profit_price: number | null;
    profit_floor_price: number | null;
    trailing_stop_price: number | null;
    is_safe: boolean;
    active_signal: {
        signal: boolean;
        reason: string;
        quantity_pct: number;
    } | null;
}

// Risk Gate Check Result
export interface RiskGateCheck {
    name: string;
    passed: boolean;
    value: string;
    threshold: string;
}

// Signal Check Result
export interface SignalCheck {
    strategy: string;
    triggered: boolean;
    reason: string;
}

// Buy Logic Snapshot (from Buy Scanner)
export interface BuyLogicSnapshot {
    timestamp: string;
    stock_code: string;
    stock_name: string;
    current_price: number;
    vwap: number;
    volume_ratio: number;
    rsi: number | null;
    market_regime: string;
    llm_score: number;
    trade_tier: string;
    risk_gate: {
        passed: boolean;
        checks: RiskGateCheck[];
    };
    signal_checks: SignalCheck[];
    triggered_signal: string | null;
}

// Signal History Entry
export interface SignalHistoryEntry {
    timestamp: string;
    type: 'BUY' | 'SELL';
    signal_type: string;
    reason: string;
    price: number;
}

export interface ChartDataPoint {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export type Timeframe = '1m' | '5m' | '1d';

export interface LogicStatusResponse {
    stock_code: string;
    snapshot: LogicSnapshot | null;
    buy_snapshot: BuyLogicSnapshot | null;
    signal_history: SignalHistoryEntry[];
    chart_data: ChartDataPoint[];
    timeframe: Timeframe;
}

export const logicApi = {
    getStatus: async (stockCode: string, timeframe: Timeframe = '1d'): Promise<LogicStatusResponse> => {
        const response = await api.get(`/logic/status/${stockCode}?timeframe=${timeframe}`);
        return response.data;
    }
};
