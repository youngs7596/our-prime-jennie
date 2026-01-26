
import { api } from '../lib/api';

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

export interface ChartDataPoint {
    time: string;
    open: number;
    high: number;
    low: number;
    close: number;
    volume: number;
}

export interface LogicStatusResponse {
    stock_code: string;
    snapshot: LogicSnapshot | null;
    chart_data: ChartDataPoint[];
}

export const logicApi = {
    getStatus: async (stockCode: string): Promise<LogicStatusResponse> => {
        const response = await api.get(`/logic/status/${stockCode}`);
        return response.data;
    }
};
