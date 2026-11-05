// Sheet layout: keeping stickers inside the safe margin and apart from each
// other so they can be cut cleanly. Everything is in page units.
import { MM, SAFE_MARGIN_MM, STICKER_SPACING_MM, stickerExtent } from './render.js'

// Axis-aligned box around a sticker's printed area (artwork, backdrop and
// outline; not the shadow), allowing for rotation.
export function stickerBounds(sticker) {
  const extent = stickerExtent(sticker)
  const w = sticker.width + 2 * extent.x
  const h = sticker.height + 2 * extent.y
  const angle = (sticker.rotation * Math.PI) / 180
  const cos = Math.abs(Math.cos(angle))
  const sin = Math.abs(Math.sin(angle))
  const bw = w * cos + h * sin
  const bh = w * sin + h * cos
  const cx = sticker.x + sticker.width / 2
  const cy = sticker.y + sticker.height / 2

  return { left: cx - bw / 2, top: cy - bh / 2, right: cx + bw / 2, bottom: cy + bh / 2 }
}

// Stickers crossing the safe margin, and pairs closer than the spacing.
// Boxes are used for rotated stickers too, so a close rotated pair may be
// reported even when the shapes themselves have room.
export function layoutIssues(stickers, page) {
  const margin = SAFE_MARGIN_MM * MM
  const gap = STICKER_SPACING_MM * MM - 0.01
  const boxes = stickers.map((sticker) => ({ id: sticker.id, ...stickerBounds(sticker) }))

  const outside = boxes.filter(
    (box) =>
      box.left < margin - 0.01 ||
      box.top < margin - 0.01 ||
      box.right > page.width - margin + 0.01 ||
      box.bottom > page.height - margin + 0.01,
  )

  const tooClose = new Set()
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) {
      const a = boxes[i]
      const b = boxes[j]
      const dx = Math.max(b.left - a.right, a.left - b.right)
      const dy = Math.max(b.top - a.bottom, a.top - b.bottom)
      if (dx < gap && dy < gap) {
        tooClose.add(a.id)
        tooClose.add(b.id)
      }
    }
  }

  return { outside: outside.map((box) => box.id), tooClose: [...tooClose] }
}

// Pack stickers into rows inside the safe area with the cutting gap between
// them, tallest first. Returns the new { id: { x, y } } positions, or null
// if they don't all fit on the page.
export function arrangeStickers(stickers, page) {
  const margin = SAFE_MARGIN_MM * MM
  const gap = STICKER_SPACING_MM * MM
  const right = page.width - margin
  const bottom = page.height - margin

  const items = stickers
    .map((sticker) => {
      const box = stickerBounds(sticker)
      return { sticker, w: box.right - box.left, h: box.bottom - box.top }
    })
    .sort((a, b) => b.h - a.h)

  const positions = {}
  let x = margin
  let y = margin
  let rowHeight = 0

  for (const item of items) {
    if (x > margin && x + item.w > right) {
      x = margin
      y += rowHeight + gap
      rowHeight = 0
    }

    if (x + item.w > right + 0.01 || y + item.h > bottom + 0.01) return null

    const { sticker } = item
    positions[sticker.id] = {
      x: x + item.w / 2 - sticker.width / 2,
      y: y + item.h / 2 - sticker.height / 2,
    }

    x += item.w + gap
    rowHeight = Math.max(rowHeight, item.h)
  }

  return positions
}

// After a paper change: keep each sticker's printed size, but shrink any
// that no longer fit and move them back onto the page.
export function fitStickersToPage(stickers, page) {
  return stickers.map((sticker) => {
    const fit = Math.min(1, page.width / sticker.width, page.height / sticker.height)
    const width = sticker.width * fit
    const height = sticker.height * fit
    const cx = sticker.x + sticker.width / 2
    const cy = sticker.y + sticker.height / 2

    return {
      ...sticker,
      width,
      height,
      x: Math.min(Math.max(cx - width / 2, 0), page.width - width),
      y: Math.min(Math.max(cy - height / 2, 0), page.height - height),
    }
  })
}
