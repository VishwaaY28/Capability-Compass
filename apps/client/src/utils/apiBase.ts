export const API_BASE =
  `${(import.meta.env.BASE_URL ?? '/').replace(/\/$/, '')}/api`;

export function apiUrl(path: string): string {
  return `${API_BASE}/${path.replace(/^\//, '')}`;
}
