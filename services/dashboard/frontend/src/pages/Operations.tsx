import { useState, useEffect } from 'react';
import { Play, RotateCw, Terminal, Activity } from 'lucide-react';
import { useAuthStore } from '@/store/authStore';

export default function Operations() {
    const [activeTab, setActiveTab] = useState<'workflows' | 'logs'>('workflows');
    const [dags, setDags] = useState<any[]>([]);
    const [logs, setLogs] = useState<any[]>([]);
    const [selectedService, setSelectedService] = useState('scout-job');
    const [loading, setLoading] = useState(false);
    const [triggerLoading, setTriggerLoading] = useState<string | null>(null);
    const [timeRange, setTimeRange] = useState('1h');
    const { token } = useAuthStore();

    const SERVICES = [
        'scout-job', 'scout-worker',
        'buy-scanner', 'buy-executor', 'sell-executor',
        'price-monitor', 'kis-gateway',
        'news-collector', 'news-analyzer', 'news-archiver',
        'dashboard-backend'
    ];

    useEffect(() => {
        if (activeTab === 'workflows') {
            fetchDags();
        } else {
            fetchLogs();
        }
    }, [activeTab, selectedService, timeRange]);

    const fetchDags = async () => {
        setLoading(true);
        try {
            const res = await fetch('/api/airflow/dags', {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setDags(data);
            }
        } catch (error) {
            console.error(error);
        } finally {
            setLoading(false);
        }
    };

    const fetchLogs = async () => {
        // setLoading(true); // Don't block UI for logs
        try {
            const now = Date.now();
            let start = now - 60 * 60 * 1000; // default 1h

            if (timeRange === '5m') start = now - 5 * 60 * 1000;
            if (timeRange === '30m') start = now - 30 * 60 * 1000;
            if (timeRange === '1h') start = now - 60 * 60 * 1000;
            if (timeRange === '6h') start = now - 6 * 60 * 60 * 1000;

            const startNs = start * 1000000; // ms to ns

            const res = await fetch(`/api/logs/stream?service=${selectedService}&limit=1000&start=${startNs}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                const data = await res.json();
                setLogs(data.logs || []);
            }
        } catch (error) {
            console.error(error);
        } finally {
        }
    };

    const handleTrigger = async (dagId: string) => {
        setTriggerLoading(dagId);
        try {
            const res = await fetch(`/api/airflow/dags/${dagId}/trigger`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${token}` }
            });
            if (res.ok) {
                alert(`Triggered ${dagId}`);
                setTimeout(fetchDags, 2000); // usage refresh
            } else {
                alert('Failed to trigger');
            }
        } catch (error) {
            console.error(error);
        } finally {
            setTriggerLoading(null);
        }
    };

    return (
        <div className="p-6 max-w-7xl mx-auto">
            <div className="flex justify-between items-center mb-6">
                <h1 className="text-2xl font-bold text-gray-800 flex items-center gap-2">
                    <Activity className="w-6 h-6 text-blue-600" />
                    Operations Center
                </h1>
                <div className="flex gap-2 bg-gray-100 p-1 rounded-lg">
                    <button
                        onClick={() => setActiveTab('workflows')}
                        className={`px-4 py-2 rounded-md font-medium transition-all ${activeTab === 'workflows'
                            ? 'bg-white text-blue-600 shadow-sm'
                            : 'text-gray-500 hover:text-gray-700'
                            }`}
                    >
                        Workflows
                    </button>
                    <button
                        onClick={() => setActiveTab('logs')}
                        className={`px-4 py-2 rounded-md font-medium transition-all ${activeTab === 'logs'
                            ? 'bg-white text-blue-600 shadow-sm'
                            : 'text-gray-500 hover:text-gray-700'
                            }`}
                    >
                        System Logs
                    </button>
                </div>
            </div>

            {activeTab === 'workflows' ? (
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {loading && dags.length === 0 ? (
                        <div className="col-span-3 text-center py-12 text-gray-500">Loading Workflows...</div>
                    ) : (
                        dags.map(dag => (
                            <div key={dag.dag_id} className="bg-white rounded-xl shadow-sm border border-gray-100 p-5 hover:shadow-md transition-shadow">
                                <div className="flex justify-between items-start mb-4">
                                    <div>
                                        <h3 className="font-semibold text-gray-800 text-lg">{dag.dag_id}</h3>
                                        <p className="text-sm text-gray-500 mt-1 line-clamp-2">{dag.description || 'No description'}</p>
                                    </div>
                                    <span className={`px-2 py-1 rounded text-xs font-medium ${dag.last_run_state === 'success' ? 'bg-green-100 text-green-700' :
                                        dag.last_run_state === 'running' ? 'bg-blue-100 text-blue-700' :
                                            dag.last_run_state === 'failed' ? 'bg-red-100 text-red-700' :
                                                'bg-gray-100 text-gray-600'
                                        }`}>
                                        {dag.last_run_state || 'READY'}
                                    </span>
                                </div>

                                <div className="space-y-2 text-sm text-gray-600 mb-6">
                                    <div className="flex justify-between">
                                        <span>Schedule:</span>
                                        <span className="font-mono bg-gray-50 px-1 rounded">
                                            {typeof dag.schedule_interval === 'object' && dag.schedule_interval !== null
                                                ? (dag.schedule_interval.value || JSON.stringify(dag.schedule_interval))
                                                : (dag.schedule_interval || 'Manual')}
                                        </span>
                                    </div>
                                    <div className="flex justify-between">
                                        <span>Last Run:</span>
                                        <span>{dag.last_run_date ? new Date(dag.last_run_date).toLocaleString() : '-'}</span>
                                    </div>
                                </div>

                                <button
                                    onClick={() => handleTrigger(dag.dag_id)}
                                    disabled={triggerLoading === dag.dag_id}
                                    className="w-full flex items-center justify-center gap-2 bg-blue-50 text-blue-600 py-2 rounded-lg font-medium hover:bg-blue-100 transition-colors disabled:opacity-50"
                                >
                                    {triggerLoading === dag.dag_id ? (
                                        <RotateCw className="w-4 h-4 animate-spin" />
                                    ) : (
                                        <Play className="w-4 h-4" />
                                    )}
                                    Trigger Now
                                </button>
                            </div>
                        ))
                    )}
                </div>
            ) : (
                <div className="bg-[#1e1e1e] rounded-xl shadow-lg border border-gray-800 overflow-hidden flex flex-col h-[600px]">
                    <div className="bg-[#2d2d2d] px-4 py-3 flex items-center justify-between border-b border-gray-700">
                        <div className="flex items-center gap-2 text-gray-300">
                            <Terminal className="w-4 h-4" />
                            <span className="font-mono text-sm">/var/log/{selectedService}.log</span>
                        </div>
                        <div className="flex items-center gap-4">
                            <div className="flex bg-[#3d3d3d] rounded p-0.5">
                                {['5m', '30m', '1h', '6h'].map(range => (
                                    <button
                                        key={range}
                                        onClick={() => setTimeRange(range)}
                                        className={`px-3 py-1 text-xs font-medium rounded transition-colors ${timeRange === range
                                                ? 'bg-blue-600 text-white'
                                                : 'text-gray-400 hover:text-gray-200'
                                            }`}
                                    >
                                        {range}
                                    </button>
                                ))}
                            </div>
                            <select
                                value={selectedService}
                                onChange={(e) => setSelectedService(e.target.value)}
                                className="bg-[#3d3d3d] text-gray-200 text-sm rounded px-3 py-1 border-none focus:ring-1 focus:ring-blue-500 outline-none"
                            >
                                {SERVICES.map(s => (
                                    <option key={s} value={s}>{s}</option>
                                ))}
                            </select>
                            <button
                                onClick={fetchLogs}
                                className="text-gray-400 hover:text-white p-1 hover:bg-gray-700 rounded"
                            >
                                <RotateCw className="w-4 h-4" />
                            </button>
                        </div>
                    </div>

                    <div className="flex-1 overflow-auto p-4 font-mono text-xs md:text-sm">
                        {logs.length === 0 ? (
                            <div className="text-gray-500 italic">No logs found or loading...</div>
                        ) : (
                            logs.map((log, i) => (
                                <div key={i} className="mb-1 flex gap-3 hover:bg-[#2a2a2a] px-1 rounded">
                                    <span className="text-gray-500 shrink-0 select-none">
                                        {new Date(log.timestamp / 1000000).toLocaleTimeString('ko-KR')}
                                    </span>
                                    <span className="text-gray-300 break-all whitespace-pre-wrap">
                                        {log.message}
                                    </span>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
