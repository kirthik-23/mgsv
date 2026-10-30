"""General-purpose MindGuard chat.

This module is deliberately separate from the wellness interview engine.
The interview's duplicate-question protections, state machine and assessment
flow are not touched by normal AI chat.
"""

import re
from .llm_connector import ask_general_llm

GENERAL_SYSTEM_PROMPT = """
You are MindGuard AI, a warm, highly capable AI assistant for students.
You use the friendly conversational intelligence of Guardian AI while living
inside the MindGuard app.

GENERAL CHAT MODE:
- This is a normal AI assistant, NOT a wellness assessment.
- Do not turn ordinary requests into wellness questions.
- Do not repeatedly ask the user the same question.
- Answer directly and helpfully.
- Be warm, friendly, natural and encouraging, like a smart helpful friend.
  Use a polished, witty, JARVIS-inspired assistant personality: composed,
  observant, lightly humorous and conversational, but never pretend to be
  a fictional character or claim capabilities you do not have.
- Answer the exact question in the first sentence or two. Never send the
  generic welcome message as a reply to a specific question.
- For greetings, greet naturally and ask what the person would like to do.
- Use gentle, harmless humour when welcomed; never mock distress, identity,
  appearance, or a person's vulnerabilities. In emotional conversations,
  lead with empathy before advice.
- If asked how MindGuard differs from ChatGPT, explain accurately that
  ChatGPT is general-purpose while MindGuard combines general AI chat with
  student-focused study/planning tools and a separate wellness check-in.
  Do not claim MindGuard is more intelligent or a replacement for people.
- Give practical, actionable answers rather than generic advice.
- You can help with studying, homework explanations, revision plans,
  timetables, productivity, writing, brainstorming, planning and everyday
  questions.
- When asked to create a timetable or study plan, actually create one.
  It MUST cover the full duration/time window the user requested. Never give
  a shorter plan. Include clear times, tasks, breaks and a realistic workload.
- If the user gives a start/end time, the timetable MUST end at or after the
  requested end time. If the user gives a duration, the study blocks must
  cover that duration (breaks may extend the clock window).
- If something is ambiguous but a useful answer can still be given, make a
  reasonable assumption and state it briefly instead of interrogating the user.
- Never claim to have completed an external action you cannot perform.
- Never diagnose medical or mental-health conditions.
- For urgent safety situations, encourage the user to seek immediate help
  from a trusted person or local emergency service.
- Keep normal answers reasonably detailed: short for simple questions and
  structured/detailed for plans, timetables and study help.
"""


def _minutes(h, m, ampm=None):
    h = int(h)
    m = int(m)
    if ampm:
        a = ampm.lower()
        if a == "pm" and h < 12:
            h += 12
        if a == "am" and h == 12:
            h = 0
    return h * 60 + m


def _parse_clock(value):
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*", value, re.I)
    if not m:
        return None
    return _minutes(m.group(1), m.group(2) or "00", m.group(3))


def _requested_window(text):
    """Return explicit start/end minutes when the user gives a clock window."""
    patterns = [
        r"\bfrom\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s+(?:to|until|till|-)\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm))\s*(?:-|to|until|till)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm))",
    ]
    for pattern in patterns:
        m = re.search(pattern, text, re.I)
        if m:
            start = _parse_clock(m.group(1))
            end = _parse_clock(m.group(2))
            if start is not None and end is not None:
                if end <= start:
                    end += 24 * 60
                return start, end
    return None


def _requested_hours(text):
    m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:-?hour|hours|hr|hrs)\b", text, re.I)
    if m:
        return float(m.group(1))
    return None


def _is_timetable_request(text):
    lower = text.lower()
    return any(k in lower for k in ("timetable", "time table", "study plan", "study schedule", "schedule for studying"))


def _response_times(reply):
    """Extract clock ranges such as 18:00–18:45 from an AI response."""
    ranges = []
    pattern = re.compile(
        r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*[–—-]\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)",
        re.I,
    )
    for m in pattern.finditer(reply or ""):
        start = _parse_clock(m.group(1))
        end = _parse_clock(m.group(2))
        if start is None or end is None:
            continue
        if end <= start:
            end += 24 * 60
        ranges.append((start, end))
    return ranges


def _fallback_timetable(message):
    """Create a deterministic timetable that always covers the requested window."""
    window = _requested_window(message)
    hours = _requested_hours(message)

    if window:
        start, end = window
    else:
        start = 18 * 60
        duration = int(round((hours or 3) * 60))
        # Use the requested duration as elapsed study time. Short breaks are
        # inserted between blocks, so the final clock time may be later.
        end = start + duration

    total = max(60, end - start)
    # Four sensible blocks for a 3-hour window; adapt to shorter/longer windows.
    break_len = 10
    min_block = 25
    blocks = max(1, min(6, round(total / 45)))
    if total < 90:
        blocks = 2
    elif total < 150:
        blocks = 3
    elif total < 240:
        blocks = 4
    else:
        blocks = 5

    usable = total - break_len * (blocks - 1)
    block_len = max(min_block, usable // blocks)
    # Make sure the final segment reaches the requested end.
    tasks = [
        "Core concepts / weakest topic",
        "Practice questions and examples",
        "Past-paper / exam-style questions",
        "Active recall + revision",
        "Difficult problems + mistakes",
        "Quick final recap",
    ]

    lines = ["Absolutely bro 💪 Here’s a realistic study timetable that covers the full time you gave me:"]
    cursor = start
    for i in range(blocks):
        remaining = end - cursor
        this_block = remaining if i == blocks - 1 else min(block_len, remaining - break_len * (blocks - i - 1))
        if this_block < min_block and i > 0:
            this_block = remaining
        block_end = cursor + this_block
        sh, sm = divmod(cursor % (24 * 60), 60)
        eh, em = divmod(block_end % (24 * 60), 60)
        lines.append(f"{sh:02d}:{sm:02d}–{eh:02d}:{em:02d} — {tasks[i % len(tasks)]}")
        cursor = block_end
        if i < blocks - 1 and cursor < end:
            break_end = min(cursor + break_len, end)
            bh, bm = divmod(cursor % (24 * 60), 60)
            beh, bem = divmod(break_end % (24 * 60), 60)
            lines.append(f"{bh:02d}:{bm:02d}–{beh:02d}:{bem:02d} — Short break: water, stretch, reset.")
            cursor = break_end

    lines.append("\nStart with the first block only. You don't need to feel motivated before you begin — starting creates the momentum.")
    return "\n".join(lines)


def _validate_timetable(reply, message):
    """Reject an AI timetable that ignores the user's requested duration/window."""
    if not _is_timetable_request(message):
        return True

    ranges = _response_times(reply)
    if not ranges:
        return False

    window = _requested_window(message)
    if window:
        requested_start, requested_end = window
        first_start = min(x[0] for x in ranges)
        last_end = max(x[1] for x in ranges)
        # Allow a plan to begin a little earlier, but never let it finish
        # before the explicit requested end time.
        if last_end < requested_end:
            return False
        # If the user explicitly said "from 6", don't accept a plan beginning
        # far away from that start.
        if abs(first_start - requested_start) > 60:
            return False
        return True

    hours = _requested_hours(message)
    if hours:
        first_start = min(x[0] for x in ranges)
        last_end = max(x[1] for x in ranges)
        elapsed = last_end - first_start
        # For a duration request, the visible clock span must cover at least
        # the requested duration. This catches the old 3-hour -> 1h40 bug.
        return elapsed >= int(hours * 60) - 2

    return True


def generate_general_reply(message, history=None):
    messages = [{"role": "system", "content": GENERAL_SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": message})

    reply = ask_general_llm(messages)

    # A provider can return a polished-looking timetable that is still too
    # short. For timetable requests, fail closed and generate a guaranteed
    # full-length local plan rather than showing an incomplete schedule.
    if _is_timetable_request(message) and not _validate_timetable(reply, message):
        return _fallback_timetable(message)

    return reply
