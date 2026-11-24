# AI RMF sources

`AI_RMF_Playbook.pdf` is committed (NIST, a US government work, not under copyright). The CIS files are not
redistributed: download each and save it here under the exact name below.
SHA-256 values and download URLs are in `data/metadata.json`; `check_freshness.py --ai-bank` compares them.

| File | Where from |
|---|---|
| `AI_RMF_Playbook.pdf` | https://airc.nist.gov/airmf-resources/playbook/ |
| `CIS_Controls_v8.1_AI_and_LLM_Companion_Guide_April_2026.pdf` | https://www.cisecurity.org/controls |
| `CIS_Controls_v8.1_Model_Context_Protocol_Companion_Guide_April_2026.pdf` | https://www.cisecurity.org/controls |
| `CIS_Controls_v8.1_AI_Agents_Companion_Guide_April_2026.pdf` | https://www.cisecurity.org/controls |

The CIS files are CC BY-NC-ND 4.0: non-commercial use, no derivatives. This repository therefore holds no CIS text:
`data/ai/cis_ai_safeguard_ids.json` (committed) has only the safeguard ids, control numbers and names, and IG levels.
`parse_ai_rmf_sources.py` writes the full text to `data/ai/cis_ai_safeguards.json`, which stays on your machine
(`.gitignore`). Answering a questionnaire needs neither the guides nor the text; building or rebuilding the AI RMF
mapping, banks or evidence prompts, or the External AI questions, does (the agents read the safeguard text). The
External AI link from CSF to CIS comes from NIST's own references (`data/csf/crosswalks/olir_cis_v81.json`), not from
CIS's mapping spreadsheet.
