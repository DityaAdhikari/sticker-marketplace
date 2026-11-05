// File export helpers: PNGs tagged with their print DPI, and a single-page
// PDF at the exact paper size (plus any bleed) so printers don't rescale
// the sheet.

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

const mmToPt = (mm) => (mm / 25.4) * 72
const num = (value) => value.toFixed(2)

async function deflate(text) {
  const bytes = new TextEncoder().encode(text)
  if (typeof CompressionStream === 'undefined') return { bytes, filter: '' }
  const stream = new Blob([bytes]).stream().pipeThrough(new CompressionStream('deflate'))
  return { bytes: new Uint8Array(await new Response(stream).arrayBuffer()), filter: '/Filter /FlateDecode ' }
}

// Build a one-page PDF: the sheet artwork as a JPEG filling the page and,
// optionally, the cut paths as vectors on their own "CutContour" layer in a
// CutContour spot colour (the name cutting software looks for).
//
// widthMm / heightMm are the trimmed page; bleedMm is added on every side.
// cutPaths are polygons of [x, y] mm from the top-left of the bleed area.
export async function pdfSheet({ canvas, widthMm, heightMm, bleedMm = 0, cutPaths = [] }) {
  const jpeg = new Uint8Array(
    await (await canvasToBlob(canvas, 'image/jpeg', 0.95)).arrayBuffer(),
  )
  const w = mmToPt(widthMm + 2 * bleedMm)
  const h = mmToPt(heightMm + 2 * bleedMm)
  const b = mmToPt(bleedMm)
  const hasCut = cutPaths.length > 0

  let content = `q ${num(w)} 0 0 ${num(h)} 0 0 cm /Im0 Do Q\n`
  if (hasCut) {
    // PDF y runs upwards from the bottom of the page.
    const lines = cutPaths.map((path) =>
      path
        .map(([x, y], i) => `${num(mmToPt(x))} ${num(h - mmToPt(y))} ${i ? 'l' : 'm'}`)
        .join('\n') + '\nh',
    )
    content += `/OC /Cut BDC q /CutColor CS 1 SCN 0.25 w 1 j\n${lines.join('\n')}\nS Q EMC\n`
  }
  const stream = await deflate(content)

  const encoder = new TextEncoder()
  const parts = []
  const offsets = {}
  let length = 0
  const push = (chunk) => {
    const bytes = typeof chunk === 'string' ? encoder.encode(chunk) : chunk
    parts.push(bytes)
    length += bytes.length
  }
  const object = (id, ...chunks) => {
    offsets[id] = length
    push(`${id} 0 obj\n`)
    chunks.forEach(push)
    push('\nendobj\n')
  }

  const layers = hasCut
    ? ' /OCProperties << /OCGs [6 0 R] /D << /Order [6 0 R] /ON [6 0 R] >> >>'
    : ''
  const resources = hasCut
    ? '/XObject << /Im0 4 0 R >> /ColorSpace << /CutColor 7 0 R >> /Properties << /Cut 6 0 R >>'
    : '/XObject << /Im0 4 0 R >>'

  push('%PDF-1.5\n%\xE2\xE3\xCF\xD3\n')
  object(1, `<< /Type /Catalog /Pages 2 0 R${layers} >>`)
  object(2, '<< /Type /Pages /Kids [3 0 R] /Count 1 >>')
  object(
    3,
    `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${num(w)} ${num(h)}] ` +
      `/BleedBox [0 0 ${num(w)} ${num(h)}] ` +
      `/TrimBox [${num(b)} ${num(b)} ${num(w - b)} ${num(h - b)}] ` +
      `/Resources << ${resources} >> /Contents 5 0 R >>`,
  )
  object(
    4,
    `<< /Type /XObject /Subtype /Image /Width ${canvas.width} /Height ${canvas.height} ` +
      `/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpeg.length} >>\nstream\n`,
    jpeg,
    '\nendstream',
  )
  object(5, `<< ${stream.filter}/Length ${stream.bytes.length} >>\nstream\n`, stream.bytes, '\nendstream')
  if (hasCut) {
    object(6, '<< /Type /OCG /Name (CutContour) >>')
    // Prints as 100% magenta where the spot colour isn't recognised.
    object(
      7,
      '[/Separation /CutContour /DeviceCMYK ' +
        '<< /FunctionType 2 /Domain [0 1] /C0 [0 0 0 0] /C1 [0 1 0 0] /N 1 >>]',
    )
  }

  const ids = Object.keys(offsets).map(Number)
  const size = Math.max(...ids) + 1
  const xref = length
  let table = `xref\n0 ${size}\n0000000000 65535 f \n`
  for (let id = 1; id < size; id += 1) {
    table += `${String(offsets[id]).padStart(10, '0')} 00000 n \n`
  }
  push(`${table}trailer\n<< /Size ${size} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF\n`)

  return new Blob(parts, { type: 'application/pdf' })
}
