# NetSage AI Demo

This folder contains a self-contained demonstration of the complete NetSage
AI pipeline:

```
Case → Rule Checker → AI Diagnosis → Human Review → Responsible AI Log → Dashboard
```

## Files

| File | Purpose |
|------|---------|
| `run_demo.py` | Runs the full pipeline from a single script |
| `../DEMO_WALKTHROUGH.md` | Presenter script (what to show and say at each step) |

## Run the demo

```powershell
py -3.12 demo\run_demo.py
```

Read the accompanying step-by-step script in `DEMO_WALKTHROUGH.md`.

## Integrity

The demo reads the REAL 33-case dataset (`data/cases.csv`) but uses
temporary review stores and log files, so the real review data
(`data/reviews.json` and `responsible_ai/ai_corrections.csv`) is never
modified. The AI-diagnosis engine runs in demo mode and clearly labels its
output as simulated — no genuine-AI results are fabricated.
