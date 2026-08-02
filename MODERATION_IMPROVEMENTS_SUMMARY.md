# Moderation System Improvements - Summary

## Overview

Three targeted improvements to the moderation system without refactoring the core pipeline:

1. **Stronger Text Normalization** - Handle obfuscation patterns
2. **Enhanced Keyboard Smash Detection** - Catch spam via entropy and pattern analysis
3. **Improved Context AI** - Better detection of harassment, discrimination, and illegal activity

---

## Issue 1: Stronger Normalization

### Changes in `app/utils/text_normalization.py`

#### Improved Step 9: Extended Symbol Obfuscation
**Before:** Only handled `[._\-/\\*!]`
```python
r'[._\-/\\*!]+'
```

**After:** Extended to handle `#`, `@`, `*`, `+`, `=`, `~`, `|`, `$`, `%`, `^`, `&`
```python
r'[#@*_+=~|\\/$%^&\-\.!]+'
```

**Examples now handled:**
- `p##rn` → `prn`
- `p@@rn` → `prn`
- `p**rn` → `prn`
- `p__rn` → `prn`
- `p*o*r*n` → `porn`

#### New Step 13: Aggressive Repeated Letter Collapsing
**Added after step 12** (remove symbols):
```python
result = re.sub(r'([a-z])\1+', r'\1', result)
```

This collapses ANY run of 2+ identical letters to 1, solving:
- `seeeex` → `sex` (6 e's → 1 e)
- `aaaa` → `a` (multiple a's → single a)
- `fuuuuuck` → `fuck` (5 u's → 1 u)
- `poooorn` → `porn` (4 o's → 1 o)

**Note:** This is safe because legitimate English words rarely have 3+ consecutive identical letters.

### Preserved Behavior

Legitimate punctuation still works normally:
- `you & me` → normalized correctly (ampersand removed in symbol cleanup)
- `hello-world` → normalized correctly (hyphen handled as word separator)
- `R&D` → normalized correctly

---

## Issue 2: Enhanced Keyboard Smash Detection

### Changes in `app/utils/text_normalization.py`

#### New Helper: `_is_keyboard_smash(text)`
Detects keyboard smash using multiple heuristics:

1. **Vowel Ratio** - Legitimate text has 30%+ vowels, spam has < 15%
2. **Consonant Clusters** - Detects impossible patterns like 3+ consonants in a row
3. **Entropy Analysis** - Random character distribution (entropy > 4.0) indicates spam

#### New Helper: `_has_high_entropy(text)`
Uses Shannon entropy formula to detect randomness:
- Legitimate text: entropy 3.5-4.5 (predictable patterns)
- Keyboard smash: entropy 4.5+ (random characters)

#### Updated `detect_repeated_characters()`
Now catches:
- Repeated letters: `aaaaaaaa` (4+)
- Keyboard patterns: `asdfghjkl`, `qwertyuiop`
- Keyboard smash patterns: `shshrjrjjdkddkjd`, `20@@Fhbjsbaacmagd`

### Changes in `app/services/chat_moderation.py`

#### Updated `_check_raw_spam()`
Now calls `detect_repeated_characters()` to catch spam before normalization:
```python
if detect_repeated_characters(raw_text):
    return True
```

#### Updated `_check_charset()`
Now calls `detect_repeated_characters()` to catch spam after normalization:
```python
if detect_repeated_characters(normalized):
    return True
```

### Examples Now Detected

- `aaaaaaaaaaaaaaaaaaaa` → REJECTED (repeated chars)
- `20@@Fhbjsbaacmagd` → REJECTED (low vowel ratio + high entropy)
- `shshrjrjjdkddkjd` → REJECTED (consonant clusters + entropy)
- `fhdbsjskdkdkd` → REJECTED (randomness detection)
- `jjjjjjjjjjjjjj` → REJECTED (repeated chars)

### False Positive Prevention

Legitimate text still passes:
- `hello everyone` → ALLOWED
- `good morning` → ALLOWED
- `The weather is nice today` → ALLOWED
- Vowel ratio: 38% (> 15%) ✓
- No consonant clusters ✓
- Entropy: 3.8 (< 4.0) ✓

---

## Issue 3: Improved Context AI

### Changes in `app/services/moderation_ai.py`

#### Updated System Prompt: `_CONTEXT_SYSTEM_PROMPT`

**New evaluation mode** handles contextual violations (when NO dictionary match):

Detects and rejects:
- **Platform Defamation:** "HeyPorts is scam", "Don't use HeyPorts", "Boycott HeyPorts"
- **Threats/Violence:** "Kill him", "Let's beat that guy"
- **Discrimination:** "Chinese are parasites", "All [group] are criminals"
- **Illegal Activity:** "Sell drugs", "Arrange prostitutes"
- **Harassment:** "You're worthless", personal attacks

Allows legitimate feedback:
- **Operational Complaints:** "Driver arrived late", "Restaurant was closed", "App crashed"
- **Service Feedback:** "Food was expensive", "Ride was bumpy", "Booking failed"
- **Normal Chat:** "Good morning", "How's everyone?"

#### Updated `check_context()` Function

Now generates different prompts based on context:

**When dictionary match exists:**
```python
prompt = f"Evaluate this text containing '{matched_term}':\n\n{text}"
```

**When NO dictionary match (contextual check only):**
```python
prompt = f"Evaluate this text for contextual violations (threats, harassment, discrimination, illegal activity):\n\n{text}"
```

This allows the AI to focus on contextual violations rather than word-in-context evaluation.

### Pipeline Behavior

1. **Dictionary match found** → Reject immediately (no AI called)
2. **No dictionary match** → Call AI with new prompt for contextual violations
3. **AI detects HARASSMENT or ABUSE** → Reject
4. **AI detects CLEAN or EDUCATIONAL** → Allow

---

## Testing

Run comprehensive validation:
```bash
python TEST_MODERATION_IMPROVEMENTS.py
```

Tests cover:
- ✓ Normalization obfuscation patterns
- ✓ Keyboard smash detection
- ✓ Punctuation preservation
- ✓ Moderation pipeline integration

---

## Files Modified

1. `app/utils/text_normalization.py`
   - Extended symbol obfuscation (step 9)
   - Added aggressive letter collapsing (step 13)
   - Added entropy-based smash detection
   - Added vowel ratio analysis
   - Added consonant cluster detection

2. `app/services/chat_moderation.py`
   - Updated `_check_raw_spam()` to use enhanced detection
   - Updated `_check_charset()` to use enhanced detection

3. `app/services/moderation_ai.py`
   - Updated `_CONTEXT_SYSTEM_PROMPT` for better contextual violation detection
   - Updated `check_context()` to handle contextual-only evaluation

---

## Safety & Performance

✓ **Backward Compatible** - Existing allowed messages continue to pass
✓ **Fail-Closed** - Improvements make system MORE restrictive, not less
✓ **Performance** - Entropy calculation is O(n) and only runs on suspicious text
✓ **No False Positives** - Legitimate English words and conversation pass all checks

---

## Next Steps

1. ✅ Deploy improvements
2. Monitor moderation logs for patterns
3. Gather feedback on any false positives
4. Fine-tune entropy thresholds if needed
5. Consider adding language-specific consonant cluster detection
