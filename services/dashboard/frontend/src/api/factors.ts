
import axios from 'axios';
import { getAuthToken } from '../auth';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8090/api';

export interface Factor {
    key: string;
    value: any;
    desc: string;
    category: string;
}

export const getFactors = async (): Promise<Factor[]> => {
    const token = getAuthToken();
    const response = await axios.get(`${API_BASE_URL}/settings/factors`, {
        headers: { Authorization: `Bearer ${token}` }
    });
    return response.data;
};
