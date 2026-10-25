// Canvas rendering for stickers and the A5 sheet.
// All sticker geometry is stored in "page units": the sheet is 500 × 710
// units, which maps to 148 × 210 mm. Effects are stored in millimetres.

export const PAGE = {
  widthMm: 148,
  heightMm: 210,
  width: 500,
  height: 710,
  exportWidth: 1748,
  exportHeight: 2480,
}

// Page units per millimetre.
export const MM = PAGE.width / PAGE.widthMm

export const PREVIEW_SCALE = 1.5
export const EXPORT_SCALE = PAGE.exportWidth / PAGE.width

export const TEXT_FONTS = [
  'Outfit',
  'DM Sans',
  'Bangers',
  'Pacifico',
  'Permanent Marker',
  'Georgia',
]

const TEXT_BASE_PX = 160

export function sourceSize(source) {
  return {
    w: source.naturalWidth || source.width,
    h: source.naturalHeight || source.height,
  }
}

export function createCanvas(width, height) {
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.ceil(width))
  canvas.height = Math.max(1, Math.ceil(height))
  return canvas
}

export function hexToRgba(hex, alpha = 1) {
  const value = hex.replace('#', '')
  const r = parseInt(value.slice(0, 2), 16)
  const g = parseInt(value.slice(2, 4), 16)
  const b = parseInt(value.slice(4, 6), 16)
  return `rgba(${r}, ${g}, ${b}, ${alpha})`
}

// How far the backdrop reaches beyond the content box, in page units.
function backdropExtent(sticker) {
  const { shape, padding } = sticker.backdrop
  if (shape === 'none') return { x: 0, y: 0 }

  const pad = padding * MM
  if (shape === 'circle') {
    const diameter = Math.max(sticker.width, sticker.height) + 2 * pad
    return {
      x: (diameter - sticker.width) / 2,
      y: (diameter - sticker.height) / 2,
    }
  }

  return { x: pad, y: pad }
}

// Total reach of backdrop + outline beyond the content box, in page units.
export function stickerExtent(sticker) {
  const backdrop = backdropExtent(sticker)
  const outline = sticker.outline.enabled ? sticker.outline.width * MM : 0
  return { x: backdrop.x + outline, y: backdrop.y + outline }
}

// Render one sticker (backdrop + artwork + outline) unrotated, without its
// shadow, at `scale` pixels per page unit.
export function renderSprite(sticker, scale) {
  const extent = stickerExtent(sticker)
  const margin = 2 / scale
  const padX = extent.x + margin
  const padY = extent.y + margin

  const content = createCanvas(
    (sticker.width + 2 * padX) * scale,
    (sticker.height + 2 * padY) * scale,
  )
  const ctx = content.getContext('2d')
  const ox = padX * scale
  const oy = padY * scale
  const w = sticker.width * scale
  const h = sticker.height * scale

  if (sticker.backdrop.shape !== 'none') {
    const reach = backdropExtent(sticker)
    const bx = ox - reach.x * scale
    const by = oy - reach.y * scale
    const bw = w + 2 * reach.x * scale
    const bh = h + 2 * reach.y * scale

    ctx.fillStyle = sticker.backdrop.color
    ctx.beginPath()
    if (sticker.backdrop.shape === 'circle') {
      ctx.arc(ox + w / 2, oy + h / 2, bw / 2, 0, Math.PI * 2)
    } else if (sticker.backdrop.shape === 'rounded') {
      ctx.roundRect(bx, by, bw, bh, Math.min(bw, bh) * 0.18)
    } else {
      ctx.rect(bx, by, bw, bh)
    }
    ctx.fill()
  }

  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(sticker.source, ox, oy, w, h)

  if (!sticker.outline.enabled || sticker.outline.width <= 0) {
    return { canvas: content, padX, padY }
  }

  const radius = sticker.outline.width * MM * scale
  const result = dilate(content, radius, sticker.outline.color)
  result.getContext('2d').drawImage(content, 0, 0)
  return { canvas: result, padX, padY }
}

// Build a die-cut style outline by growing the opaque silhouette by `radius`
// pixels using an exact Euclidean distance transform.
function dilate(canvas, radius, color) {
  const { width, height } = canvas
  const pixels = canvas.getContext('2d').getImageData(0, 0, width, height).data
  const grid = new Float64Array(width * height)

  for (let i = 0; i < grid.length; i += 1) {
    grid[i] = pixels[i * 4 + 3] > 127 ? 0 : INF
  }

  distanceTransform(grid, width, height)

  const out = createCanvas(width, height)
  const ctx = out.getContext('2d')
  const image = ctx.createImageData(width, height)
  const r = parseInt(color.slice(1, 3), 16)
  const g = parseInt(color.slice(3, 5), 16)
  const b = parseInt(color.slice(5, 7), 16)

  for (let i = 0; i < grid.length; i += 1) {
    const coverage = Math.min(1, radius - Math.sqrt(grid[i]) + 0.5)
    if (coverage <= 0) continue
    image.data[i * 4] = r
    image.data[i * 4 + 1] = g
    image.data[i * 4 + 2] = b
    image.data[i * 4 + 3] = Math.round(coverage * 255)
  }

  ctx.putImageData(image, 0, 0)
  return out
}

const INF = 1e20

// Felzenszwalb & Huttenlocher squared distance transform, in place.
function distanceTransform(grid, width, height) {
  const size = Math.max(width, height)
  const f = new Float64Array(size)
  const d = new Float64Array(size)
  const v = new Int32Array(size)
  const z = new Float64Array(size + 1)

  for (let x = 0; x < width; x += 1) {
    for (let y = 0; y < height; y += 1) f[y] = grid[y * width + x]
    transform1d(f, height, d, v, z)
    for (let y = 0; y < height; y += 1) grid[y * width + x] = d[y]
  }

  for (let y = 0; y < height; y += 1) {
    const row = y * width
    for (let x = 0; x < width; x += 1) f[x] = grid[row + x]
    transform1d(f, width, d, v, z)
    for (let x = 0; x < width; x += 1) grid[row + x] = d[x]
  }
}

function transform1d(f, n, d, v, z) {
  let k = 0
  v[0] = 0
  z[0] = -INF
  z[1] = INF

  for (let q = 1; q < n; q += 1) {
    let s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    while (s <= z[k]) {
      k -= 1
      s = (f[q] + q * q - (f[v[k]] + v[k] * v[k])) / (2 * q - 2 * v[k])
    }
    k += 1
    v[k] = q
    z[k] = s
    z[k + 1] = INF
  }

  k = 0
  for (let q = 0; q < n; q += 1) {
    while (z[k + 1] < q) k += 1
    const dq = q - v[k]
    d[q] = dq * dq + f[v[k]]
  }
}

function applyShadow(ctx, sticker, scale) {
  if (!sticker.shadow.enabled) return
  const { blur, offsetX, offsetY, color, opacity } = sticker.shadow

  // Shadow settings are in device pixels and ignore the current transform,
  // so the shadow always falls in the same direction on the page.
  ctx.shadowColor = hexToRgba(color, opacity)
  ctx.shadowBlur = blur * MM * scale
  ctx.shadowOffsetX = offsetX * MM * scale
  ctx.shadowOffsetY = offsetY * MM * scale
}

// Sprites only need re-rendering when size or effects change, not on move.
export function createSpriteCache() {
  const cache = new Map()

  return {
    get(sticker, scale) {
      const key = JSON.stringify([
        scale,
        sticker.width,
        sticker.height,
        sticker.outline,
        sticker.backdrop,
      ])
      const hit = cache.get(sticker.id)
      if (hit && hit.key === key && hit.source === sticker.source) {
        return hit.sprite
      }

      const sprite = renderSprite(sticker, scale)
      cache.set(sticker.id, { key, source: sticker.source, sprite })
      return sprite
    },
    prune(ids) {
      for (const id of cache.keys()) {
        if (!ids.has(id)) cache.delete(id)
      }
    },
  }
}

export function drawPage(
  canvas,
  items,
  { activeId = null, guides = false, background = '#ffffff', spriteCache } = {},
) {
  const ctx = canvas.getContext('2d')
  if (!ctx) return

  const scale = canvas.width / PAGE.width
  ctx.setTransform(1, 0, 0, 1, 0, 0)
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  if (background) {
    ctx.fillStyle = background
    ctx.fillRect(0, 0, canvas.width, canvas.height)
  }

  // Page-safe-area guide; it is not part of the export.
  if (guides) {
    ctx.save()
    ctx.strokeStyle = '#e4ded8'
    ctx.lineWidth = scale
    ctx.setLineDash([4 * scale, 4 * scale])
    ctx.strokeRect(18 * scale, 18 * scale, (PAGE.width - 36) * scale, (PAGE.height - 36) * scale)
    ctx.restore()
  }

  for (const sticker of items) {
    if (!sticker.source) continue

    const sprite = spriteCache
      ? spriteCache.get(sticker, scale)
      : renderSprite(sticker, scale)

    ctx.save()
    ctx.translate(
      (sticker.x + sticker.width / 2) * scale,
      (sticker.y + sticker.height / 2) * scale,
    )
    ctx.rotate((sticker.rotation * Math.PI) / 180)
    applyShadow(ctx, sticker, scale)
    ctx.drawImage(
      sprite.canvas,
      -(sticker.width / 2 + sprite.padX) * scale,
      -(sticker.height / 2 + sprite.padY) * scale,
    )
    ctx.restore()

    if (sticker.id === activeId && guides) {
      const extent = stickerExtent(sticker)
      const w = (sticker.width + 2 * extent.x) * scale
      const h = (sticker.height + 2 * extent.y) * scale

      ctx.save()
      ctx.translate(
        (sticker.x + sticker.width / 2) * scale,
        (sticker.y + sticker.height / 2) * scale,
      )
      ctx.rotate((sticker.rotation * Math.PI) / 180)
      ctx.strokeStyle = '#ff4b0b'
      ctx.lineWidth = 1.5 * scale
      ctx.setLineDash([4 * scale, 3 * scale])
      ctx.strokeRect(-w / 2, -h / 2, w, h)
      ctx.restore()
    }
  }
}

// A single sticker on a transparent canvas, rotated and with its shadow,
// at print resolution. Used for individual downloads and shop publishing.
export function renderStickerImage(sticker, scale = EXPORT_SCALE) {
  const sprite = renderSprite(sticker, scale)
  const sw = sprite.canvas.width
  const sh = sprite.canvas.height
  const angle = (sticker.rotation * Math.PI) / 180
  const cos = Math.abs(Math.cos(angle))
  const sin = Math.abs(Math.sin(angle))

  let shadowPad = 0
  if (sticker.shadow.enabled) {
    const { blur, offsetX, offsetY } = sticker.shadow
    shadowPad = (blur + Math.max(Math.abs(offsetX), Math.abs(offsetY))) * MM * scale
  }

  const canvas = createCanvas(
    sw * cos + sh * sin + 2 * shadowPad,
    sw * sin + sh * cos + 2 * shadowPad,
  )
  const ctx = canvas.getContext('2d')
  ctx.translate(canvas.width / 2, canvas.height / 2)
  ctx.rotate(angle)
  applyShadow(ctx, sticker, scale)
  ctx.drawImage(sprite.canvas, -sw / 2, -sh / 2)
  return canvas
}

// Render text to a high-resolution canvas that is then treated like an image.
export async function renderTextSource(text) {
  const font = `${text.italic ? 'italic ' : ''}${text.bold ? 700 : 400} ${TEXT_BASE_PX}px "${text.font}"`

  try {
    await document.fonts.load(font, text.content)
  } catch {
    // Fall back to whatever font the browser picks.
  }

  const lines = (text.content || ' ').split('\n')
  const measure = createCanvas(1, 1).getContext('2d')
  measure.font = font
  const pad = TEXT_BASE_PX * 0.12
  const lineHeight = TEXT_BASE_PX * 1.25
  const maxWidth = Math.max(
    TEXT_BASE_PX * 0.3,
    ...lines.map((line) => measure.measureText(line).width),
  )

  const canvas = createCanvas(maxWidth + 2 * pad, lines.length * lineHeight + pad)
  const ctx = canvas.getContext('2d')
  ctx.font = font
  ctx.fillStyle = text.color
  ctx.textBaseline = 'middle'
  ctx.textAlign = text.align

  const x =
    text.align === 'left' ? pad : text.align === 'right' ? canvas.width - pad : canvas.width / 2

  lines.forEach((line, index) => {
    ctx.fillText(line, x, pad / 2 + lineHeight * (index + 0.5))
  })

  return canvas
}
