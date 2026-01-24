import { useState, useEffect, useRef, useCallback } from 'react';

// Define the signal payload structure
export interface BuySignal {
    stock_code: string;
    stock_name: string;
    price: number;
    time: string;
    signal_type: string;
    reason: string;
    regime: string;
}

export interface WebSocketMessage {
    type: string;
    data: BuySignal;
}

interface UseWebSocketOptions {
    url?: string;
    onMessage?: (data: WebSocketMessage) => void;
}

export const useWebSocket = ({ url, onMessage }: UseWebSocketOptions = {}) => {
    const [isConnected, setIsConnected] = useState(false);
    const [lastMessage, setLastMessage] = useState<WebSocketMessage | null>(null);
    const wsRef = useRef<WebSocket | null>(null);

    // Default URL logic
    const defaultUrl = 'ws://localhost:8090/ws'; // For local dev
    // In production, you might want: const defaultUrl = `${window.location.protocol === 'https:' ? 'wss:' : 'ws:'}//${window.location.host}/ws`;
    const wsUrl = url || defaultUrl;

    const connect = useCallback(() => {
        try {
            if (wsRef.current?.readyState === WebSocket.OPEN) return;

            const ws = new WebSocket(wsUrl);
            wsRef.current = ws;

            ws.onopen = () => {
                console.log('✅ WebSocket Connected');
                setIsConnected(true);
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    // Helper: Handle ping/pong if backend sends custom ping text
                    if (event.data === 'ping') {
                        ws.send('pong');
                        return;
                    }

                    setLastMessage(data);
                    if (onMessage) {
                        onMessage(data);
                    }
                } catch (e) {
                    console.error('WebSocket Message Parse Error:', e);
                }
            };

            ws.onclose = () => {
                console.log('⚠️ WebSocket Disconnected');
                setIsConnected(false);
                wsRef.current = null;
                // Simple reconnect logic
                setTimeout(connect, 3000);
            };

            ws.onerror = (error) => {
                console.error('WebSocket Error:', error);
                ws.close();
            };
        } catch (e) {
            console.error('WebSocket Connection Failed:', e);
        }
    }, [wsUrl, onMessage]);

    useEffect(() => {
        connect();

        // Cleanup on unmount
        return () => {
            if (wsRef.current) {
                wsRef.current.close();
            }
        };
    }, [connect]);

    // Keep-alive (optional)
    useEffect(() => {
        const interval = setInterval(() => {
            if (wsRef.current?.readyState === WebSocket.OPEN) {
                wsRef.current.send('ping');
            }
        }, 30000);
        return () => clearInterval(interval);
    }, []);

    return { isConnected, lastMessage };
};
