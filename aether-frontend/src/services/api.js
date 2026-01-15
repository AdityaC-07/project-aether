const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:8000";

export const analyzePdf = async (file) => {
	const formData = new FormData();
	formData.append("file", file);

	const res = await fetch(`${API_BASE}/analyze-pdf`, {
		method: "POST",
		body: formData,
	});

	if (!res.ok) {
		const detail = await res.text();
		throw new Error(detail || `Request failed with ${res.status}`);
	}

	return res.json();
};

export const analyzePdfReport = async (file) => {
	const formData = new FormData();
	formData.append("file", file);

	const res = await fetch(`${API_BASE}/analyze-pdf-report`, {
		method: "POST",
		body: formData,
	});

	if (!res.ok) {
		const detail = await res.text();
		throw new Error(detail || `Request failed with ${res.status}`);
	}

	const blob = await res.blob();
	return {
		blob,
		filename: res.headers.get('content-disposition')?.split('filename=')[1]?.replace(/"/g, '') || 'AETHER_Report.pdf'
	};
};

export const analyzeContext = async (context) => {
	const res = await fetch(`${API_BASE}/analyze`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(context),
	});

	if (!res.ok) {
		const detail = await res.text();
		throw new Error(detail || `Request failed with ${res.status}`);
	}

	return res.json();
};

export const analyzeContextReport = async (context) => {
	const res = await fetch(`${API_BASE}/analyze-report`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(context),
	});

	if (!res.ok) {
		const detail = await res.text();
		throw new Error(detail || `Request failed with ${res.status}`);
	}

	const blob = await res.blob();
	return {
		blob,
		filename: 'AETHER_Analysis_Report.pdf'
	};
};

export const downloadFile = (blob, filename) => {
	const url = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);
};
