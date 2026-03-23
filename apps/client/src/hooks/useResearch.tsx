import { useState } from "react";
import { API } from "../utils/constants";

export function useResearch() {
	const [results, setResults] = useState([]);
	const [isLoading, setIsLoading] = useState(false);
	const [error, setError] = useState<string>("");

	const research = async (query: string) => {
		setIsLoading(true);
		setError("");
		console.log("[useResearch] Starting research for query:", query);
		try {
			const res = await fetch(
				API.ENDPOINTS.CAPABILITIES.BASE_URL() + "/research",
				{
					method: "POST",
					headers: { "Content-Type": "application/json" },
					body: JSON.stringify({ query }),
				}
			);
			console.log("[useResearch] Response status:", res.status);
			
			if (!res.ok) throw new Error("Failed to fetch research results");
			const data = await res.json();
			console.log("[useResearch] Response data:", data);
			
			// Extract results array from response
			const resultsArray = data.results || data || [];
			console.log("[useResearch] Results array length:", resultsArray.length);
			console.log("[useResearch] Results types:", resultsArray.map((item: any) => item.type || "unknown"));
			
			setResults(resultsArray);
		} catch (err: any) {
			console.error("[useResearch] Error:", err);
			setError(err.message || "Unknown error");
			setResults([]);
		} finally {
			setIsLoading(false);
		}
	};

	return { research, results, isLoading, error };
}
