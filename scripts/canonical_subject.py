#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Clean long-tail keywords into usable title subjects.

The title engine should not blindly print the entire raw keyword inside a
headline. This module turns noisy search phrases into a cleaner subject while
preserving the main SEO entity and intent.
"""

from __future__ import annotations

import re

SMALL_WORDS = {"a", "an", "and", "as", "at", "by", "for", "from", "in", "is", "of", "on", "or", "the", "to", "vs", "with"}
BRAND_MAP = {
    "bluechew": "BlueChew",
    "extenze": "ExtenZe",
    "ozempic": "Ozempic",
    "wegovy": "Wegovy",
    "mounjaro": "Mounjaro",
    "zepbound": "Zepbound",
    "semaglutide": "Semaglutide",
    "tirzepatide": "Tirzepatide",
    "retatrutide": "Retatrutide",
    "metformin": "Metformin",
    "topiramate": "Topiramate",
    "contrave": "Contrave",
    "phentermine": "Phentermine",
    "alli": "Alli",
    "orlistat": "Orlistat",
    "cbd": "CBD",
    "ed": "ED",
    "glp": "GLP",
    "fda": "FDA",
    "a1c": "A1C",
    "ldl": "LDL",
    "hdl": "HDL",
    "mct": "MCT",
    "pcos": "PCOS",
}
PUBLIC_NAMES = {
    "jelly roll": "Jelly Roll",
    "nikocado avocado": "Nikocado Avocado",
    "kelly clarkson": "Kelly Clarkson",
    "fat joe": "Fat Joe",
    "mike pompeo": "Mike Pompeo",
    "scott disick": "Scott Disick",
    "dr oz": "Dr. Oz",
    "dr barbara o neill": "Dr. Barbara O'Neill",
    "dr barbara o'neill": "Dr. Barbara O'Neill",
}


def normalize(text: str) -> str:
    text = str(text or "").replace("’", "'").replace("–", "-").replace("—", "-")
    text = re.sub(r"[:;|]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def title_case(text: str) -> str:
    words = re.sub(r"[^a-zA-Z0-9+%']+", " ", str(text or "")).split()
    out: list[str] = []
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
    k = re.sub(r"\s+", " ", k).strip()
    return k


def public_subject(k: str) -> str | None:
    for needle, name in PUBLIC_NAMES.items():
        if needle in k:
            if "ozempic" in k:
                return f"{name} Ozempic Weight Loss"
            if re.search(r"\b(beard|shaved)\b", k) and "200" in k:
                return f"{name} Weight Loss"
            return f"{name} Weight Loss"
    return None


def medication_subject(k: str) -> str | None:
    meds = ["ozempic", "wegovy", "mounjaro", "zepbound", "semaglutide", "tirzepatide", "retatrutide", "metformin", "topiramate", "contrave", "alli", "orlistat", "phentermine"]
    found = next((m for m in meds if m in k), None)
    if not found:
        return None
    med = title_case(found)
    if re.search(r"\b(dose|dosage|dosing|chart|units|mg|ml|maximum dose|starting dose|maintenance dose)\b", k):
        if "chart" in k:
            return f"{med} Dosage Chart for Weight Loss"
        return f"{med} Dosage for Weight Loss"
    if re.search(r"\b(side effects?|safe|safety|risks?|warning)\b", k):
        return f"{med} Side Effects for Weight Loss"
    if re.search(r"\b(cost|price|insurance|cover|coverage|how to get|get prescribed|near me)\b", k):
        return f"{med} for Weight Loss"
    if " vs " in k or " versus " in k:
        return title_case(k)
    return f"{med} for Weight Loss" if "weight loss" in k else med


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
    if "coffee method" in k or "coffee hack" in k:
        return "Coffee Method for Weight Loss"
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
    if "high protein" in k:
        if "breakfast" in k:
            return "High Protein Breakfast for Weight Loss"
        if "snack" in k:
            return "High Protein Snacks for Weight Loss"
        if "meal" in k or "recipe" in k:
            return "High Protein Meals for Weight Loss"
        return "High Protein Foods for Weight Loss"
    if "smoothie" in k or "shake" in k:
        return "Weight Loss Smoothies"
    if "juice" in k:
        return "Weight Loss Juice Recipes" if "recipe" in k else "Juice for Weight Loss"
    if "green tea" in k:
        return "Green Tea for Weight Loss"
    if "tea" in k:
        return "Tea for Weight Loss"
    if "oatmeal" in k or "oats" in k:
        return "Oatmeal for Weight Loss"
    if "milk" in k:
        return "Milk for Weight Loss"
    if "fruit" in k or "pineapple" in k or "apple" in k or "avocado" in k:
        if "pineapple" in k:
            return "Pineapple for Weight Loss"
        if "avocado" in k:
            return "Avocado for Weight Loss"
        if "apple" in k:
            return "Apples for Weight Loss"
        return "Fruit for Weight Loss"
    if "mct oil" in k:
        return "MCT Oil for Weight Loss"
    if "olive oil" in k:
        return "Olive Oil for Weight Loss"
    if "probiotic" in k:
        return "Probiotics for Weight Loss"
    if "turmeric" in k:
        return "Turmeric for Weight Loss"
    if "cinnamon" in k:
        return "Cinnamon for Weight Loss"
    return None


def clean_question(k: str) -> str:
    q = normalize(k)
    q = re.sub(r"\bdoes\s+(.+?)\s+help\s+with\s+weight\s+loss\b", r"Does \1 Help With Weight Loss", q)
    q = re.sub(r"\bdo\s+(.+?)\s+help\s+with\s+weight\s+loss\b", r"Do \1 Help With Weight Loss", q)
    q = re.sub(r"\bis\s+(.+?)\s+good\s+for\s+weight\s+loss\b", r"Is \1 Good for Weight Loss", q)
    q = re.sub(r"\bdoes\s+(.+?)\s+really\s+work\b", r"Does \1 Really Work", q)
    q = re.sub(r"\bdo\s+(.+?)\s+work\b", r"Do \1 Work", q)
    if q != normalize(k):
        return title_case(q)
    return f"Does {canonicalize_title_subject(k)} Actually Work"


def canonicalize_title_subject(keyword: str) -> str:
    k = remove_noise(keyword)
    # Trend recipes must beat true medication matching for natural/homemade Mounjaro queries.
    for resolver in (public_subject, recipe_subject, food_subject, medication_subject):
        value = resolver(k)
        if value:
            return value
    k = re.sub(r"^(how do you|how to|what is|what are|when to|best time to|does|do|is|are|can)\s+", "", k)
    k = re.sub(r"\b(how to|how do you)\b", "", k)
    k = re.sub(r"\s+", " ", k).strip()
    return title_case(k)


def canonicalize_title_question(keyword: str) -> str:
    k = normalize(keyword)
    if re.match(r"^(do|does|can|will|is|are|should|how effective)\b", k) or "really work" in k or "actually work" in k or "help with" in k or "good for" in k:
        return clean_question(k).rstrip("?")
    return f"Does {canonicalize_title_subject(keyword)} Actually Work"


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("keyword", nargs="+")
    args = parser.parse_args()
    text = " ".join(args.keyword)
    print(canonicalize_title_subject(text))
    print(canonicalize_title_question(text))
