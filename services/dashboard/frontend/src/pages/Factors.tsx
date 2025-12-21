import React, { useEffect, useState } from 'react';
import { Factor, getFactors } from '../api/factors';

const Factors: React.FC = () => {
    const [factors, setFactors] = useState<Factor[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [error, setError] = useState<string | null>(null);

    useEffect(() => {
        const fetchFactors = async () => {
            try {
                const data = await getFactors();
                setFactors(data);
            } catch (err: any) {
                console.error("Failed to fetch factors:", err);
                setError("팩터 정보를 불러오는데 실패했습니다.");
            } finally {
                setLoading(false);
            }
        };

        fetchFactors();
    }, []);

    // Group factors by category
    const groupedFactors = factors.reduce((acc, factor) => {
        const category = factor.category || '기타';
        if (!acc[category]) {
            acc[category] = [];
        }
        acc[category].push(factor);
        return acc;
    }, {} as Record<string, Factor[]>);

    // Category display order
    const categoryOrder = ['Buying', 'Selling', 'Risk', 'Strategy', 'General'];

    if (loading) return <div className="text-white">Loading...</div>;
    if (error) return <div className="text-red-500">{error}</div>;

    return (
                                                <span className="font-medium text-gray-700 dark:text-gray-200 font-mono text-sm">
                                                    {f.key}
                                                </span>
                                                <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200">
                                                    {String(f.value)}
                                                </span>
                                            </div >
    <p className="text-sm text-gray-500 dark:text-gray-400 leading-snug">
        {f.desc}
    </p>
                                        </div >
                                    ))}
                                </div >
                            </div >
                        );
                    })}

{/* Render remaining categories not in order list */ }
{
    Object.keys(groupedFactors).filter(c => !categoryOrder.includes(c)).map(category => (
        <div key={category} className="bg-white dark:bg-gray-800 shadow rounded-lg overflow-hidden border border-gray-200 dark:border-gray-700">
            <div className="bg-gray-50 dark:bg-gray-700 px-4 py-3 border-b border-gray-200 dark:border-gray-600">
                <h2 className="text-lg font-semibold text-gray-800 dark:text-gray-100">{category}</h2>
            </div>
            <div className="divide-y divide-gray-200 dark:divide-gray-700">
                {groupedFactors[category].map(f => (
                    <div key={f.key} className="px-4 py-3 hover:bg-gray-50 dark:hover:bg-gray-750 transition-colors">
                        <div className="flex justify-between items-start mb-1">
                            <span className="font-medium text-gray-700 dark:text-gray-200 font-mono text-sm">{f.key}</span>
                            <span className="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-800 dark:bg-gray-600 dark:text-gray-200">
                                {String(f.value)}
                            </span>
                        </div>
                        <p className="text-sm text-gray-500 dark:text-gray-400">{f.desc}</p>
                    </div>
                ))}
            </div>
        </div>
    ))
}
                </div >
            </div >
        </Layout >
    );
};

export default Factors;
