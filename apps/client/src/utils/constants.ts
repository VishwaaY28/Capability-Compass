const PREFIX = (import.meta.env.BASE_URL ?? '/').replace(/\/$/, '');

const API_PREFIX = `${PREFIX}/api`;

export const API = {
  BASE_URL: () => API_PREFIX,
  ENDPOINTS: {
    CAPABILITIES: {
      BASE_URL: () => `${API_PREFIX}/capabilities`,
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

