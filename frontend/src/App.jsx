import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import './App.css'
import {
  EXPORT_SCALE,
  MM,
  PAGE,
  PREVIEW_SCALE,
  TEXT_FONTS,
  createCanvas,
  createSpriteCache,
  drawPage,
  renderStickerImage,
  renderTextSource,
  sourceSize,
  stickerExtent,
} from './lib/render.js'
import { removeBackground } from './lib/cutout.js'
import { canvasToBlob, downloadBlob, pdfFromCanvas, pngWithDpi } from './lib/exportFile.js'
import {
  FLASK_URL,
  deleteDesign,
  getCurrentUser,
  getDesign,
  listDesigns,
  saveDesign,
  uploadAsset,
} from './lib/api.js'

const DRAFT_KEY = 'stickernest-a5-draft'
const DRAFT_VERSION = 2

const DEFAULT_SHEET = { color: '#ffffff', transparent: false }

const DEFAULT_TEXT = {
  content: 'Hello!',
  font: 'Bangers',
  color: '#ff4b0b',
  bold: false,
  italic: false,
  align: 'center',
}

function defaultEffects() {
  return {
    outline: { enabled: false, width: 2, color: '#ffffff' },
    shadow: {
      enabled: false,
      blur: 2,
      offsetX: 0.8,
      offsetY: 1.2,
      color: '#000000',
      opacity: 0.35,
    },
    backdrop: { shape: 'none', color: '#ffffff', padding: 3 },
  }
}

const clamp = (value, min, max) => Math.min(max, Math.max(min, value))
const round1 = (value) => Math.round(value * 10) / 10

function slugify(name) {
  return (
    name
      .replace(/\.[a-z0-9]+$/i, '')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-|-$/g, '') || 'sticker'
  )
}

function fileToDataURL(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(new Error('Could not read file'))
    reader.readAsDataURL(file)
  })
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image()
    image.onload = () => resolve(image)
    image.onerror = () => reject(new Error(`Could not load ${src.slice(0, 60)}`))
    image.src = src
  })
}

// Only plain data is stored; images and text are re-rendered on load.
function serializeSticker(sticker) {
  // eslint-disable-next-line no-unused-vars
  const { source, original, crop, ...data } = sticker
  return data
}

async function hydrateSticker(data) {
  const effects = defaultEffects()
  const sticker = {
    kind: 'image',
    rotation: 0,
    ...data,
    outline: { ...effects.outline, ...data.outline },
    shadow: { ...effects.shadow, ...data.shadow },
    backdrop: { ...effects.backdrop, ...data.backdrop },
  }

  if (sticker.kind === 'text') {
    sticker.text = { ...DEFAULT_TEXT, ...data.text }
    sticker.source = await renderTextSource(sticker.text)
    return sticker
  }

  // Version 1 drafts stored the image as `imageUrl`.
  sticker.originalUrl = data.originalUrl ?? data.imageUrl
  delete sticker.imageUrl
  sticker.cutout = { enabled: false, tolerance: 40, ...data.cutout }
  sticker.original = await loadImage(sticker.originalUrl)

  const { w, h } = sourceSize(sticker.original)
  sticker.source = sticker.original
  sticker.crop = { x: 0, y: 0, w, h }

  if (sticker.cutout.enabled) {
    const result = removeBackground(sticker.original, sticker.cutout.tolerance)
    if (result) {
      sticker.source = result.canvas
      sticker.crop = result.crop
    }
  }

  return sticker
}

// Re-map an image sticker onto a new crop of its original image so the
// artwork stays where it was on the sheet.
function refitCrop(sticker, source, crop) {
  const kx = sticker.width / sticker.crop.w
  const ky = sticker.height / sticker.crop.h
  return {
    source,
    crop,
    x: sticker.x + (crop.x - sticker.crop.x) * kx,
    y: sticker.y + (crop.y - sticker.crop.y) * ky,
    width: crop.w * kx,
    height: crop.h * ky,
  }
}

// Keep the text at the same size per letter when its content changes.
function refitText(sticker, source) {
  const previous = sourceSize(sticker.source)
  const next = sourceSize(source)
  const width = next.w * (sticker.width / previous.w)
  const height = next.h * (sticker.height / previous.h)
  return {
    source,
    width,
    height,
    x: sticker.x + (sticker.width - width) / 2,
    y: sticker.y + (sticker.height - height) / 2,
  }
}

// Numeric input that commits valid values while typing and reverts on blur.
function NumberField({ label, value, onCommit, min, max, step = 0.5, suffix }) {
  const [draft, setDraft] = useState(null)

  return (
    <label className="number-field">
      <span>{label}</span>
      <div>
        <input
          type="number"
          value={draft ?? String(round1(value))}
          min={min}
          max={max}
          step={step}
          onChange={(event) => {
            const text = event.target.value
            setDraft(text)
            const number = Number(text)
            if (text !== '' && Number.isFinite(number) && number >= min && number <= max) {
              onCommit(number)
            }
          }}
          onBlur={() => setDraft(null)}
        />
        <em>{suffix}</em>
      </div>
    </label>
  )
}

function Toggle({ label, checked, onChange }) {
  return (
    <label className="check-row">
      <input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} />
      {label}
    </label>
  )
}

function ColorField({ label, value, onChange }) {
  return (
    <label className="color-row field-label">
      {label}
      <input
        className="color-input"
        type="color"
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  )
}

function RangeField({ label, value, display, min, max, step, onChange }) {
  return (
    <>
      <label className="field-label">
        {label}
        <span>{display}</span>
      </label>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(event) => onChange(Number(event.target.value))}
      />
    </>
  )
}

function App() {
  const canvasRef = useRef(null)
  const fileInputRef = useRef(null)
  const stickersRef = useRef([])
  const dragRef = useRef(null)
  const nextId = useRef(1)
  const textJobs = useRef(new Map())
  const cutoutTimer = useRef(null)

  const [spriteCache] = useState(createSpriteCache)
  const [stickers, setStickers] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [sheet, setSheet] = useState(DEFAULT_SHEET)
  const [lockRatio, setLockRatio] = useState(true)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState(
    'Upload images to start arranging your A5 sheet.',
  )

  // Flask account state. `undefined` while loading, `null` when logged out.
  const [user, setUser] = useState(undefined)
  const [apiOffline, setApiOffline] = useState(false)
  const [designs, setDesigns] = useState([])
  const [currentDesign, setCurrentDesign] = useState(null)
  const [designTitle, setDesignTitle] = useState('My sticker sheet')

  const selectedSticker =
    stickers.find((sticker) => sticker.id === selectedId) ?? null
  const selectedIndex = stickers.findIndex((sticker) => sticker.id === selectedId)
  const sheetBackground = sheet.transparent ? null : sheet.color

  // Keep refs synchronized for pointer events and timers.
  useEffect(() => {
    stickersRef.current = stickers
  }, [stickers])

  const updateSticker = useCallback((id, changes) => {
    setStickers((current) =>
      current.map((sticker) =>
        sticker.id === id ? { ...sticker, ...changes } : sticker,
      ),
    )
  }, [])

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    drawPage(canvas, stickers, {
      activeId: selectedId,
      guides: true,
      background: sheetBackground,
      spriteCache,
    })
    spriteCache.prune(new Set(stickers.map((sticker) => sticker.id)))
  }, [stickers, selectedId, sheetBackground, spriteCache])

  useEffect(() => {
    getCurrentUser()
      .then((current) => setUser(current ?? null))
      .catch(() => {
        setUser(null)
        setApiOffline(true)
      })
  }, [])

  useEffect(() => {
    if (!user) return

    listDesigns()
      .then(setDesigns)
      .catch((error) => setMessage(error.message))
  }, [user])

  // Upload several image files at once.
  async function handleUpload(event) {
    const files = Array.from(event.target.files ?? [])
    event.target.value = ''

    if (!files.length) return

    const allowedTypes = ['image/png', 'image/jpeg', 'image/webp']
    const validFiles = files.filter(
      (file) => allowedTypes.includes(file.type) && file.size <= 5 * 1024 * 1024,
    )

    if (!validFiles.length) {
      setMessage('Choose PNG, JPG or WebP images up to 5 MB each.')
      return
    }

    if (validFiles.length < files.length) {
      setMessage('Some files were skipped. Use PNG, JPG or WebP up to 5 MB each.')
    }

    let added = 0

    for (const file of validFiles) {
      try {
        const originalUrl = await fileToDataURL(file)
        const image = await loadImage(originalUrl)

        // Start stickers in a staggered arrangement.
        const id = nextId.current++
        const scale = Math.min(1, 130 / image.naturalWidth, 180 / image.naturalHeight)
        const width = image.naturalWidth * scale
        const height = image.naturalHeight * scale

        const x = 28 + ((id - 1) % 3) * 28
        const y = Math.min(35 + ((id - 1) % 8) * 58, PAGE.height - height - 18)

        setStickers((current) => [
          ...current,
          {
            id,
            kind: 'image',
            name: file.name,
            originalUrl,
            original: image,
            source: image,
            crop: { x: 0, y: 0, w: image.naturalWidth, h: image.naturalHeight },
            cutout: { enabled: false, tolerance: 40 },
            x: Math.max(0, Math.min(x, PAGE.width - width - 18)),
            y: Math.max(0, y),
            width,
            height,
            rotation: 0,
            ...defaultEffects(),
          },
        ])

        setSelectedId(id)
        added += 1
      } catch (error) {
        console.error(`Failed to upload ${file.name}:`, error)
        setMessage(`Could not load ${file.name}.`)
      }
    }

    if (added > 0 && added === validFiles.length) {
      setMessage(`${added} image(s) added to your sheet.`)
    }
  }

  async function addText() {
    const id = nextId.current++
    const text = { ...DEFAULT_TEXT }
    const source = await renderTextSource(text)
    const { w, h } = sourceSize(source)
    const width = 60 * MM
    const height = (width * h) / w
    const effects = defaultEffects()

    setStickers((current) => [
      ...current,
      {
        id,
        kind: 'text',
        name: 'Text',
        text,
        source,
        x: (PAGE.width - width) / 2,
        y: 60,
        width,
        height,
        rotation: 0,
        ...effects,
        outline: { ...effects.outline, enabled: true, width: 1.5 },
      },
    ])
    setSelectedId(id)
    setMessage('Text added. Edit it in the properties panel.')
  }

  async function updateText(changes) {
    if (!selectedSticker) return
    const { id } = selectedSticker
    const text = { ...selectedSticker.text, ...changes }
    updateSticker(id, { text })

    // Only the latest render for a sticker is applied.
    const job = (textJobs.current.get(id) ?? 0) + 1
    textJobs.current.set(id, job)

    const source = await renderTextSource(text)
    if (textJobs.current.get(id) !== job) return

    setStickers((current) =>
      current.map((sticker) =>
        sticker.id === id ? { ...sticker, ...refitText(sticker, source) } : sticker,
      ),
    )
  }

  function applyCutout(id, cutout) {
    const sticker = stickersRef.current.find((item) => item.id === id)
    if (!sticker || sticker.kind !== 'image') return

    const { w, h } = sourceSize(sticker.original)
    let source = sticker.original
    let crop = { x: 0, y: 0, w, h }

    if (cutout.enabled) {
      const result = removeBackground(sticker.original, cutout.tolerance)
      if (!result) {
        setMessage('That tolerance removes the whole image. Try a lower value.')
        return
      }
      source = result.canvas
      crop = result.crop
    }

    updateSticker(id, { cutout, ...refitCrop(sticker, source, crop) })
    setMessage(cutout.enabled ? 'Background removed.' : 'Original image restored.')
  }

  function changeTolerance(tolerance) {
    if (!selectedSticker) return
    const { id } = selectedSticker
    const cutout = { ...selectedSticker.cutout, tolerance }
    updateSticker(id, { cutout })

    clearTimeout(cutoutTimer.current)
    cutoutTimer.current = setTimeout(() => applyCutout(id, cutout), 250)
  }

  function updateEffect(group, changes) {
    if (!selectedSticker) return
    updateSticker(selectedSticker.id, {
      [group]: { ...selectedSticker[group], ...changes },
    })
  }

  function writeLocalDraft(items, sheetSettings) {
    const draft = {
      version: DRAFT_VERSION,
      savedAt: new Date().toISOString(),
      sheet: sheetSettings,
      stickers: items.map(serializeSticker),
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(draft))
  }

  async function applyDraft(draft) {
    const restored = await Promise.all((draft.stickers ?? []).map(hydrateSticker))

    setStickers(restored)
    setSelectedId(null)
    setSheet({ ...DEFAULT_SHEET, ...draft.sheet })
    nextId.current =
      Math.max(0, ...restored.map((sticker) => Number(sticker.id) || 0)) + 1
  }

  const saveDraft = () => {
    try {
      writeLocalDraft(stickers, sheet)
      setMessage('Draft saved on this device!')
    } catch (error) {
      console.error(error)
      setMessage('Could not save draft. Try fewer or smaller images.')
    }
  }

  const resumeDraft = async () => {
    try {
      const saved = localStorage.getItem(DRAFT_KEY)

      if (!saved) {
        setMessage('No saved draft found.')
        return
      }

      await applyDraft(JSON.parse(saved))
      setCurrentDesign(null)
      setMessage('Draft restored!')
    } catch (error) {
      console.error(error)
      setMessage('Could not restore draft.')
    }
  }

  const resetSheet = () => {
    if (!window.confirm('Clear this sheet? Your saved draft will remain.')) return

    setStickers([])
    setSelectedId(null)
    setCurrentDesign(null)
    setMessage('Sheet cleared.')
  }

  function getCanvasPoint(event) {
    const canvas = canvasRef.current
    const rect = canvas.getBoundingClientRect()

    return {
      x: ((event.clientX - rect.left) / rect.width) * PAGE.width,
      y: ((event.clientY - rect.top) / rect.height) * PAGE.height,
    }
  }

  function handlePointerDown(event) {
    const point = getCanvasPoint(event)
    const items = stickersRef.current

    // Check from topmost to bottommost sticker, including outline/backdrop.
    const hit = [...items].reverse().find((sticker) => {
      const extent = stickerExtent(sticker)
      const cx = sticker.x + sticker.width / 2
      const cy = sticker.y + sticker.height / 2
      const angle = (-sticker.rotation * Math.PI) / 180
      const dx = point.x - cx
      const dy = point.y - cy
      const localX = dx * Math.cos(angle) - dy * Math.sin(angle)
      const localY = dx * Math.sin(angle) + dy * Math.cos(angle)

      return (
        Math.abs(localX) <= sticker.width / 2 + extent.x &&
        Math.abs(localY) <= sticker.height / 2 + extent.y
      )
    })

    if (!hit) {
      setSelectedId(null)
      return
    }

    setSelectedId(hit.id)
    dragRef.current = {
      id: hit.id,
      startX: point.x,
      startY: point.y,
      originalX: hit.x,
      originalY: hit.y,
    }

    event.currentTarget.setPointerCapture(event.pointerId)
  }

  function handlePointerMove(event) {
    if (!dragRef.current) return

    const point = getCanvasPoint(event)
    const drag = dragRef.current
    const sticker = stickersRef.current.find((item) => item.id === drag.id)

    if (!sticker) return

    const x = drag.originalX + point.x - drag.startX
    const y = drag.originalY + point.y - drag.startY

    updateSticker(sticker.id, {
      x: clamp(x, 0, PAGE.width - sticker.width),
      y: clamp(y, 0, PAGE.height - sticker.height),
    })
  }

  function handlePointerUp() {
    dragRef.current = null
  }

  function setSizeMm(dimension, mm) {
    const sticker = selectedSticker
    if (!sticker) return

    let width = sticker.width
    let height = sticker.height

    if (dimension === 'width') {
      width = mm * MM
      if (lockRatio) height = (width * sticker.height) / sticker.width
    } else {
      height = mm * MM
      if (lockRatio) width = (height * sticker.width) / sticker.height
    }

    // Never let a sticker grow beyond the page.
    const fit = Math.min(1, PAGE.width / width, PAGE.height / height)
    width *= fit
    height *= fit

    // Resize around the centre so the sticker stays where it was placed.
    const cx = sticker.x + sticker.width / 2
    const cy = sticker.y + sticker.height / 2

    updateSticker(sticker.id, {
      width,
      height,
      x: clamp(cx - width / 2, 0, PAGE.width - width),
      y: clamp(cy - height / 2, 0, PAGE.height - height),
    })
  }

  function setPositionMm(axis, mm) {
    const sticker = selectedSticker
    if (!sticker) return

    if (axis === 'x') {
      updateSticker(sticker.id, { x: clamp(mm * MM, 0, PAGE.width - sticker.width) })
    } else {
      updateSticker(sticker.id, { y: clamp(mm * MM, 0, PAGE.height - sticker.height) })
    }
  }

  function rotateSticker(rotation) {
    if (!selectedSticker) return
    updateSticker(selectedSticker.id, { rotation: clamp(Number(rotation), -180, 180) })
  }

  function deleteSelected() {
    if (!selectedSticker) return

    setStickers((current) =>
      current.filter((sticker) => sticker.id !== selectedSticker.id),
    )
    setSelectedId(null)
    setMessage('Sticker removed.')
  }

  function duplicateSelected() {
    const sticker = selectedSticker
    if (!sticker) return

    const id = nextId.current++
    const copy = {
      ...sticker,
      id,
      name: `${sticker.name} copy`,
      x: clamp(sticker.x + 12, 0, PAGE.width - sticker.width),
      y: clamp(sticker.y + 12, 0, PAGE.height - sticker.height),
    }

    setStickers((current) => {
      const index = current.findIndex((item) => item.id === sticker.id)
      const next = [...current]
      next.splice(index + 1, 0, copy)
      return next
    })
    setSelectedId(id)
    setMessage('Sticker duplicated.')
  }

  // Stickers later in the array are drawn on top.
  function moveLayer(direction) {
    if (!selectedSticker) return

    setStickers((current) => {
      const index = current.findIndex((item) => item.id === selectedSticker.id)
      const target = {
        forward: Math.min(current.length - 1, index + 1),
        backward: Math.max(0, index - 1),
        front: current.length - 1,
        back: 0,
      }[direction]

      if (target === index) return current
      const next = [...current]
      const [item] = next.splice(index, 1)
      next.splice(target, 0, item)
      return next
    })
  }

  function renderSheet(width, height, background) {
    const canvas = createCanvas(width, height)
    drawPage(canvas, stickers, { background })
    return canvas
  }

  async function runTask(task, failure) {
    setBusy(true)
    try {
      await task()
    } catch (error) {
      console.error(error)
      setMessage(error.message ? `${failure} ${error.message}` : failure)
    } finally {
      setBusy(false)
    }
  }

  function exportPdf() {
    return runTask(async () => {
      // JPEG has no transparency, so a transparent sheet prints on white.
      const canvas = renderSheet(PAGE.exportWidth, PAGE.exportHeight, sheet.color)
      const blob = await pdfFromCanvas(canvas, PAGE.widthMm, PAGE.heightMm)
      downloadBlob(blob, 'stickernest-a5-sheet.pdf')
      setMessage('A5 PDF exported at 148 × 210 mm. Print at Actual size / 100%.')
    }, 'PDF export failed.')
  }

  function exportPng() {
    return runTask(async () => {
      const canvas = renderSheet(PAGE.exportWidth, PAGE.exportHeight, sheetBackground)
      downloadBlob(await pngWithDpi(canvas, 300), 'stickernest-a5-sheet.png')
      setMessage('A5 PNG exported at 300 DPI.')
    }, 'PNG export failed.')
  }

  function downloadSelected() {
    const sticker = selectedSticker
    if (!sticker) return

    return runTask(async () => {
      const blob = await pngWithDpi(renderStickerImage(sticker, EXPORT_SCALE), 300)
      downloadBlob(blob, `${slugify(sticker.name)}.png`)
      setMessage(`${sticker.name} downloaded as a 300 DPI PNG.`)
    }, 'Sticker download failed.')
  }

  function saveToAccount() {
    return runTask(async () => {
      // Upload embedded images once, then store only their URLs in MySQL.
      const uploaded = new Map()
      const items = []

      for (const sticker of stickers) {
        const data = serializeSticker(sticker)
        if (data.kind === 'image' && data.originalUrl.startsWith('data:')) {
          if (!uploaded.has(data.originalUrl)) {
            const blob = await (await fetch(data.originalUrl)).blob()
            uploaded.set(data.originalUrl, await uploadAsset(blob, data.name))
          }
          data.originalUrl = uploaded.get(data.originalUrl)
        }
        items.push(data)
      }

      if (uploaded.size) {
        setStickers((current) =>
          current.map((sticker) =>
            uploaded.has(sticker.originalUrl)
              ? { ...sticker, originalUrl: uploaded.get(sticker.originalUrl) }
              : sticker,
          ),
        )
      }

      const thumbnail = await canvasToBlob(
        renderSheet(PAGE.width / 2, PAGE.height / 2, sheet.color),
        'image/jpeg',
        0.8,
      )

      const design = await saveDesign({
        id: currentDesign?.id,
        title: designTitle.trim() || 'Untitled sheet',
        data: { version: DRAFT_VERSION, sheet, stickers: items },
        thumbnail,
      })

      setCurrentDesign({ id: design.id, title: design.title })
      setDesigns(await listDesigns())
      setMessage(`"${design.title}" saved to your account.`)
    }, 'Could not save to your account.')
  }

  function openDesign(id) {
    return runTask(async () => {
      const design = await getDesign(id)
      await applyDraft(design.data)
      setCurrentDesign({ id: design.id, title: design.title })
      setDesignTitle(design.title)
      setMessage(`"${design.title}" opened.`)
    }, 'Could not open that design.')
  }

  function removeDesign(design) {
    if (!window.confirm(`Delete "${design.title}" from your account?`)) return

    return runTask(async () => {
      await deleteDesign(design.id)
      if (currentDesign?.id === design.id) setCurrentDesign(null)
      setDesigns((current) => current.filter((item) => item.id !== design.id))
      setMessage(`"${design.title}" deleted.`)
    }, 'Could not delete that design.')
  }

  // Hand the rendered sticker to the Flask Create Sticker form, where the
  // artist sets its name, price and category.
  function sellSelected() {
    const sticker = selectedSticker
    if (!sticker) return

    return runTask(async () => {
      try {
        writeLocalDraft(stickers, sheet)
      } catch (error) {
        console.error('Could not save draft before leaving:', error)
      }

      const image = await pngWithDpi(renderStickerImage(sticker, EXPORT_SCALE), 300)
      const url = await uploadAsset(image, 'sticker.png')
      const name =
        sticker.kind === 'text'
          ? sticker.text.content.split('\n')[0]
          : sticker.name.replace(/\.[a-z0-9]+$/i, '')

      const params = new URLSearchParams({
        studio_asset: url.replace(/^\/static\/uploads\//, ''),
        name: name.trim().slice(0, 100),
      })
      window.location.href = `${FLASK_URL}/create-sticker?${params}`
    }, 'Could not send this sticker to Create Sticker.')
  }

  // Autosave the draft to localStorage one second after the last change.
  useEffect(() => {
    if (stickers.length === 0) return

    const timer = setTimeout(() => {
      try {
        writeLocalDraft(stickers, sheet)
      } catch (error) {
        console.error('StickerNest auto-save failed:', error)
      }
    }, 1000)

    return () => clearTimeout(timer)
  }, [stickers, sheet])

  // Keyboard shortcuts for the selected sticker.
  useEffect(() => {
    function handleKey(event) {
      if (!selectedSticker) return
      if (event.target.closest?.('input, textarea, select')) return

      const step = event.shiftKey ? 10 : 1
      const nudges = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      }

      if (nudges[event.key]) {
        event.preventDefault()
        const [dx, dy] = nudges[event.key]
        updateSticker(selectedSticker.id, {
          x: clamp(selectedSticker.x + dx, 0, PAGE.width - selectedSticker.width),
          y: clamp(selectedSticker.y + dy, 0, PAGE.height - selectedSticker.height),
        })
      } else if (event.key === 'Delete' || event.key === 'Backspace') {
        event.preventDefault()
        deleteSelected()
      } else if (event.key.toLowerCase() === 'd' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault()
        duplicateSelected()
      }
    }

    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  })

  const sticker = selectedSticker

  return (
    <div className="studio-app">
      <header className="topbar">
        <a className="brand" href={`${FLASK_URL}/`}>
          <span className="brand-mark">✿</span>
          StickerNest
        </a>
        <div className="topbar-label">PRINT STUDIO</div>
        <button
          className="primary-button"
          onClick={exportPdf}
          disabled={!stickers.length || busy}
        >
          ↓ Export print PDF
        </button>
      </header>

      <div className="studio-layout">
        <aside className="sidebar">
          <p className="sidebar-label">WORKSPACE</p>
          <button className="nav-item active">▦ &nbsp; A5 Sheet</button>
          <button className="nav-item" onClick={() => fileInputRef.current?.click()}>
            ↑ &nbsp; Add stickers
          </button>
          <button className="nav-item" onClick={addText}>
            T &nbsp; Add text
          </button>
          <button className="nav-item" onClick={duplicateSelected} disabled={!sticker}>
            ⧉ &nbsp; Duplicate
          </button>
          <button className="nav-item" onClick={deleteSelected} disabled={!sticker}>
            × &nbsp; Delete selected
          </button>
          <div className="sidebar-note">
            <span>✿</span>
            <p>Small stickers,<br />big joy.</p>
            <small>Made with care in Nepal.</small>
          </div>
        </aside>

        <main className="studio-main">
          <div className="page-heading">
            <div>
              <p className="eyebrow">YOUR CREATIVE SPACE</p>
              <h1>Sticker Sheet Designer</h1>
              <p className="subtitle">
                Add, arrange and size each sticker for printing.
              </p>
            </div>
            <span className="status-pill">A5 · PORTRAIT</span>
          </div>

          <div className="print-workspace">
            <section className="panel sheet-panel">
              <div className="panel-heading">
                <div>
                  <h2>Your A5 sheet</h2>
                  <p>
                    Click a sticker to select it. Drag or use arrow keys to move it.
                    Ctrl+D duplicates, Delete removes.
                  </p>
                </div>
                <span className="live-label">LIVE</span>
              </div>

              <div className="sheet-stage">
                <div className={`a5-paper ${sheet.transparent ? 'transparent' : ''}`}>
                  <canvas
                    ref={canvasRef}
                    width={PAGE.width * PREVIEW_SCALE}
                    height={PAGE.height * PREVIEW_SCALE}
                    onPointerDown={handlePointerDown}
                    onPointerMove={handlePointerMove}
                    onPointerUp={handlePointerUp}
                    onPointerCancel={handlePointerUp}
                    aria-label="A5 sticker sheet editor"
                  />
                </div>
              </div>

              <p className="canvas-caption">
                A5 portrait · 148 × 210 mm · Print at 100% scale
              </p>

              <input
                ref={fileInputRef}
                className="hidden-input"
                type="file"
                accept="image/png,image/jpeg,image/webp"
                multiple
                onChange={handleUpload}
              />

              <div className="preview-actions">
                <button
                  className="secondary-button"
                  onClick={() => fileInputRef.current?.click()}
                >
                  + Add images
                </button>
                <button className="secondary-button" onClick={addText}>
                  T Add text
                </button>
                <button
                  className="primary-button"
                  onClick={exportPdf}
                  disabled={!stickers.length || busy}
                >
                  ↓ Print PDF
                </button>
                <button
                  className="secondary-button"
                  onClick={exportPng}
                  disabled={!stickers.length || busy}
                >
                  ↓ PNG (300 DPI)
                </button>
              </div>

              <p className="feedback-message" role="status">
                {busy ? 'Working…' : message}
              </p>
            </section>

            <aside className="panel controls-panel">
              <div className="panel-heading">
                <div>
                  <h2>Sticker properties</h2>
                  <p>Adjust the selected sticker.</p>
                </div>
              </div>

              {sticker ? (
                // Keyed so field drafts reset when a different sticker is selected.
                <Fragment key={sticker.id}>
                  <section className="control-section">
                    <h3>01 / Selected sticker</h3>
                    <p className="selected-name">
                      {sticker.name} · layer {selectedIndex + 1} of {stickers.length}
                    </p>

                    <div className="tool-grid">
                      <button className="secondary-button" onClick={duplicateSelected}>
                        Duplicate
                      </button>
                      <button
                        className="secondary-button"
                        onClick={downloadSelected}
                        disabled={busy}
                      >
                        Download PNG
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => moveLayer('forward')}
                        disabled={selectedIndex === stickers.length - 1}
                      >
                        Forward
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => moveLayer('backward')}
                        disabled={selectedIndex === 0}
                      >
                        Backward
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => moveLayer('front')}
                        disabled={selectedIndex === stickers.length - 1}
                      >
                        To front
                      </button>
                      <button
                        className="secondary-button"
                        onClick={() => moveLayer('back')}
                        disabled={selectedIndex === 0}
                      >
                        To back
                      </button>
                    </div>

                    <button className="secondary-button full-button" onClick={deleteSelected}>
                      Remove selected sticker
                    </button>
                  </section>

                  <section className="control-section">
                    <h3>02 / Size & position</h3>

                    <div className="number-grid">
                      <NumberField
                        label="Width"
                        value={sticker.width / MM}
                        min={3}
                        max={PAGE.widthMm}
                        suffix="mm"
                        onCommit={(mm) => setSizeMm('width', mm)}
                      />
                      <NumberField
                        label="Height"
                        value={sticker.height / MM}
                        min={3}
                        max={PAGE.heightMm}
                        suffix="mm"
                        onCommit={(mm) => setSizeMm('height', mm)}
                      />
                      <NumberField
                        label="X"
                        value={sticker.x / MM}
                        min={0}
                        max={PAGE.widthMm}
                        suffix="mm"
                        onCommit={(mm) => setPositionMm('x', mm)}
                      />
                      <NumberField
                        label="Y"
                        value={sticker.y / MM}
                        min={0}
                        max={PAGE.heightMm}
                        suffix="mm"
                        onCommit={(mm) => setPositionMm('y', mm)}
                      />
                    </div>

                    <Toggle label="Lock aspect ratio" checked={lockRatio} onChange={setLockRatio} />

                    <RangeField
                      label="Width"
                      display={`${round1(sticker.width / MM)} mm`}
                      min={5}
                      max={PAGE.widthMm}
                      step={0.5}
                      value={clamp(round1(sticker.width / MM), 5, PAGE.widthMm)}
                      onChange={(mm) => setSizeMm('width', mm)}
                    />

                    <RangeField
                      label="Rotation"
                      display={`${sticker.rotation}°`}
                      min={-180}
                      max={180}
                      step={1}
                      value={sticker.rotation}
                      onChange={rotateSticker}
                    />
                  </section>

                  {sticker.kind === 'text' ? (
                    <section className="control-section">
                      <h3>03 / Text</h3>
                      <textarea
                        className="text-input"
                        rows={3}
                        value={sticker.text.content}
                        onChange={(event) => updateText({ content: event.target.value })}
                        aria-label="Sticker text"
                      />

                      <label className="field-label" htmlFor="text-font">Font</label>
                      <select
                        id="text-font"
                        className="text-input"
                        value={sticker.text.font}
                        onChange={(event) => updateText({ font: event.target.value })}
                      >
                        {TEXT_FONTS.map((font) => (
                          <option key={font} value={font}>{font}</option>
                        ))}
                      </select>

                      <ColorField
                        label="Colour"
                        value={sticker.text.color}
                        onChange={(color) => updateText({ color })}
                      />

                      <div className="segmented">
                        {['left', 'center', 'right'].map((align) => (
                          <button
                            key={align}
                            className={sticker.text.align === align ? 'selected' : ''}
                            onClick={() => updateText({ align })}
                          >
                            {align}
                          </button>
                        ))}
                      </div>

                      <div className="check-pair">
                        <Toggle
                          label="Bold"
                          checked={sticker.text.bold}
                          onChange={(bold) => updateText({ bold })}
                        />
                        <Toggle
                          label="Italic"
                          checked={sticker.text.italic}
                          onChange={(italic) => updateText({ italic })}
                        />
                      </div>
                    </section>
                  ) : (
                    <section className="control-section">
                      <h3>03 / Cut-out</h3>
                      <Toggle
                        label="Remove background"
                        checked={sticker.cutout.enabled}
                        onChange={(enabled) =>
                          applyCutout(sticker.id, { ...sticker.cutout, enabled })
                        }
                      />
                      {sticker.cutout.enabled && (
                        <RangeField
                          label="Tolerance"
                          display={sticker.cutout.tolerance}
                          min={5}
                          max={150}
                          step={1}
                          value={sticker.cutout.tolerance}
                          onChange={changeTolerance}
                        />
                      )}
                      <p className="small-note">
                        Works best on artwork with a plain, even background. Edges
                        are trimmed so outlines follow the shape.
                      </p>
                    </section>
                  )}

                  <section className="control-section">
                    <h3>04 / Outline</h3>
                    <Toggle
                      label="Die-cut outline"
                      checked={sticker.outline.enabled}
                      onChange={(enabled) => updateEffect('outline', { enabled })}
                    />
                    {sticker.outline.enabled && (
                      <>
                        <RangeField
                          label="Thickness"
                          display={`${sticker.outline.width} mm`}
                          min={0.5}
                          max={8}
                          step={0.5}
                          value={sticker.outline.width}
                          onChange={(width) => updateEffect('outline', { width })}
                        />
                        <ColorField
                          label="Colour"
                          value={sticker.outline.color}
                          onChange={(color) => updateEffect('outline', { color })}
                        />
                      </>
                    )}
                  </section>

                  <section className="control-section">
                    <h3>05 / Shadow</h3>
                    <Toggle
                      label="Drop shadow"
                      checked={sticker.shadow.enabled}
                      onChange={(enabled) => updateEffect('shadow', { enabled })}
                    />
                    {sticker.shadow.enabled && (
                      <>
                        <RangeField
                          label="Blur"
                          display={`${sticker.shadow.blur} mm`}
                          min={0}
                          max={8}
                          step={0.25}
                          value={sticker.shadow.blur}
                          onChange={(blur) => updateEffect('shadow', { blur })}
                        />
                        <RangeField
                          label="Offset X"
                          display={`${sticker.shadow.offsetX} mm`}
                          min={-5}
                          max={5}
                          step={0.1}
                          value={sticker.shadow.offsetX}
                          onChange={(offsetX) => updateEffect('shadow', { offsetX })}
                        />
                        <RangeField
                          label="Offset Y"
                          display={`${sticker.shadow.offsetY} mm`}
                          min={-5}
                          max={5}
                          step={0.1}
                          value={sticker.shadow.offsetY}
                          onChange={(offsetY) => updateEffect('shadow', { offsetY })}
                        />
                        <RangeField
                          label="Opacity"
                          display={`${Math.round(sticker.shadow.opacity * 100)}%`}
                          min={0.05}
                          max={1}
                          step={0.05}
                          value={sticker.shadow.opacity}
                          onChange={(opacity) => updateEffect('shadow', { opacity })}
                        />
                        <ColorField
                          label="Colour"
                          value={sticker.shadow.color}
                          onChange={(color) => updateEffect('shadow', { color })}
                        />
                      </>
                    )}
                  </section>

                  <section className="control-section">
                    <h3>06 / Background</h3>
                    <div className="segmented">
                      {['none', 'rect', 'rounded', 'circle'].map((shape) => (
                        <button
                          key={shape}
                          className={sticker.backdrop.shape === shape ? 'selected' : ''}
                          onClick={() => updateEffect('backdrop', { shape })}
                        >
                          {shape}
                        </button>
                      ))}
                    </div>
                    {sticker.backdrop.shape !== 'none' && (
                      <>
                        <RangeField
                          label="Padding"
                          display={`${sticker.backdrop.padding} mm`}
                          min={0}
                          max={15}
                          step={0.5}
                          value={sticker.backdrop.padding}
                          onChange={(padding) => updateEffect('backdrop', { padding })}
                        />
                        <ColorField
                          label="Colour"
                          value={sticker.backdrop.color}
                          onChange={(color) => updateEffect('backdrop', { color })}
                        />
                      </>
                    )}
                  </section>

                  {user?.role === 'artist' && (
                    <section className="control-section">
                      <h3>07 / Sell in the shop</h3>
                      <p className="small-note">
                        Send this sticker to Create Sticker to set its name, price
                        and category. Your sheet is saved as a draft first.
                      </p>
                      <button
                        className="primary-button full-button"
                        onClick={sellSelected}
                        disabled={busy}
                      >
                        Sell this sticker
                      </button>
                      <p className="small-note">
                        Already have a finished image?{' '}
                        <a href={`${FLASK_URL}/create-sticker`}>Upload it directly</a>
                      </p>
                    </section>
                  )}
                </Fragment>
              ) : (
                <div className="empty-selection">
                  <span>✳</span>
                  <h3>No sticker selected</h3>
                  <p>
                    Add an image or text, then click it on the sheet to edit its
                    size, cut-out, outline and more.
                  </p>
                  <button
                    className="primary-button full-button"
                    onClick={() => fileInputRef.current?.click()}
                  >
                    + Add stickers
                  </button>
                </div>
              )}

              <section className="control-section">
                <h3>Sheet</h3>

                <ColorField
                  label="Sheet background"
                  value={sheet.color}
                  onChange={(color) => setSheet({ ...sheet, color })}
                />
                <Toggle
                  label="Transparent background (PNG only)"
                  checked={sheet.transparent}
                  onChange={(transparent) => setSheet({ ...sheet, transparent })}
                />

                <div className="info-row">
                  <span>Paper size</span>
                  <strong>A5 · Portrait · 148 × 210 mm</strong>
                </div>
                <div className="info-row">
                  <span>Export resolution</span>
                  <strong>{PAGE.exportWidth} × {PAGE.exportHeight} px · 300 DPI</strong>
                </div>

                <button type="button" className="secondary-button full-button" onClick={saveDraft}>
                  Save draft
                </button>
                <button type="button" className="secondary-button full-button" onClick={resumeDraft}>
                  Resume draft
                </button>
                <button type="button" className="secondary-button full-button" onClick={resetSheet}>
                  Reset sheet
                </button>

                <p className="small-note">
                  Leave space between stickers for cutting. The dashed inner
                  border is a preview guide and is not exported.
                </p>
              </section>

              <section className="control-section">
                <h3>Your account</h3>
                {user === undefined && <p className="small-note">Checking your account…</p>}

                {user === null && (
                  <p className="small-note">
                    {apiOffline
                      ? 'The StickerNest server is not reachable, so designs can only be saved on this device.'
                      : 'Log in to save sheets to your StickerNest account and open them on any device.'}{' '}
                    {!apiOffline && <a href={`${FLASK_URL}/login`}>Log in</a>}
                  </p>
                )}

                {user && (
                  <>
                    <p className="small-note">
                      Signed in as <strong>{user.name}</strong>
                      {currentDesign && <> · editing “{currentDesign.title}”</>}
                    </p>
                    <input
                      className="text-input"
                      value={designTitle}
                      maxLength={120}
                      onChange={(event) => setDesignTitle(event.target.value)}
                      aria-label="Design title"
                    />
                    <button
                      className="primary-button full-button"
                      onClick={saveToAccount}
                      disabled={busy || !stickers.length}
                    >
                      {currentDesign ? 'Update saved design' : 'Save to account'}
                    </button>
                    {currentDesign && (
                      <button
                        className="secondary-button full-button"
                        onClick={() => setCurrentDesign(null)}
                      >
                        Save as a new design instead
                      </button>
                    )}

                    {designs.length > 0 && (
                      <ul className="design-list">
                        {designs.map((design) => (
                          <li key={design.id}>
                            {design.thumbnail_url ? (
                              <img src={design.thumbnail_url} alt="" />
                            ) : (
                              <span className="design-thumb" />
                            )}
                            <div>
                              <strong>{design.title}</strong>
                              <small>{new Date(design.updated_at).toLocaleString()}</small>
                            </div>
                            <button
                              className="secondary-button"
                              onClick={() => openDesign(design.id)}
                              disabled={busy}
                            >
                              Open
                            </button>
                            <button
                              className="secondary-button"
                              onClick={() => removeDesign(design)}
                              disabled={busy}
                              aria-label={`Delete ${design.title}`}
                            >
                              ×
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                )}
              </section>

              <section className="control-section">
                <h3>Print reminder</h3>
                <p className="small-note">
                  Print the PDF on A5 paper at Actual size / 100%. Printer margins
                  can vary, so test a sheet before printing a full batch.
                </p>
              </section>
            </aside>
          </div>

          <footer className="studio-footer">
            <span>StickerNest</span>
            <span>Design it. Arrange it. Print it. ♡</span>
          </footer>
        </main>
      </div>
    </div>
  )
}

export default App
