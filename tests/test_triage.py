"""Deterministic backend rules, unknown answers and precedence; fictional inputs only."""
import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from triage import RuleEngine


def rule_answers(rule):
    selected=rule['symptoms'][:]
    if rule.get('any_symptoms'): selected.append(rule['any_symptoms'][0])
    return {'symptoms':selected,'followups':dict(rule['followups']),
            'warnings':{**{w:'no' for w in RuleEngine().warnings},**rule['warnings']},
            'other_listed_absent':True,'duration':{'value':1,'unit':'hours'},
            'self_severity':rule.get('self_severity'),'additional':''}

class RuleTests(unittest.TestCase):
    def setUp(self): self.rules=RuleEngine()

    def test_each_supported_rule_and_explanation(self):
        levels=set()
        for r in self.rules.data['rules']:
            with self.subTest(rule=r['id']):
                result=self.rules.evaluate(rule_answers(r));levels.add(result['suggested_priority'])
                self.assertEqual(result['suggested_priority'],r['priority'])
                self.assertIn(r['explanation'],result['explanation'])
                self.assertIn(r['id'],result['rule_ids']);self.assertIn(r['source'],result['sources'])
                self.assertEqual(result['review_status'],'demonstration_only')
        self.assertEqual(levels,{1,2,3,4})

    def test_missing_unknown_or_unconfirmed_not_assumed_absent(self):
        self.assertEqual(self.rules.evaluate({})['suggested_priority'],3)
        normal=self.rules.data['rules'][-1]
        # Optional duration does not block a rule which has no duration condition.
        a=rule_answers(normal);del a['duration'];self.assertEqual(self.rules.evaluate(a)['suggested_priority'],4)
        for field in ['self_severity','warnings','followups','other_listed_absent']:
            a=rule_answers(normal);del a[field]
            result=self.rules.evaluate(a);self.assertEqual(result['suggested_priority'],3);self.assertTrue(result['fallback_used'])
        a=rule_answers(normal);a['warnings']['heavy_bleeding']='unsure'
        self.assertFalse(self.rules.evaluate(a)['complete'])
        a['duration']={'value':3,'unit':None};self.assertEqual(self.rules.validate(a)['duration']['value'],3)
        self.assertEqual(self.rules.evaluate({'symptoms':['cough']})['suggested_priority'],3)

    def test_invalid_answers_rejected(self):
        base=rule_answers(self.rules.data['rules'][-1])
        for field,value in [('symptoms',['unknown']),('symptoms',['nasal','nasal']),('followups',{'nasal.fever':'maybe'}),
                            ('followups',{'urinary.fever':'yes'}),('warnings',{'invented':'no'}),('duration',{'value':True,'unit':'hours'}),
                            ('self_severity',4),('additional','X'*1501),('other_listed_absent',1),('pain_level',True),('pain_level',11)]:
            a=copy.deepcopy(base);a[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError): self.rules.evaluate(a)

    def test_emergency_independent_of_missing_or_unmatched_answers(self):
        for warning in self.rules.warnings:
            result=self.rules.evaluate({'warnings':{warning:'yes'}})
            self.assertTrue(result['emergency']);self.assertTrue(result['warning_flags'])
            self.assertEqual(result['suggested_priority'],1);self.assertIn('immediate emergency',result['emergency_instruction'])
        result=self.rules.evaluate({'symptoms':['headache','cough'],'followups':{'headache.sudden':'yes'}})
        self.assertTrue(result['emergency']);self.assertEqual(result['suggested_priority'],1)
        self.assertEqual(result['winning_rule_ids'],['DEMO-C-HEAD'])

    def test_unmatched_ambiguous_unreviewed_and_free_text(self):
        a=rule_answers(self.rules.data['rules'][-1]);a['symptoms'].append('other')
        self.assertEqual(self.rules.evaluate(a)['suggested_priority'],3)
        a=rule_answers(self.rules.data['rules'][-1]);a['additional']='Also pain not in the checklist'
        result=self.rules.evaluate(a);self.assertEqual(result['suggested_priority'],3);self.assertTrue(result['uncertainty_flags'])
        duplicate=copy.deepcopy(self.rules.data['rules'][-1]);duplicate['id']='DEMO-DUP';duplicate['priority']=2
        self.rules.data['rules'].append(duplicate)
        result=self.rules.evaluate(rule_answers(duplicate));self.assertEqual(result['suggested_priority'],2)
        self.assertIn('DEMO-N4',result['rule_ids']);self.assertIn('DEMO-DUP',result['winning_rule_ids'])
        self.rules.data['rules'].pop();self.rules.data['rules'][-1]['review_status']='unreviewed'
        self.assertEqual(self.rules.evaluate(rule_answers(self.rules.data['rules'][-1]))['suggested_priority'],3)

    def test_duration_bounds_no_counts_or_weights(self):
        r=self.rules.data['rules'][-1];r['duration_hours']={'min':0,'max':72}
        a=rule_answers(r);a['duration']={'value':4,'unit':'days'}
        self.assertEqual(self.rules.evaluate(a)['suggested_priority'],3)
        a['duration']=None;self.assertEqual(self.rules.evaluate(a)['suggested_priority'],3)
        a['duration']={'value':72,'unit':'hours'};self.assertEqual(self.rules.evaluate(a)['suggested_priority'],4)
        self.assertTrue(all('weights' not in r for r in self.rules.data['rules']))

    def test_all_selected_symptoms_contribute_and_optional_values_do_not_block(self):
        result=self.rules.evaluate({'symptoms':['urinary','fever','back_pain','headache','other']})
        self.assertEqual(result['suggested_priority'],2);self.assertTrue(result['fallback_used'])
        self.assertIn('DEMO-U-URINARY',result['winning_rule_ids'])
        self.assertEqual(result['selected_symptoms'],['urinary','fever','back_pain','headache','other'])
        self.assertTrue(result['uncertainty_flags'])
        for answer in (None,'unsure','no'):
            a={'symptoms':['headache'],'followups':{'headache.sudden':answer}}
            result=self.rules.evaluate(a);self.assertEqual(result['suggested_priority'],3)
            self.assertNotIn('DEMO-C-HEAD',result['rule_ids'])
        self.assertEqual(self.rules.evaluate({'symptoms':['headache'],'followups':{'headache.sudden':'yes'}})['suggested_priority'],1)

    def test_catalog_categories_and_other(self):
        self.assertGreaterEqual(len(self.rules.symptoms),60)
        self.assertEqual(len({s['category'] for s in self.rules.symptoms.values()}),10)
        self.assertIn('other',self.rules.symptoms)
