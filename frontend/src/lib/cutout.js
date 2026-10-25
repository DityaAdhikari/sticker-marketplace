import { createCanvas, sourceSize } from './render.js'

// Large photos are processed at this size at most to keep the editor fast.
const MAX_SIDE = 2000

// Remove a roughly uniform background by flood-filling inward from the image
// border, then trim the transparent edges. Returns the cut-out canvas and the
// crop rectangle in original image pixels, or null if nothing is left.
export function removeBackground(image, tolerance) {
  const { w: srcW, h: srcH } = sourceSize(image)
  const factor = Math.min(1, MAX_SIDE / Math.max(srcW, srcH))
  const width = Math.max(1, Math.round(srcW * factor))
  const height = Math.max(1, Math.round(srcH * factor))

  const canvas = createCanvas(width, height)
  const ctx = canvas.getContext('2d', { willReadFrequently: true })
  ctx.drawImage(image, 0, 0, width, height)

  const imageData = ctx.getImageData(0, 0, width, height)
  const data = imageData.data
  const total = width * height
  const reference = borderColor(data, width, height)

  const distance = (i) => {
    if (data[i * 4 + 3] < 16) return 0
    if (!reference) return Infinity
    const dr = data[i * 4] - reference[0]
    const dg = data[i * 4 + 1] - reference[1]
    const db = data[i * 4 + 2] - reference[2]
    return Math.sqrt(dr * dr + dg * dg + db * db)
  }

  const background = new Uint8Array(total)
  const queue = new Int32Array(total)
  let head = 0
  let tail = 0

  const visit = (i) => {
    if (background[i] || distance(i) > tolerance) return
    background[i] = 1
    queue[tail++] = i
  }

  for (let x = 0; x < width; x += 1) {
    visit(x)
    visit((height - 1) * width + x)
  }
  for (let y = 0; y < height; y += 1) {
    visit(y * width)
    visit(y * width + width - 1)
  }

  while (head < tail) {
    const i = queue[head++]
    const x = i % width
    if (x > 0) visit(i - 1)
    if (x < width - 1) visit(i + 1)
    if (i >= width) visit(i - width)
    if (i < total - width) visit(i + width)
  }

  // Clear the background and soften pixels on the boundary so edges
  // don't look jagged.
  const softness = tolerance * 0.5 + 1
  for (let i = 0; i < total; i += 1) {
    if (background[i]) {
      data[i * 4 + 3] = 0
      continue
    }

    const x = i % width
    const touchesBackground =
      (x > 0 && background[i - 1]) ||
      (x < width - 1 && background[i + 1]) ||
      (i >= width && background[i - width]) ||
      (i < total - width && background[i + width])

    if (touchesBackground) {
      const t = Math.min(1, Math.max(0, (distance(i) - tolerance) / softness))
      data[i * 4 + 3] = Math.round(data[i * 4 + 3] * (0.35 + 0.65 * t))
    }
  }

  ctx.putImageData(imageData, 0, 0)

  const bounds = opaqueBounds(data, width, height)
  if (!bounds) return null

  const cropped = createCanvas(bounds.w, bounds.h)
  cropped
    .getContext('2d')
    .drawImage(canvas, bounds.x, bounds.y, bounds.w, bounds.h, 0, 0, bounds.w, bounds.h)

  return {
    canvas: cropped,
    crop: {
      x: bounds.x / factor,
      y: bounds.y / factor,
      w: bounds.w / factor,
      h: bounds.h / factor,
    },
  }
}

// The most common colour around the image edge, averaged within its bucket.
function borderColor(data, width, height) {
  const buckets = new Map()

  const add = (i) => {
    if (data[i * 4 + 3] < 16) return
    const r = data[i * 4]
    const g = data[i * 4 + 1]
    const b = data[i * 4 + 2]
    const key = ((r >> 4) << 8) | ((g >> 4) << 4) | (b >> 4)
    const bucket = buckets.get(key) ?? { count: 0, r: 0, g: 0, b: 0 }
    bucket.count += 1
    bucket.r += r
    bucket.g += g
    bucket.b += b
    buckets.set(key, bucket)
  }

  for (let x = 0; x < width; x += 1) {
    add(x)
    add((height - 1) * width + x)
  }
  for (let y = 1; y < height - 1; y += 1) {
    add(y * width)
    add(y * width + width - 1)
  }

  let best = null
  for (const bucket of buckets.values()) {
    if (!best || bucket.count > best.count) best = bucket
  }

  return best ? [best.r / best.count, best.g / best.count, best.b / best.count] : null
}

function opaqueBounds(data, width, height) {
  let minX = width
  let minY = height
  let maxX = -1
  let maxY = -1

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (data[(y * width + x) * 4 + 3] > 8) {
        if (x < minX) minX = x
        if (x > maxX) maxX = x
        if (y < minY) minY = y
        if (y > maxY) maxY = y
      }
    }
  }

  if (maxX < 0) return null
  return { x: minX, y: minY, w: maxX - minX + 1, h: maxY - minY + 1 }
}
