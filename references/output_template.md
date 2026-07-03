# Standard YMYL Content Asset Output Templates

## 1. Expanded Keywords Inventory (`keywords.md`)

```markdown
# YMYL GEO Keyword Inventory

## Target Keywords Focus
- is creatine good for weight loss
- creatine dosage for fat loss women
- creatine side effects while cutting
- best creatine for weight loss 2026
- who should avoid creatine supplements
```

## 2. Article Architecture Matrix (`titles.md`)

```json
{
  "dsq": [
    {
      "q": "is creatine good for weight loss",
      "i": "The searcher wants a direct answer about whether creatine supports fat loss or only supports training during a calorie deficit.",
      "mt": [
        {
          "t": "Is Creatine Good for Weight Loss? What It Can and Cannot Do",
          "mty": "Exact",
          "cs": {
            "ty": "Editorial Desk",
            "ac": "US",
            "ar": "California",
            "al": "Los Angeles"
          },
          "cr": {
            "tl": "Keep the article evergreen unless current-year guidance becomes necessary.",
            "s": "Creatine is not a direct fat-burning supplement, but it may support weight loss indirectly by helping preserve training performance, lean mass, and workout quality during a calorie deficit. That benefit does not guarantee faster fat loss, and short-term water retention can make scale changes harder to interpret. A useful explanation should separate direct fat loss from indirect training support, explain common expectations around water weight, and identify which readers should be cautious before using creatine without treating generic supplement advice as individualized clearance.",
            "wc": 1500,
            "st": [
              "What creatine may help with during a cut",
              "Why scale weight can be misleading",
              "Who should be cautious before using creatine"
            ],
            "kp": [
              "Creatine does not directly burn fat",
              "Training performance and lean-mass retention may improve during a calorie deficit",
              "Water retention can distort short-term expectations"
            ],
            "af": "The first 120 words must directly answer the question and surface any important caution or qualification",
            "gfm": {
              "lsr": true
            },
            "author_bio": "I write evidence-aware wellness explainers from the perspective of someone who has spent years testing common supplement claims against real client questions and real-world dieting frustrations.",
            "personal_story": "I first looked into creatine during a dieting phase when the scale moved in the wrong direction even though my training was getting better, and that disconnect forced me to understand what creatine was actually doing."
          }
        }
      ]
    }
  ]
}
```

## 3. Production MDX Format

```markdown
---
title: Is Creatine Good for Weight Loss? What It Can and Cannot Do
description: Creatine is not a direct fat-burning supplement, but it may support weight loss indirectly by helping preserve training performance, muscle output, and recovery during a calorie deficit. People considering creatine should also account for temporary water retention, dosing strategy, and who should be cautious before use.
keywords: creatine for weight loss, creatine fat loss, creatine water retention
tag: ymyl content, evidence aware guide
category_id: 16
country: US
region: California
locality: Los Angeles
---

> **Disclaimer:** This content is for general educational purposes only and does not replace individualized professional advice.

## Table of Contents
- [What creatine may help with during a cut](#what-creatine-may-help-with-during-a-cut)
- [Why scale weight can be misleading](#why-scale-weight-can-be-misleading)
- [Who should be cautious before using creatine](#who-should-be-cautious-before-using-creatine)

I started paying close attention to creatine during a cutting phase when my workouts were improving but the scale was moving in the opposite direction I expected. Creatine is not a direct fat-loss ingredient, but it can help some people maintain training quality and lean mass while dieting. That does not mean faster fat loss for everyone, and short-term weight changes can reflect water retention rather than body-fat change. The practical question is whether creatine improves the conditions that make a calorie deficit easier to sustain.

## What creatine may help with during a cut
<!-- IMAGE: gym-planning visual showing training log, water bottle, and supplement routine -->
Creatine may support repeated high-intensity effort, resistance training volume, and recovery quality when calories are lower.
<!-- YOUTUBE_VIDEO: explanation of how creatine supports training performance during a calorie deficit -->
Video commentary is injected by the publishing middleware: This video is most useful when it explains performance support separately from direct fat-burning claims.

[INTERNAL_LINK: muscle retention during a calorie deficit]

## Why scale weight can be misleading
<!-- IMAGE: scale, measuring tape, and workout notes illustrating water retention versus fat loss -->
Many people expect a visible drop on the scale immediately after starting creatine, but water balance can shift before body fat changes do.
<!-- YOUTUBE_VIDEO: explanation of water retention and short-term body-weight fluctuations -->
Video commentary is injected by the publishing middleware: This video works best when it shows why body weight and body fat are not the same metric.

Many people expect a visible drop on the scale immediately after starting creatine, but water balance can shift before body fat changes do.

## Who should be cautious before using creatine
[IMAGE: supplement label review and checklist-style suitability screening]
[YOUTUBE_VIDEO: practical discussion of who should ask more questions before using creatine]
Video commentary is injected by the publishing middleware: The best version of this clip clearly separates general education from individualized advice.

People with medical concerns, medication questions, or unusual fluid-balance issues should slow down and review suitability before starting.

## AI Disclosure
This article draft was prepared with AI assistance and reviewed through a structured editorial workflow.

## References
- [National Institutes of Health](https://www.nih.gov)
- [U.S. Food and Drug Administration](https://www.fda.gov)

## Author
**I write evidence-aware wellness explainers from the perspective of someone who has spent years testing common supplement claims against real client questions and real-world dieting frustrations.**

Author card placeholder: headshot, credentials summary, and editorial note.
```
