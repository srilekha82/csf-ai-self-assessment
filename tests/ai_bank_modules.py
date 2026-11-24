"""The AI RMF bank code as one object for the tests: record_bank.py and the modules it uses (ai_mapping,
ai_questions, ai_external, ai_notes).

Reading a name finds it in whichever module has it. Setting a name (a test pointing a store at a temp folder) sets it
in every one of those modules that has it, so no module goes on reading or writing the real file.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ai_bank_common  # noqa: E402
import ai_external  # noqa: E402
import ai_mapping  # noqa: E402
import ai_notes  # noqa: E402
import ai_questions  # noqa: E402
import record_bank  # noqa: E402

_SPLIT = (record_bank, ai_mapping, ai_questions, ai_external, ai_notes)


class _AIBank:
    def __getattr__(self, name):
        for m in (*_SPLIT, ai_bank_common):
            if hasattr(m, name):
                return getattr(m, name)
        raise AttributeError(name)

    def __setattr__(self, name, value):
        hits = [m for m in _SPLIT if hasattr(m, name)]
        if not hits:
            raise AttributeError(f"no AI bank module has {name}")
        for m in hits:
            setattr(m, name, value)


R = _AIBank()
