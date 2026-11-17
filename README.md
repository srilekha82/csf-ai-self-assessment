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

## What's in each folder

| Folder | What's in it |
|---|---|
| `scripts/` | The Python programs that do the work: intake, picking questions, writing the spreadsheet |
| `.claude/commands/` | The commands you run in Claude Code, such as `/generate-questions`. Each lists the scripts to run, in order. |
| `prompts/` | Instructions for the AI agents, used when they judge or write something a script can't decide |
| `data/` | The prepared content: the frameworks, the question banks, and the rules for tailoring. Split into `csf/`, `ai/` and `common/`. |
| `templates/` | The empty CSF and AI RMF profile spreadsheets (for Stage 2) |
| `runs/` | One folder per assessment: intake answers and the finished `questionnaire.xlsx`. Created when you run the tool. Holds your data, so it's never committed. |
| `tests/` | Checks for the scripts |
| `docs/` | The detailed documentation |

File by file: the "What is where" section of the [guide](docs/guide.md).

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
