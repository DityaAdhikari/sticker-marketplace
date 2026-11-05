// Display formatting for Nepali rupees. Mirrors currency.py on the Flask
// side so both apps show amounts the same way. Display only: never use the
// result in price or payment calculations.
//
//   formatRupees(100)      -> 'Rs. 100'
//   formatRupees(1249.5)   -> 'Rs. 1,249.50'
//   formatRupees(1250000)  -> 'Rs. 12,50,000'  (Nepali lakh grouping)

// The last three digits, then pairs (12,50,000)
function groupDigits(digits) {
  if (digits.length <= 3) return digits

  let head = digits.slice(0, -3)
  const groups = [digits.slice(-3)]
  while (head.length > 2) {
    groups.unshift(head.slice(-2))
    head = head.slice(0, -2)
  }
  groups.unshift(head)
  return groups.join(',')
}

export function formatPaisa(paisa) {
  if (paisa === null || paisa === undefined || Number.isNaN(Number(paisa))) return ''

  const whole = Math.round(Number(paisa))
  const sign = whole < 0 ? '-' : ''
  const rupees = Math.floor(Math.abs(whole) / 100)
  const cents = Math.abs(whole) % 100

  let text = groupDigits(String(rupees))
  if (cents) text += `.${String(cents).padStart(2, '0')}`
  return `Rs. ${sign}${text}`
}

export function formatRupees(amount) {
  if (amount === null || amount === undefined || Number.isNaN(Number(amount))) return ''

  // toFixed avoids float drift such as 1249.5 * 100 = 124949.99999
  return formatPaisa(Number(Number(amount).toFixed(2).replace('.', '')))
}
