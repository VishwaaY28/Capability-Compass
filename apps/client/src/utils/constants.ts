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
        WORKSPACES: {
            BASE_URL: () => '/api/workspaces',
            LIST: () => '',
            CREATE: () => '',
            BY_ID: (id: string | number) => `/${id}`,
            DOCUMENTS: (workspaceId: string | number) => `/${workspaceId}/documents`,
            DOCUMENT_BY_ID: (documentId: string | number) => `/documents/${documentId}`,
            CHUNKS: (documentId: string | number) => `/documents/${documentId}/chunks`,
            CHUNK_BY_ID: (chunkId: string | number) => `/chunks/${chunkId}`,
        },
    },
};
