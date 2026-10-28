// Shared API helper: fetch + JSON parse + the "{ ok: true }" envelope check
// used by the backend endpoints.
window.fetchApi = async function (url, options = {}) {
  const response = await fetch(url, options);
  const payload = await response.json();
  return { response, payload, ok: response.ok && Boolean(payload && payload.ok) };
};
