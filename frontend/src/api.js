const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000';

function makeUrl(path, params = {}) {
  const url = new URL(path, API_BASE);
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') {
      url.searchParams.set(key, value);
    }
  });
  return url;
}

async function parseResponse(response) {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    const detail = payload?.detail ?? payload?.error ?? response.statusText;
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return payload;
}

export async function apiGet(path, params = {}) {
  const response = await fetch(makeUrl(path, params));
  return parseResponse(response);
}

export async function apiPost(path, body, params = {}) {
  const response = await fetch(makeUrl(path, params), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return parseResponse(response);
}
