# csf-ai-self-assessment

A self-assessment for cybersecurity and AI. From a short intake about your organisation, it builds one questionnaire
(`questionnaire.xlsx`) with two sheets: NIST CSF 2.0 and NIST AI RMF 1.0, tailored to your sector, your certifications
and how you use AI.

```
Stage 1: questionnaire  →  Stage 2: answers → maturity scores  →  Stage 3: reports
(done)                     (being designed)                        (later)
```

## Quick start

Needs Python 3 and [Claude Code](https://claude.com/claude-code). Or open the repo in GitHub Codespaces, which sets this up.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

Then, in Claude Code from the repo root:

```
/generate-questions
```

It asks the intake as numbered choices and writes `runs/<Org>_<date>/questionnaire.xlsx`. Send that to the people who
own the controls.

## Keep private

`runs/` holds your organisation's answers and is never committed (`.gitignore`).

## More

- [Docs home](docs/index.md): the idea, a small example, and where each part lives.
- [Guide](docs/guide.md): every command, script and data file, and a glossary.
- [Architecture](docs/architecture.md): how the stages fit together.
- [AI RMF model](docs/ai-rmf-model.md): AI areas, mapping, severity and the question banks.
- `CLAUDE.md`: short guide for Claude Code. `DESIGN_RULES.md`: read before changing code.

## Sources

This tool uses free, public material from:
- **NIST:** the Cybersecurity Framework (CSF) 2.0 and the AI Risk Management Framework (AI RMF) 1.0 Playbook.
- **CISA:** the cybersecurity questions, from its free assessment tool [CSET](https://github.com/cisagov/cset).
- **CIS (Center for Internet Security):** the ID numbers of its safeguards. CIS's own text is not included; its licence
  (CC BY-NC-ND 4.0) does not allow that.

NIST, CISA and CIS do not endorse this tool.
