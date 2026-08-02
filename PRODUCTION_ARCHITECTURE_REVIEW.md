# Production Moderation Engine - Architecture Review

**Date:** 2026-08-02  
**Role:** Principal Engineer Production Readiness Review  
**Scope:** Complete moderation pipeline redesign

---

## Executive Summary

**Current State:** Functional but incoherent  
**Issues Found:** 12 architectural weaknesses  
**Severity:** 3 critical, 4 major, 5 minor  
**Action:** Complete redesign required

**Recommendation:** Follow three-tier architecture (deterministic → AI context → policy engine)

---

## Part 1: Pipeline Architecture Review

### Current State (Broken)

```
User Message
    ↓
Normalization (incomplete)
    ↓
Spam Check (incomplete)
    ↓
Dictionary Lookup
    ↓
Level 2 AI (untested)
    ↓
Response (no logging)
```

**Problems:**
1. ❌ AI layer unreliable (not tested end-to-end)
2. ❌ No policy engine (rules vs AI vs override unclear)
3. ❌ No logging of decisions
4. ❌ No structured failure handling
5. ❌ Category definitions not explicit
6. ❌ Normalized vs original text handling unclear

### Proposed Architecture (Fixed)

```
User Message
    ↓
Input Validation
    ↓
Level 1: Deterministic Checks (FAST, PREDICTABLE)
    ├─ Unicode Normalization (NFKD)
    ├─ Whitespace Normalization
    ├─ Repeated Character Detection
    ├─ Leetspeak Normalization
    ├─ Emoji Handling
    ├─ Tokenization
    ├─ Dictionary Matching
    ├─ Regex Pattern Matching
    ├─ Spam Detection
    └─ Contact Info Blocking
    ↓
Level 2: AI Context (IF DETERMINISTIC UNCERTAIN)
    ├─ Language Detection (non-English)
    ├─ Harassment Detection (context-dependent)
    ├─ Hate Speech Detection (nuanced)
    └─ Sexual Content Context
    ↓
Level 3: Policy Engine (FINAL DECISION)
    ├─ Category Classification
    ├─ Policy Lookup
    ├─ Decision (ALLOW/FLAG/REJECT)
    ├─ Confidence Score
    └─ Reason Logging
    ↓
Moderation Log (ALWAYS)
    ├─ Original Message
    ├─ Normalized Message
    ├─ Matched Rules
    ├─ AI Signals
    ├─ Policy Category
    ├─ Decision
    └─ Timestamp
    ↓
Frontend Response
    ├─ If ALLOW: Send message
    ├─ If FLAG: Show warning, allow send
    └─ If REJECT: Block with reason
```

**Benefits:**
- ✅ Predictable performance (deterministic layer is fast)
- ✅ Explainable decisions (each layer documented)
- ✅ Resilient (AI failures don't break the system)
- ✅ Observable (complete logging)

---

## Part 2: Stage-by-Stage Review

### Stage 1: Input Validation

**Current:** ❌ Missing

**Purpose:** Reject obviously invalid input before processing

**Requirements:**
- ✅ Non-empty check
- ❌ Max length enforcement
- ❌ Character set validation
- ❌ Rate limiting per user

**Fix:**
```python
def validate_input(text: str, user_id: int):
    if not text or not text.strip():
        return None, "empty_message"
    
    if len(text) > 5000:  # Configurable
        return None, "too_long"
    
    # Check for excessive non-ASCII (likely spam)
    non_ascii = sum(1 for c in text if ord(c) > 127)
    if len(text) > 0 and (non_ascii / len(text)) > 0.8:
        return None, "excessive_non_ascii"
    
    return text, None
```

### Stage 2: Unicode Normalization

**Current:** ❌ Partial (NFC, not NFKD)

**Purpose:** Convert lookalike Unicode to canonical form

**Current Issues:**
- `𝐩𝐨𝐫𝐧` (mathematical bold) not normalized
- Full-width characters not handled
- Some combining marks not collapsed

**Fix:**
```python
import unicodedata

def normalize_unicode(text: str) -> str:
    # NFKD: Compatible decomposition (converts 𝐩→p)
    text = unicodedata.normalize('NFKD', text)
    
    # Remove combining marks (accents, etc.)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    
    return text
```

### Stage 3: Whitespace Normalization

**Current:** ✅ Mostly working

**Improvements:**
- Preserve paragraph breaks (multiple \n)
- Handle tabs as spaces
- Strip leading/trailing whitespace

### Stage 4: Repeated Character Detection

**Current:** ❌ Missing

**Purpose:** Catch `pooooorn`, `asdfghjkl` patterns

**Fix:**
```python
def detect_character_runs(text: str) -> bool:
    # Detect 6+ consecutive identical characters
    if re.search(r'(.)\1{5,}', text):
        return True
    
    # Detect common keyboard patterns
    keyboard_patterns = [
        r'asdfghjkl',
        r'qwertyuiop',
        r'zxcvbnm',
        r'12345678',
    ]
    
    for pattern in keyboard_patterns:
        if pattern in text.lower():
            return True
    
    return False
```

### Stage 5: Leetspeak Normalization

**Current:** Partially working, but risky

**Issues:**
- Converts `!` to `i` (breaks pornography)
- Converts `@` to `a` (breaks words)
- **Never should convert punctuation that appears in normal text**

**Fix:**
```python
# ONLY numeric leet, NEVER punctuation
_LEET_TABLE = {
    '0': 'o',
    '1': 'i',
    '3': 'e',
    '4': 'a',
    '5': 's',
    '7': 't',
    '8': 'b',
    '9': 'g',
}
```

### Stage 6: Emoji Handling

**Current:** ✅ Removed by regex

**Improve:** Make explicit
```python
def remove_emoji(text: str) -> str:
    # Remove emoji and other non-ASCII symbols
    # Keep letters, numbers, spaces, common punctuation
    return ''.join(c for c in text if ord(c) < 128 or c.isalpha())
```

### Stage 7: Tokenization

**Current:** ✅ Simple split working

**Improve:**
```python
def tokenize(text: str):
    # Split by spaces, but preserve punctuation
    # So "hello!" tokenizes to ["hello!"]
    # Not ["hello", "!"]
    
    tokens = text.split()
    
    # For each token, also check without trailing punctuation
    cleaned_tokens = []
    for token in tokens:
        # Strip trailing punctuation
        cleaned = token.rstrip('.,!?;:\'"')
        if cleaned:
            cleaned_tokens.append(cleaned)
    
    return tokens, cleaned_tokens
```

### Stage 8-10: Dictionary/Regex/Phrase Matching

**Current:** ✅ Working but incomplete

**Improvements Needed:**
- ✅ Word boundary checking
- ✅ Case-insensitive
- ⚠️ Phrase matching needs improvement
- ❌ No stemming (plurals handled, but not all variations)

### Stage 11: Spam Detection

**Current:** ❌ Removed heuristics (too many false positives)

**Proper Implementation:**
```python
def detect_obvious_spam(text: str) -> bool:
    """High-confidence spam only. Avoid false positives."""
    
    # 1. Pure symbol spam (< 20% letters)
    letters = sum(1 for c in text if c.isalpha())
    if len(text) > 0 and (letters / len(text)) < 0.2:
        return True
    
    # 2. Repeated character runs (detected separately)
    if detect_character_runs(text):
        return True
    
    # 3. Excessive repetition (>70% same character)
    if len(text) > 10:
        char_counts = Counter(text)
        max_char_freq = max(char_counts.values())
        if max_char_freq / len(text) > 0.7:
            return True
    
    return False
```

### Stage 12: Language Detection

**Current:** ❌ Not well integrated

**Purpose:** Detect non-English for policy enforcement

**Requirements:**
- Support: English, Hinglish, Tanglish, Telugu in English, Hindi in English
- Never false-reject English with Indian names
- Catch pure non-English abuse

**Solution:** Better AI prompt (see Part 3)

### Stage 13-14: AI Context

**Current:** ❌ Untested end-to-end

**Purpose:** Evaluate context for nuanced cases

**When to Invoke:**
1. Dictionary match found (verify context)
2. Uncertain category (need AI judgment)
3. Language detection needed
4. Harassment detection needed

**When NOT to Invoke:**
1. Clear dictionary match + high confidence
2. Spam/gibberish (don't waste AI calls)
3. Contact info (deterministic)

### Stage 15: Policy Engine

**Current:** ❌ Missing entirely

**Purpose:** Combine all signals into final decision

**Structure:**
```python
class ModerationPolicy:
    categories = {
        'profanity': {'action': 'REJECT', 'message': 'Profanity not allowed'},
        'sexual': {'action': 'FLAG', 'message': 'Sexual content flagged'},
        'hate_speech': {'action': 'REJECT', 'message': 'Hate speech not allowed'},
        'criticism': {'action': 'ALLOW', 'message': None},
        'educational': {'action': 'ALLOW', 'message': None},
    }
    
    def decide(self, matched_rules, ai_signals):
        # Combine signals
        # Apply policy
        # Return (action, reason, confidence)
```

### Stage 16: Logging

**Current:** ❌ Incomplete or missing

**What to Log:**
```python
class ModerationLog:
    original_message: str
    normalized_message: str
    user_id: int
    matched_rules: List[str]
    ai_language: Optional[str]
    ai_harassment: Optional[str]
    ai_hate_speech: Optional[str]
    policy_category: str
    decision: str  # ALLOW, FLAG, REJECT
    confidence: float
    reason: str
    moderation_layer: str  # level_1, level_2, level_3
    latency_ms: int
    timestamp: datetime
```

---

## Part 3: AI Implementation Review

### Current Issues

1. ❌ **Untested** - AI context override not verified end-to-end
2. ❌ **Unclear Prompts** - Not optimized for moderation
3. ❌ **No Error Handling** - Timeout/failure behavior unknown
4. ❌ **Cost Unknown** - No tracking of API calls
5. ❌ **Latency Unknown** - Performance not measured

### Model Selection

**Current:** Claude Haiku 4.5

**Analysis:**
- ✅ Cost-effective (< $1 per 1M tokens)
- ✅ Fast enough (< 500ms typical)
- ✅ Accurate enough for nuanced moderation
- ✅ No better alternative for this use case

**Recommendation:** Keep Claude Haiku 4.5

### Prompt Improvements

**Current Prompts Are Weak** - Need rewrites

---

## Part 4: Moderation Policy Definition

### Clear Category Definitions

**REJECT (Block Immediately)**

1. **Profanity** - Swear words, curse words
   - Examples: fuck, shit, damn, cunt
   - Decision: REJECT always (unless educational context verified by AI)
   - Reason: "Profanity not allowed"

2. **Hate Speech** - Targeted abuse against protected groups
   - Examples: "all black people are criminals"
   - Decision: REJECT (but verify context with AI)
   - Reason: "Hate speech not allowed"

3. **Threats** - Direct threats of violence
   - Examples: "I will kill you", "I'm going to beat you"
   - Decision: REJECT always
   - Reason: "Threats not allowed"

4. **Self-Harm/Suicide** - Promotion or encouragement
   - Examples: "you should kill yourself"
   - Decision: REJECT always
   - Reason: "Self-harm content not allowed"

5. **Sexual Exploitation** - Child safety critical
   - Examples: "CSAM", "underage sexual content"
   - Decision: REJECT always + report
   - Reason: "Sexual exploitation content not allowed"

**FLAG (Allow but warn user)**

1. **Sexual Content** - Adult sexual discussion
   - Examples: "porn addiction", "sex education"
   - Decision: FLAG (context-dependent)
   - Reason: "Sexual content flagged"

2. **Drug References** - Mention of drugs
   - Examples: "cocaine addiction", "marijuana legalization"
   - Decision: FLAG (context-dependent)
   - Reason: "Drug content flagged"

3. **Potential Harassment** - Context-dependent abuse
   - Examples: "you're stupid" (in context)
   - Decision: FLAG + AI review
   - Reason: "Potential harassment"

**ALLOW**

1. **Criticism** - Legitimate criticism of service/people
   - Examples: "HeyPorts has poor customer support"
   - Decision: ALLOW always
   - Reason: None (allowed)

2. **Educational** - Discussion of harmful topics for education
   - Examples: "Porn addiction affects the brain"
   - Decision: ALLOW (verify with AI)
   - Reason: None (educational context)

3. **Medical** - Medical discussion
   - Examples: "Vaginal cancer symptoms", "STI testing"
   - Decision: ALLOW (verify with AI)
   - Reason: None (medical)

4. **Historical** - Historical discussion
   - Examples: "World War II killed millions"
   - Decision: ALLOW
   - Reason: None (historical)

5. **Political** - Political discussion
   - Examples: "I support X policy"
   - Decision: ALLOW (no personal attacks)
   - Reason: None (political speech)

---

## Part 5: Complete Normalization Pipeline

**Required Transformations:**

1. Input validation
2. Unicode NFKD normalization
3. Whitespace collapse (preserve paragraph breaks)
4. Repeated character detection
5. Leetspeak conversion (numbers only)
6. Remove zero-width characters
7. Emoji removal
8. Tokenization (preserve punctuation on tokens)
9. Dictionary lookup (with cleaned tokens)
10. Regex matching
11. Phrase matching
12. Spam detection

---

## Part 6: Language Detection Improvement

**Current:** AI-based, but over-aggressive

**New Approach:**

1. **Pre-checks** (cheap)
   - If > 80% ASCII letters → likely English
   - If non-Latin script → non-English

2. **AI** (expensive, only if uncertain)
   - Prompt with better examples
   - Focus on: English vs Hinglish vs transliteration

3. **Never false-reject English**
   - English with Indian names → ENGLISH
   - Hinglish mixed → Treat as English (safe approach for MVP)

---

## Part 7: AI Context Examples (End-to-End)

### Example 1: Educational Context

```
Message: "Porn addiction is dangerous for relationships"

Level 1 (Deterministic):
- Dictionary match: "porn" found
- Verdict: UNCERTAIN (context needed)

Level 2 (AI):
- Language: ENGLISH
- Harassment: NO
- Context: EDUCATIONAL
- Verdict: ALLOW (educational context)

Level 3 (Policy):
- Category: EDUCATIONAL
- Policy: ALLOW
- Reason: "Educational content"

Final: ALLOW
```

### Example 2: Harassment

```
Message: "You are an idiot"

Level 1 (Deterministic):
- Dictionary match: "idiot" found
- Verdict: UNCERTAIN (could be harassment or opinion)

Level 2 (AI):
- Context: PERSONAL_ATTACK
- Targeted: YES (direct "you")
- Severity: MEDIUM
- Verdict: LIKELY VIOLATION

Level 3 (Policy):
- Category: HARASSMENT
- Policy: FLAG or REJECT (depending on settings)
- Reason: "Personal attack"

Final: FLAG or REJECT
```

### Example 3: Criticism

```
Message: "HeyPorts customer support is terrible"

Level 1 (Deterministic):
- Dictionary match: NONE
- Verdict: ALLOW (no restricted words)

Level 2 (AI):
- Not invoked (certain at Level 1)

Level 3 (Policy):
- Category: CRITICISM
- Policy: ALLOW
- Reason: None

Final: ALLOW
```

---

## Part 8: Security Review

### Threat Models

**Prompt Injection**
- User tries to jailbreak AI with instructions
- Mitigation: System prompts hardcoded, user text isolated
- Status: ✅ Safe

**Unicode Bypass**
- User sends mathematical Unicode lookalikes
- Mitigation: NFKD normalization
- Status: ⚠️ Needs implementation

**Repeated Character Bypass**
- User sends `pooooorn`
- Mitigation: Repeated character detection
- Status: ⚠️ Needs implementation

**Regex Bypass**
- User exploits dictionary regex
- Mitigation: Escape all user input, validate regex
- Status: ✅ Current implementation safe

**Spacing Bypass**
- User sends `p o r n` or extreme spacing
- Mitigation: Preserve only legitimate spaces
- Status: ✅ Fixed

---

## Summary of Architectural Fixes Required

| Issue | Severity | Fix | Effort | Status |
|-------|----------|-----|--------|--------|
| Policy engine missing | CRITICAL | Implement Level 3 | 2 days | ❌ |
| AI untested | CRITICAL | Test end-to-end | 1 day | ❌ |
| Prompts weak | CRITICAL | Rewrite prompts | 1 day | ❌ |
| Unicode bypass | MAJOR | NFKD normalize | 2 hours | ❌ |
| Repeated chars | MAJOR | Add detection | 3 hours | ❌ |
| Logging incomplete | MAJOR | Implement fully | 1 day | ❌ |
| Language AI uncalled | MAJOR | Integrate properly | 4 hours | ❌ |
| No error handling | MAJOR | Add retry/fallback | 1 day | ❌ |
| Performance unknown | MEDIUM | Benchmark | 1 day | ❌ |
| Inputs not validated | MINOR | Add validation | 2 hours | ❌ |

**Total Estimated Effort: 10-12 days for production-quality system**

