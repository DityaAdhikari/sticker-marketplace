// Thin client for the Flask studio API. Requests go to the same origin:
// Vite proxies /api and /static to Flask in development, and Flask serves
// the built studio at /studio in production.

// Flask pages (login, shop) live on the Flask server, not the Vite dev server.
export const FLASK_URL = import.meta.env.VITE_FLASK_URL ?? ''

// Flask rejects state-changing API calls without this header, which a
// cross-site form cannot send.
const CLIENT_HEADER = { 'X-StickerNest-Client': 'studio' }

async function request(path, { method = 'GET', body, json } = {}) {
  const headers = { ...CLIENT_HEADER }
  if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }

  const response = await fetch(path, {
    method,
    body,
    headers,
    credentials: 'same-origin',
  })

  const data = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(data.error || `Request failed (${response.status})`)
  }
  return data
}

export function getCurrentUser() {
  return request('/api/me').then((data) => data.user)
}

export function uploadAsset(blob, filename = 'asset.png') {
  const form = new FormData()
  form.append('file', blob, filename)
  return request('/api/studio/assets', { method: 'POST', body: form }).then(
    (data) => data.url,
  )
}

export function listDesigns() {
  return request('/api/studio/designs').then((data) => data.designs)
}

export function getDesign(id) {
  return request(`/api/studio/designs/${id}`).then((data) => data.design)
}

export function saveDesign({ id, title, data, thumbnail }) {
  const form = new FormData()
  form.append('title', title)
  form.append('data', JSON.stringify(data))
  if (thumbnail) form.append('thumbnail', thumbnail, 'thumbnail.jpg')

  return request(id ? `/api/studio/designs/${id}` : '/api/studio/designs', {
    method: id ? 'PUT' : 'POST',
    body: form,
  }).then((result) => result.design)
}

export function deleteDesign(id) {
  return request(`/api/studio/designs/${id}`, { method: 'DELETE' })
}
