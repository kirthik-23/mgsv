// MindGuard conversational voice: prefer a natural male English voice when installed.
// Browser speech quality depends on the voices available on the visitor's device.
export function canSpeak() {
  return typeof window !== 'undefined' &&
    'speechSynthesis' in window &&
    'SpeechSynthesisUtterance' in window
}

function chooseMindGuardVoice(voices = []) {
  if (!voices.length) return null

  const english = voices.filter((v) => /^en([_-]|$)/i.test(v.lang || ''))
  const pool = english.length ? english : voices

  const score = (voice) => {
    const name = (voice.name || '').toLowerCase()
    const lang = (voice.lang || '').toLowerCase()
    let points = 0

    // Explicit male labels and commonly male voice names receive priority.
    if (/\b(male|man)\b/.test(name)) points += 120
    if (/\b(david|guy|mark|george|ryan|james|daniel|thomas|alex|fred|aaron|oliver|arthur|ravi|prabhat|matthew|andrew|christopher|liam|jack)\b/.test(name)) points += 45
    if (/\b(female|woman|zira|samantha|victoria|karen|susan|hazel|aria|jenny|sonia|natasha|heera|veena)\b/.test(name)) points -= 100

    if (/en-in/.test(lang)) points += 16
    else if (/en-gb/.test(lang)) points += 12
    else if (/en-us/.test(lang)) points += 10
    if (/natural|online|neural/.test(name)) points += 12
    if (voice.default) points += 2
    return points
  }

  return [...pool].sort((a, b) => score(b) - score(a))[0] || null
}

function cleanSpeechText(text) {
  return String(text)
    .replace(/```[\s\S]*?```/g, ' Code example omitted. ')
    .replace(/https?:\/\/\S+/g, ' link ')
    .replace(/\$\$([\s\S]*?)\$\$/g, '$1')
    .replace(/\$([^$]+)\$/g, '$1')
    .replace(/[|*_#`~]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function loadVoices(synthesis) {
  const available = synthesis.getVoices()
  if (available.length) return Promise.resolve(available)

  // Some browsers populate voices asynchronously after the page loads.
  return new Promise((resolve) => {
    let finished = false
    const done = () => {
      if (finished) return
      finished = true
      synthesis.removeEventListener?.('voiceschanged', onChanged)
      resolve(synthesis.getVoices())
    }
    const onChanged = () => done()
    synthesis.addEventListener?.('voiceschanged', onChanged)
    window.setTimeout(done, 900)
  })
}

export async function speakMindGuard(text) {
  if (!canSpeak() || !text) return false

  try {
    const synthesis = window.speechSynthesis
    synthesis.cancel()

    const clean = cleanSpeechText(text).slice(0, 4500)
    if (!clean) return false

    const voices = await loadVoices(synthesis)
    const voice = chooseMindGuardVoice(voices)

    // Sentence-sized utterances make longer replies sound less like one flat monologue.
    const sentences = clean.match(/[^.!?]+[.!?]+|[^.!?]+$/g) || [clean]
    const chunks = []
    let current = ''

    for (const sentence of sentences) {
      const part = sentence.trim()
      if (!part) continue
      if ((current + ' ' + part).trim().length > 230 && current) {
        chunks.push(current.trim())
        current = part
      } else {
        current = `${current} ${part}`.trim()
      }
    }
    if (current) chunks.push(current.trim())

    chunks.forEach((chunk) => {
      const utterance = new SpeechSynthesisUtterance(chunk)
      utterance.lang = voice?.lang || 'en-IN'
      utterance.rate = 1.02
      utterance.pitch = 0.88
      utterance.volume = 1
      if (voice) utterance.voice = voice
      synthesis.speak(utterance)
    })

    return true
  } catch (error) {
    console.warn('MindGuard voice unavailable; text chat remains active.', error)
    return false
  }
}

export function stopMindGuardSpeech() {
  if (canSpeak()) window.speechSynthesis.cancel()
}
