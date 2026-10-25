// File export helpers: PNGs tagged with their print DPI, and a single-page
// PDF at the exact paper size so printers don't rescale the sheet.

export function canvasToBlob(canvas, type = 'image/png', quality) {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (blob) => (blob ? resolve(blob) : reject(new Error('Canvas export failed'))),
      type,
      quality,
    )
  })
}

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

const CRC_TABLE = (() => {
  const table = new Uint32Array(256)
  for (let n = 0; n < 256; n += 1) {
    let c = n
    for (let k = 0; k < 8; k += 1) {
      c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1
    }
    table[n] = c >>> 0
  }
  return table
})()

function crc32(bytes) {
  let crc = 0xffffffff
  for (const byte of bytes) {
    crc = CRC_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8)
  }
  return (crc ^ 0xffffffff) >>> 0
}

// Insert a pHYs chunk after IHDR so image viewers and print dialogs know
// the intended physical size.
export async function pngWithDpi(canvas, dpi = 300) {
  const blob = await canvasToBlob(canvas, 'image/png')
  const png = new Uint8Array(await blob.arrayBuffer())
  const pixelsPerMetre = Math.round(dpi / 0.0254)

  const chunk = new Uint8Array(21)
  const view = new DataView(chunk.buffer)
  view.setUint32(0, 9)
  chunk.set([0x70, 0x48, 0x59, 0x73], 4) // "pHYs"
  view.setUint32(8, pixelsPerMetre)
  view.setUint32(12, pixelsPerMetre)
  chunk[16] = 1 // unit: metre
  view.setUint32(17, crc32(chunk.subarray(4, 17)))

  // 8-byte signature + IHDR (4 length + 4 type + 13 data + 4 crc).
  const ihdrEnd = 33
  return new Blob([png.subarray(0, ihdrEnd), chunk, png.subarray(ihdrEnd)], {
    type: 'image/png',
  })
}

// Build a one-page PDF with the canvas as a full-bleed JPEG.
export async function pdfFromCanvas(canvas, widthMm, heightMm) {
  const jpeg = new Uint8Array(
    await (await canvasToBlob(canvas, 'image/jpeg', 0.95)).arrayBuffer(),
  )
  const pt = (mm) => ((mm / 25.4) * 72).toFixed(2)
  const w = pt(widthMm)
  const h = pt(heightMm)
  const content = `q ${w} 0 0 ${h} 0 0 cm /Im0 Do Q`

  const encoder = new TextEncoder()
  const parts = []
  const offsets = []
  let length = 0

  const push = (chunk) => {
    const bytes = typeof chunk === 'string' ? encoder.encode(chunk) : chunk
    parts.push(bytes)
    length += bytes.length
  }
  const object = (id, body) => {
    offsets[id] = length
    push(`${id} 0 obj\n${body}\nendobj\n`)
  }

  push('%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
  object(1, '<< /Type /Catalog /Pages 2 0 R >>')
  object(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
  object(
    3,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${w} ${h}] /TrimBox [0 0 ${w} ${h}] ` +
      '/Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>',
  )

  offsets[4] = length
  push(
    `4 0 obj\n<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} ` +
      `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`,
  )
  push(jpeg)
  push('\nendstream\nendobj\n')

  object(5, `<< /Length ${content.length} >>\nstream\n${content}\nendstream`)

  const xref = length
  let table = 'xref\n0 6\n0000000000 65535 f \n'
  for (let id = 1; id <= 5; id += 1) {
    table += `${String(offsets[id]).padStart(10, '0')} 00000 n \n`
  }
  push(`${table}trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)

  return new Blob(parts, { type: 'application/pdf' })
}
