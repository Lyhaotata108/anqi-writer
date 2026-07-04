#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean long-tail keywords into usable title subjects and questions.

V2.1:
- Keep timing / injection-site / tea subtype / protein drink signals.
- Avoid ugly subjects like "Weight Loss Pills Work" or "Take Berberine".
- Emit stable cluster keys for de-duplication.
"""

from __future__ import annotations
import re

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
BRAND_MAP = {
    "bluechew": "BlueChew", "extenze": "ExtenZe", "ozempic": "Ozempic", "wegovy": "Wegovy",
    "mounjaro": "Mounjaro", "zepbound": "Zepbound", "semaglutide": "Semaglutide",
    "tirzepatide": "Tirzepatide", "retatrutide": "Retatrutide", "metformin": "Metformin",
    "topiramate": "Topiramate", "contrave": "Contrave", "phentermine": "Phentermine",
    "alli": "Alli", "orlistat": "Orlistat", "cbd": "CBD", "ed": "ED", "glp": "GLP",
    "fda": "FDA", "a1c": "A1C", "ldl": "LDL", "hdl": "HDL", "mct": "MCT", "pcos": "PCOS",
    "acv": "ACV", "otc": "OTC",
}
PUBLIC_NAMES = {
    "jelly roll": "Jelly Roll", "nikocado avocado": "Nikocado Avocado", "nikocado": "Nikocado Avocado",
    "kelly clarkson": "Kelly Clarkson", "fat joe": "Fat Joe", "mike pompeo": "Mike Pompeo",
    "scott disick": "Scott Disick", "dr oz": "Dr. Oz", "dr barbara o neill": "Dr. Barbara O'Neill",
    "dr barbara o'neill": "Dr. Barbara O'Neill",
}
TEA_SUBJECTS = [
    ("ginger tea", "Ginger Tea for Weight Loss"),
    ("turmeric tea", "Turmeric Tea for Weight Loss"),
    ("dandelion tea", "Dandelion Tea for Weight Loss"),
    ("chamomile tea", "Chamomile Tea for Weight Loss"),
    ("yerba mate", "Yerba Mate Tea for Weight Loss"),
    ("mate tea", "Yerba Mate Tea for Weight Loss"),
    ("detox tea", "Detox Tea for Weight Loss"),
    ("herbal tea", "Herbal Tea for Weight Loss"),
    ("hot tea", "Hot Tea for Weight Loss"),
    ("green tea", "Green Tea for Weight Loss"),
]


def normalize(text: str) -> str:
    text = str(text or "").replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[:;|]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def title_case(text: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9+%']+", " ", str(text or "")).split()
    out = []
    for i, word in enumerate(words):
        lower = word.lower().strip("'")
        if lower in BRAND_MAP:
            out.append(BRAND_MAP[lower])
        elif i and lower in SMALL_WORDS:
            out.append(lower)
        else:
            out.append(lower[:1].upper() + lower[1:])
    return " ".join(out).strip() or "Article"


def remove_noise(text: str) -> str:
    k = normalize(text)
    k = re.sub(r"\b(pdf|today|pictures?|photos?|before and after pictures|before after)\b", " ", k)
    k = re.sub(r"\b(reviews?|results?|reddit)\b$", " ", k)
    return re.sub(r"\s+", " ", k).strip()


def public_subject(k: str) -> str | None:
    for needle, name in PUBLIC_NAMES.items():
        if needle in k:
            if "ozempic" in k:
                return f"{name} Ozempic Weight Loss"
            return f"{name} Weight Loss"
    return None


def found_medication(k: str) -> str | None:
    meds = ["ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide", "tirzepatide", "retatrutide", "metformin", "topiramate", "contrave", "alli", "orlistat", "phentermine", "berberine"]
    return next((m for m in meds if m in k), None)


def timing_subject(k: str) -> str | None:
    if not re.search(r"\b(best time|when to take|how long|how fast|how quickly|how soon|time to take|before or after)\b", k):
        return None
    med = found_medication(k)
    if med:
        return f"{title_case(med)} Timing for Weight Loss"
    if "protein" in k:
        return "Protein Timing for Weight Loss"
    return None


def injection_subject(k: str) -> str | None:
    if not re.search(r"\b(best place to inject|where to inject|injection site|inject .+ stomach|inject .+ thigh|site rotation)\b", k):
        return None
    med = found_medication(k)
    if med:
        return f"{title_case(med)} Injection Site for Weight Loss"
    return "Injection Site for Weight Loss"


def medication_subject(k: str) -> str | None:
    med = found_medication(k)
    if not med:
        return None
    label = title_case(med)
    if re.search(r"\b(dose|dosage|dosing|chart|units|mg|ml|maximum dose|starting dose|maintenance dose)\b", k):
        return f"{label} Dosage Chart for Weight Loss" if "chart" in k else f"{label} Dosage for Weight Loss"
    if re.search(r"\b(side effects?|safe|safety|risks?|warning)\b", k):
        return f"{label} Side Effects for Weight Loss"
    if re.search(r"\b(cost|price|insurance|cover|coverage|how to get|get prescribed|near me)\b", k):
        return f"{label} for Weight Loss"
    if " vs " in k or " versus " in k:
        return title_case(k)
    return f"{label} for Weight Loss" if "weight loss" in k else label


def recipe_subject(k: str) -> str | None:
    if re.search(r"\b(homemade|natural|japanese|brazilian)\b", k) and "mounjaro" in k:
        prefix = next((p for p in ["homemade", "natural", "japanese", "brazilian"] if p in k), "homemade")
        return f"{title_case(prefix)} Mounjaro Recipe for Weight Loss"
    if "pink salt" in k or "himalayan salt" in k or "himalayan pink salt" in k:
        return "Pink Salt Recipe for Weight Loss" if "recipe" in k else "Pink Salt Trick for Weight Loss"
    if "apple cider vinegar" in k or "acv" in k or "bragg" in k or "braggs" in k:
        return "Apple Cider Vinegar for Weight Loss"
    if "gelatin" in k or "jello" in k:
        return "Gelatin Trick for Weight Loss" if "trick" in k else "Gelatin Recipe for Weight Loss"
    if "coffee method" in k or "coffee hack" in k or "mushroom coffee" in k:
        return "Coffee Method for Weight Loss" if "method" in k or "hack" in k else "Mushroom Coffee for Weight Loss"
    if "lemon balm" in k:
        return "Lemon Balm for Weight Loss"
    if "chia" in k:
        return "Chia Seeds for Weight Loss"
    if "cabbage soup" in k:
        return "Cabbage Soup for Weight Loss"
    if "baking soda" in k:
        return "Baking Soda for Weight Loss"
    if "cortisol cocktail" in k:
        return "Cortisol Cocktail for Weight Loss"
    return None


def food_subject(k: str) -> str | None:
    if "protein drink" in k or "protein shake" in k or "protein shakes" in k:
        return "Protein Drinks for Weight Loss"
    if "high protein" in k:
        if "breakfast" in k: return "High Protein Breakfast for Weight Loss"
        if "snack" in k: return "High Protein Snacks for Weight Loss"
        if "meal" in k or "recipe" in k: return "High Protein Meals for Weight Loss"
        return "High Protein Foods for Weight Loss"
    if "smoothie" in k or "shake" in k: return "Weight Loss Smoothies"
    if "juice" in k: return "Weight Loss Juice Recipes" if "recipe" in k else "Juice for Weight Loss"
    for needle, subject in TEA_SUBJECTS:
        if needle in k:
            return subject
    if re.search(r"\btea|teas\b", k): return "Tea for Weight Loss"
    if "oatmeal" in k or "oats" in k: return "Oatmeal for Weight Loss"
    if "milk" in k: return "Milk for Weight Loss"
    if "fruit" in k or "pineapple" in k or "apple" in k or "avocado" in k:
        if "pineapple" in k: return "Pineapple for Weight Loss"
        if "avocado" in k: return "Avocado for Weight Loss"
        if "apple" in k: return "Apples for Weight Loss"
        return "Fruit for Weight Loss"
    if "mct oil" in k: return "MCT Oil for Weight Loss"
    if "olive oil" in k: return "Olive Oil for Weight Loss"
    if "probiotic" in k or "lactobacillus" in k: return "Probiotics for Weight Loss"
    if "turmeric" in k: return "Turmeric for Weight Loss"
    if "cinnamon" in k: return "Cinnamon for Weight Loss"
    return None


def strip_question_prefix(k: str) -> str:
    k = re.sub(r"^(how do you|how to|what is|what are|when to|best time to|does|do|is|are|can|will|should)\s+", "", k)
    k = re.sub(r"\b(help with|good for|really work|actually work|work)\b", "", k)
    return re.sub(r"\s+", " ", k).strip()


def canonicalize_title_subject(keyword: str) -> str:
    k = remove_noise(keyword)
    for resolver in (public_subject, timing_subject, injection_subject, recipe_subject, food_subject, medication_subject):
        value = resolver(k)
        if value:
            return value
    cleaned = strip_question_prefix(k)
    return title_case(cleaned)


def clean_question(k: str) -> str:
    q = normalize(k)
    direct = q
    direct = re.sub(r"\bdoes\s+(.+?)\s+help\s+with\s+weight\s+loss\b", r"Does \1 Help With Weight Loss", direct)
    direct = re.sub(r"\bdo\s+(.+?)\s+help\s+with\s+weight\s+loss\b", r"Do \1 Help With Weight Loss", direct)
    direct = re.sub(r"\bis\s+(.+?)\s+good\s+for\s+weight\s+loss\b", r"Is \1 Good for Weight Loss", direct)
    direct = re.sub(r"\bdoes\s+(.+?)\s+really\s+work\b", r"Does \1 Really Work", direct)
    direct = re.sub(r"\bdo\s+(.+?)\s+work\b", r"Do \1 Work", direct)
    if direct != q:
        return title_case(direct)
    subject = canonicalize_title_subject(k)
    if subject.endswith(" Work"):
        subject = subject[:-5]
    return f"Does {subject} Actually Work"


def canonicalize_title_question(keyword: str) -> str:
    k = normalize(keyword)
    if re.match(r"^(do|does|can|will|is|are|should|how effective)\b", k) or "really work" in k or "actually work" in k or "help with" in k or "good for" in k:
        return clean_question(k).rstrip("?")
    return f"Does {canonicalize_title_subject(keyword)} Actually Work"


def canonical_cluster_key(keyword: str, intent_family: str | None = None) -> str:
    subject = canonicalize_title_subject(keyword).lower()
    subject = re.sub(r"[^a-z0-9]+", "-", subject).strip("-")
    intent = re.sub(r"[^a-z0-9]+", "-", (intent_family or "general").lower()).strip("-")
    return f"{subject}__{intent}"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("keyword", nargs="+")
    args = parser.parse_args()
    text = " ".join(args.keyword)
    print(canonicalize_title_subject(text))
    print(canonicalize_title_question(text))
    print(canonical_cluster_key(text))
