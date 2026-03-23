export const API = {
    BASE_URL: () => '',
    ENDPOINTS: {
        CAPABILITIES: {
            BASE_URL: () => '/api/capabilities',
            CREATE: () => '',
            LIST: () => '',
            BY_ID: (id: string | number) => `/${id}`,
            BY_NAME: (name: string) => `/by-name/${encodeURIComponent(name)}`,
            FILTER: () => '/filter',
            SEARCH: () => '/search',
            UPDATE: (id: string | number) => `/${id}`,
            DELETE_SOFT: (id: string | number) => `/soft/${id}`,
            DELETE_HARD: (id: string | number) => `/hard/${id}`,
        },
    },
};
