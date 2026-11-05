// Cut lines: the outer edge of each sticker's printed shape (artwork,
// backdrop and outline, not the shadow), traced from its 300 DPI render and
// returned as closed polygons in millimetres on the exported page.
import { EXPORT_SCALE, MM, createCanvas, renderSprite } from './render.js'

// Ignore specks smaller than this many square pixels (~0.2 mm² at 300 DPI).
const MIN_AREA_PX = 30
// How far a simplified line may stray from the traced edge, in pixels.
const SIMPLIFY_PX = 0.75

// Trace the boundaries of the opaque pixels. Each pixel edge between an
// opaque and a clear pixel becomes a directed edge with the opaque side on
// its right, so outer edges run clockwise (positive area) and holes run the
// other way.
function traceLoops(mask, width, height) {
  const stride = width + 1
  const outgoing = new Map()
  const filled = (x, y) => x >= 0 && y >= 0 && x < width && y < height && mask[y * width + x]
  const addEdge = (x1, y1, x2, y2) => {
    const key = y1 * stride + x1
    const list = outgoing.get(key)
    const target = y2 * stride + x2
    if (list) list.push(target)
    else outgoing.set(key, [target])
  }

  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (!mask[y * width + x]) continue
      if (!filled(x, y - 1)) addEdge(x, y, x + 1, y)
      if (!filled(x + 1, y)) addEdge(x + 1, y, x + 1, y + 1)
      if (!filled(x, y + 1)) addEdge(x + 1, y + 1, x, y + 1)
      if (!filled(x - 1, y)) addEdge(x, y + 1, x, y)
    }
  }

  const loops = []

  for (const [start, list] of outgoing) {
    while (list.length) {
      const points = []
      let current = start
      let dx = 0
      let dy = 0

      do {
        const candidates = outgoing.get(current)
        const cx = current % stride
        const cy = (current - cx) / stride

        // Where two diagonal pixels touch, turn right (towards the opaque
        // side) so each keeps its own loop instead of the line crossing.
        let index = 0
        if (candidates.length > 1) {
          const right = candidates.findIndex((target) => {
            const tx = target % stride
            const ty = (target - tx) / stride
            return tx - cx === -dy && ty - cy === dx
          })
          if (right !== -1) index = right
        }

        const next = candidates.splice(index, 1)[0]
        const nx = next % stride
        const ny = (next - nx) / stride

        // Keep only the corners of the staircase.
        if (nx - cx !== dx || ny - cy !== dy) points.push([cx, cy])
        dx = nx - cx
        dy = ny - cy
        current = next
      } while (current !== start && outgoing.get(current)?.length)

      if (points.length >= 3) loops.push(points)
    }
  }

  return loops
}

function signedArea(points) {
  let sum = 0
  for (let i = 0; i < points.length; i += 1) {
    const [x1, y1] = points[i]
    const [x2, y2] = points[(i + 1) % points.length]
    sum += x1 * y2 - x2 * y1
  }
  return sum / 2
}

// Ramer–Douglas–Peucker on an open line.
function simplifyLine(points, tolerance) {
  if (points.length < 3) return points

  const [ax, ay] = points[0]
  const [bx, by] = points[points.length - 1]
  const length = Math.hypot(bx - ax, by - ay) || 1
  let worst = 0
  let index = 0

  for (let i = 1; i < points.length - 1; i += 1) {
    const [px, py] = points[i]
    const distance = Math.abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
    if (distance > worst) {
      worst = distance
      index = i
    }
  }

  if (worst <= tolerance) return [points[0], points[points.length - 1]]

  const head = simplifyLine(points.slice(0, index + 1), tolerance)
  const tail = simplifyLine(points.slice(index), tolerance)
  return [...head.slice(0, -1), ...tail]
}

// Split a closed loop at its two most distant points and simplify each half.
function simplifyLoop(points, tolerance) {
  const [sx, sy] = points[0]
  let far = 0
  let best = -1
  points.forEach(([x, y], i) => {
    const distance = (x - sx) ** 2 + (y - sy) ** 2
    if (distance > best) {
      best = distance
      far = i
    }
  })

  const first = simplifyLine(points.slice(0, far + 1), tolerance)
  const second = simplifyLine([...points.slice(far), points[0]], tolerance)
  return [...first.slice(0, -1), ...second.slice(0, -1)]
}

// Outer cut paths of one sticker, in sprite pixels.
function stickerLoops(sprite) {
  const { width, height } = sprite.canvas
  const alpha = sprite.canvas.getContext('2d').getImageData(0, 0, width, height).data
  const mask = new Uint8Array(width * height)
  for (let i = 0; i < mask.length; i += 1) mask[i] = alpha[i * 4 + 3] >= 128 ? 1 : 0

  return traceLoops(mask, width, height)
    .filter((loop) => signedArea(loop) >= MIN_AREA_PX)
    .map((loop) => simplifyLoop(loop, SIMPLIFY_PX))
    .filter((loop) => loop.length >= 3)
}

// Cut paths for the whole sheet as polygons of [x, y] millimetres from the
// top-left of the exported page (including any bleed).
export function sheetCutPaths(stickers, bleedMm = 0) {
  const scale = EXPORT_SCALE
  const paths = []

  for (const sticker of stickers) {
    if (!sticker.source) continue

    const sprite = renderSprite(sticker, scale)
    const angle = (sticker.rotation * Math.PI) / 180
    const cos = Math.cos(angle)
    const sin = Math.sin(angle)
    const cx = sticker.x + sticker.width / 2
    const cy = sticker.y + sticker.height / 2
    const offsetX = sticker.width / 2 + sprite.padX
    const offsetY = sticker.height / 2 + sprite.padY

    for (const loop of stickerLoops(sprite)) {
      paths.push(
        loop.map(([px, py]) => {
          // Sprite pixels -> page units around the sticker centre, rotated
          // the same way drawPage draws it.
          const ux = px / scale - offsetX
          const uy = py / scale - offsetY
          return [
            (cx + ux * cos - uy * sin) / MM + bleedMm,
            (cy + ux * sin + uy * cos) / MM + bleedMm,
          ]
        }),
      )
    }
  }

  return paths
}

// The cut paths drawn on their own transparent canvas, the same size as the
// sheet export, for printers that take the cutline as a separate image.
export function renderCutlineCanvas(paths, width, height, pixelsPerMm) {
  const canvas = createCanvas(width, height)
  const ctx = canvas.getContext('2d')
  ctx.strokeStyle = '#EC008C'
  ctx.lineWidth = Math.max(1, 0.25 * pixelsPerMm)
  ctx.lineJoin = 'round'
  ctx.beginPath()

  for (const path of paths) {
    path.forEach(([x, y], i) => {
      if (i === 0) ctx.moveTo(x * pixelsPerMm, y * pixelsPerMm)
      else ctx.lineTo(x * pixelsPerMm, y * pixelsPerMm)
    })
    ctx.closePath()
  }

  ctx.stroke()
  return canvas
}
