import { useCallback } from 'react';


export type Vertical = {
	id: number;
	name: string;
	created_at: string;
	updated_at: string;
};

export type SubVertical = {
	id: number;
	name: string;
	vertical_id: number;
	created_at: string;
	updated_at: string;
};

export type Domain = Vertical;

export type Process = {
	id: number | string;
	name: string;
	level: string;
	description: string;
	category?: string;
	lifecycle_phase?: string;
	subprocesses?: SubProcess[];
	application?: string;
	api?: string;
};

export type SubProcess = {
	subprocess_id: number;
	subprocess_name: string;
	subprocess_description?: string;
	subprocess_category?: string;
	subprocess_application?: string;
	subprocess_api?: string;
	data_entities?: DataEntity[];
};

export type DataEntity = {
	data_entity_id: number;
	data_entity_name: string;
	data_entity_description?: string;
	data_elements?: DataElement[];
};

export type DataElement = {
	data_element_id: number;
	data_element_name: string;
	data_element_description?: string;
};

export type Capability = {
	id: number;
	vertical?: string;
	subvertical: string;
	name: string;
	description: string;
	processes: Process[];
};


const BASE_URL = '/api';

async function fetcher<T>(url: string, options?: RequestInit): Promise<T> {
	const res = await fetch(url, options);
	if (!res.ok) {
		const error = await res.text();
		throw new Error(error || 'API error');
	}
	return res.json();
}

export function useCapabilityApi() {

	const listVerticals = useCallback(async () => {
		return fetcher<Vertical[]>(`${BASE_URL}/verticals`);
	}, []);

	const createVertical = useCallback(async (data: Omit<Vertical, 'id' | 'created_at' | 'updated_at'>) => {
		const res = await fetcher<Vertical>(`${BASE_URL}/verticals`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const updateVertical = useCallback(async (id: number, data: Partial<Vertical>) => {
		const res = await fetcher<Vertical>(`${BASE_URL}/verticals/${id}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const deleteVertical = useCallback(async (id: number) => {
		await fetcher(`${BASE_URL}/verticals/${id}`, { method: 'DELETE' });
	}, []);

	const listSubVerticals = useCallback(async (verticalId?: number) => {
		if (verticalId) {
			return fetcher<SubVertical[]>(`${BASE_URL}/subverticals?vertical_id=${verticalId}`);
		}
		return fetcher<SubVertical[]>(`${BASE_URL}/subverticals`);
	}, []);

	const createSubVertical = useCallback(async (data: Omit<SubVertical, 'id' | 'created_at' | 'updated_at'>) => {
		const res = await fetcher<SubVertical>(`${BASE_URL}/subverticals`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const updateSubVertical = useCallback(async (id: number, data: Partial<SubVertical>) => {
		const res = await fetcher<SubVertical>(`${BASE_URL}/subverticals/${id}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const deleteSubVertical = useCallback(async (id: number) => {
		await fetcher(`${BASE_URL}/subverticals/${id}`, { method: 'DELETE' });
	}, []);

	// Legacy domain endpoints for backwards compatibility
	const listDomains = useCallback(async () => {
		return fetcher<Domain[]>(`${BASE_URL}/domains`);
	}, []);

	const createDomain = useCallback(async (data: Omit<Domain, 'id' | 'created_at' | 'updated_at'>) => {
		const res = await fetcher<Domain>(`${BASE_URL}/domains`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const updateDomain = useCallback(async (id: number, data: Partial<Domain>) => {
		const res = await fetcher<Domain>(`${BASE_URL}/domains/${id}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const deleteDomain = useCallback(async (id: number) => {
		await fetcher(`${BASE_URL}/domains/${id}`, { method: 'DELETE' });
	}, []);

	const listCapabilities = useCallback(async () => {
		return fetcher<Capability[]>(`${BASE_URL}/capabilities`);
	}, []);

	const createCapability = useCallback(async (data: Omit<Capability, 'id' | 'processes'>) => {
		// Accept either `subvertical` or `subvertical_id` in the payload and normalize to `subvertical_id`
		const payload: any = { ...data } as any;
		if ((payload as any).subvertical !== undefined && (payload as any).subvertical !== null) {
			// selectedSubVertical in UI may be a string; ensure it's a number when possible
			const parsed = Number((payload as any).subvertical);
			payload.subvertical_id = Number.isNaN(parsed) ? (payload as any).subvertical : parsed;
			delete payload.subvertical;
		}
		const res = await fetcher<Capability>(`${BASE_URL}/capabilities`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(payload),
		});
		return res;
	}, []);

	const updateCapability = useCallback(async (id: number, data: Partial<Capability>) => {
		const res = await fetcher<Capability>(`${BASE_URL}/capabilities/${id}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const deleteCapability = useCallback(async (id: number) => {
		await fetcher(`${BASE_URL}/capabilities/${id}`, { method: 'DELETE' });
	}, []);


	const listProcesses = useCallback(async (capabilityId?: number) => {
		if (capabilityId) {
			return fetcher<Process[]>(`${BASE_URL}/processes?capability_id=${capabilityId}`);
		}
		return fetcher<Process[]>(`${BASE_URL}/processes`);
	}, []);


	const createProcess = useCallback(async (data: any) => {
		const res = await fetcher<Process>(`${BASE_URL}/processes`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const createSubprocess = useCallback(async (data: { name: string; description: string; category?: string; parent_process_id: number }) => {
		const res = await fetcher<any>(`${BASE_URL}/subprocesses`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const updateProcess = useCallback(async (id: number, data: Partial<Process>) => {
		const res = await fetcher<Process>(`${BASE_URL}/processes/${id}`, {
			method: 'PUT',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify(data),
		});
		return res;
	}, []);

	const deleteProcess = useCallback(async (id: number) => {
		await fetcher(`${BASE_URL}/processes/${id}`, { method: 'DELETE' });
	}, []);

	const generateProcesses = useCallback(async (capabilityName: string, capabilityId: number, domain: string, processType: string, capabilityDescription: string = '', prompt: string) => {
		const res = await fetcher<any>(`${BASE_URL}/processes/generate`, {
			method: 'POST',
			headers: { 'Content-Type': 'application/json' },
			body: JSON.stringify({
				capability_name: capabilityName,
				capability_id: capabilityId,
				capability_description: capabilityDescription,
				domain: domain,
				process_type: processType,
				prompt: prompt,
			}),
		});
		return res;
	}, []);

	const getPromptTemplate = useCallback(async (processLevel: string) => {
		return fetcher<{ process_level: string; prompt: string }>(`${BASE_URL}/settings/prompt-template/${processLevel}`);
	}, []);

	return {
		// New vertical/subvertical API
		listVerticals,
		createVertical,
		updateVertical,
		deleteVertical,
		listSubVerticals,
		createSubVertical,
		updateSubVertical,
		deleteSubVertical,
		// Legacy domain API (for backwards compatibility)
		listDomains,
		createDomain,
		updateDomain,
		deleteDomain,
		listCapabilities,
		createCapability,
		updateCapability,
		deleteCapability,
		listProcesses,
		createProcess,
		createSubprocess,
		updateProcess,
		deleteProcess,
		generateProcesses,
		getPromptTemplate,
	};

}