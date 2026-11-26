"""Run: .venv/bin/python -m unittest discover -s tests -v

Priority (High / Medium / Low) per AI RMF subcategory from the AI system inventory (scripts/ai_priority.py,
data/ai/severity_rules.json). Pure functions; nothing is written."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_fixture  # noqa: E402,F401  (the frozen AI data: tests/fixtures/ai/)
import ai_priority as AP  # noqa: E402

FIN, REP, HARM = "Financial loss if it gets things wrong", "Reputational damage if it gets things wrong", \
    "Possible harm to people"


def system(name, areas, fin="Under USD 100k", rep="None", harm="No"):
    return {"name": name, "areas": areas, FIN: fin, REP: rep, HARM: harm}


# A small mapping: MAP 1.4 reached by internal_process and by customer_facing; MAP 3.3 by customer_facing; MEASURE
# 2.11 by an area with a people impact. A row carries its area's impacts.
CTX = {"foundation": ["MAP 1.5"], "rows": {
    "MAP 1.4": {"internal_process:MAP 1.4": {"area": "internal_process", "impact": ["process"]},
                "customer_facing:MAP 1.4": {"area": "customer_facing", "impact": ["process"]}},
    "MAP 3.3": {"customer_facing:MAP 3.3": {"area": "customer_facing", "impact": ["process"]}},
    "MEASURE 2.11": {"customer_facing:MEASURE 2.11": {"area": "customer_facing", "impact": ["people"]}},
}}


class Priority(unittest.TestCase):
    def setUp(self):
        self.rules = AP.load_rules()

    def test_a_system_takes_its_worst_band_and_a_blank_counts_high(self):
        lvl = lambda **kw: AP.system_level(system("s", [], **kw), self.rules)  # noqa: E731
        self.assertEqual(lvl(), "Low")
        self.assertEqual(lvl(rep="Local"), "Medium")
        self.assertEqual(lvl(fin="Over USD 500k"), "High")
        self.assertEqual(lvl(harm="Yes"), "High")
        self.assertEqual(lvl(fin=""), "High")

    def priorities(self, systems, sector="finance", areas=("internal_process", "customer_facing")):
        subs = ["GOVERN 1.1", "MAP 1.5", "MAP 1.4", "MAP 3.3", "MEASURE 2.11", "MEASURE 2.6"]
        return AP.subcategory_priorities(subs, systems, sector, areas, CTX, self.rules)

    def test_areas_take_their_systems_and_foundation_takes_the_whole_organisation(self):
        got = self.priorities([system("HR screening", ["internal_process"], rep="Local"),
                               system("Chatbot", ["customer_facing"])])
        self.assertEqual(got["GOVERN 1.1"], "Medium")      # organisation-wide: the highest system
        self.assertEqual(got["MAP 1.5"], "Medium")
        self.assertEqual(got["MAP 3.3"], "Low")            # only the chatbot uses customer_facing
        self.assertEqual(got["MAP 1.4"], "Medium")         # two areas' rows (HR screening, chatbot): the highest
        self.assertEqual(got["MEASURE 2.11"], "Low")
        self.assertEqual(got["MEASURE 2.6"], "High")       # no row reaches it for this client: unknown counts high

    def test_an_area_no_system_is_marked_with_and_no_inventory_count_high(self):
        got = self.priorities([system("HR screening", ["internal_process"])])
        self.assertEqual((got["MAP 1.4"], got["MAP 3.3"]), ("High", "High"))
        self.assertEqual(set(self.priorities([]).values()), {"High"})

    def test_the_sector_floor_raises_people_rows_and_safety(self):
        systems = [system("HR screening", ["internal_process"]), system("Chatbot", ["customer_facing"])]
        fin, hc = self.priorities(systems), self.priorities(systems, sector="healthcare")
        self.assertEqual((fin["MEASURE 2.11"], hc["MEASURE 2.11"]), ("Low", "High"))
        self.assertEqual(hc["MEASURE 2.6"], "High")
        self.assertEqual((fin["MAP 3.3"], hc["MAP 3.3"]), ("Low", "Low"))   # a process row stays as it was

    def test_the_accepted_mapping_gives_every_questionnaire_subcategory_a_level(self):
        from ai_bank_modules import R  # noqa: E402
        ctx = R.question_context(R.load_inputs())
        subs = sorted(set(ctx["rows"]) | set(ctx["foundation"]))
        got = AP.subcategory_priorities(subs, [system("Chatbot", ["customer_facing", "output"], rep="Local")],
                                        "finance", ["customer_facing", "output"], ctx, self.rules)
        self.assertEqual(set(got), set(subs))
        self.assertTrue(set(got.values()) <= {"Low", "Medium", "High"})


if __name__ == "__main__":
    unittest.main()
