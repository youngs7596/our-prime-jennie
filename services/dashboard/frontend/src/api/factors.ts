import { api } from '../lib/api';

export interface Factor {
    key: string;
    value: any;
    desc: string;
    category: string;
}

export const getFactors = async (): Promise<Factor[]> => {
    const response = await api.get('/settings/factors');
    return response.data;
};
