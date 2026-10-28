import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from triage import RuleEngine


def rule_answers(rule):
    return {'symptoms':rule['symptoms'][:],'followups':dict(rule['followups']),'warnings':dict(rule['warnings']),
            'other_listed_absent':True,'duration':{'value':1,'unit':'hours'},'self_severity':rule['self_severity'],'additional':''}

class RuleTests(unittest.TestCase):
    def setUp(self): self.rules=RuleEngine()

    def test_each_supported_rule_and_explanation(self):
        for r in self.rules.data['rules']:
            with self.subTest(rule=r['id']):
                result=self.rules.evaluate(rule_answers(r))
                self.assertEqual(result['suggested_priority'],r['priority'])
                self.assertEqual(result['explanation'],r['explanation'])
                self.assertEqual(result['rule_ids'],[r['id']]);self.assertEqual(result['sources'],[r['source']])
                self.assertEqual(result['review_status'],'demonstration_only')

    def test_missing_unknown_or_unconfirmed_not_assumed_absent(self):
        self.assertEqual(self.rules.evaluate({})['label'],'Staff assessment required')
        r=self.rules.data['rules'][-1]
        for field in ['duration','self_severity','warnings','followups','other_listed_absent']:
            a=rule_answers(r);del a[field]
            self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])
        a=rule_answers(r);a['warnings']['heavy_bleeding']='unsure'
        self.assertFalse(self.rules.evaluate(a)['complete'])
        a=rule_answers(r);a['duration']={'value':3,'unit':None}
        self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])
        self.assertEqual(self.rules.validate(a)['duration']['value'],3)
        a=rule_answers(r);a['other_listed_absent']=False
        self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])

    def test_invalid_answers_rejected(self):
        base=rule_answers(self.rules.data['rules'][-1])
        for field,value in [('symptoms',['unknown']),('symptoms',['nasal','nasal']),('followups',{'nasal.fever':'maybe'}),
                            ('followups',{'urinary.fever':'yes'}),('warnings',{'invented':'no'}),('duration',{'value':True,'unit':'hours'}),
                            ('self_severity',4),('additional','X'*1501),('other_listed_absent',1)]:
            a=copy.deepcopy(base);a[field]=value
            with self.subTest(field=field,value=value),self.assertRaises(ValueError): self.rules.evaluate(a)

    def test_emergency_independent_of_missing_or_unmatched_answers(self):
        for warning in self.rules.warnings:
            result=self.rules.evaluate({'warnings':{warning:'yes'}})
            self.assertTrue(result['emergency']);self.assertTrue(result['warning_flags'])
            self.assertIsNone(result['suggested_priority']);self.assertIn('immediate emergency',result['emergency_instruction'])
        result=self.rules.evaluate({'symptoms':['headache'],'followups':{'headache.sudden':'yes'}})
        self.assertTrue(result['emergency'])
        result=self.rules.evaluate(rule_answers(self.rules.data['rules'][0]))
        self.assertEqual(result['suggested_priority'],1);self.assertTrue(result['emergency'])

    def test_unmatched_ambiguous_unreviewed_and_free_text(self):
        a=rule_answers(self.rules.data['rules'][-1]);a['symptoms'].append('other')
        self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])
        a=rule_answers(self.rules.data['rules'][-1]);a['additional']='Also pain not in the checklist'
        self.assertIn('free-text',self.rules.evaluate(a)['explanation'])
        a=rule_answers(self.rules.data['rules'][-1]);duplicate=copy.deepcopy(self.rules.data['rules'][-1]);duplicate['id']='DEMO-DUP'
        self.rules.data['rules'].append(duplicate)
        result=self.rules.evaluate(a);self.assertIsNone(result['suggested_priority']);self.assertIn('ambiguous',result['explanation'])
        self.rules.data['rules'].pop();self.rules.data['rules'][-1]['review_status']='unreviewed'
        self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])

    def test_duration_bounds_no_counts_or_weights(self):
        a=rule_answers(self.rules.data['rules'][-1]);a['duration']={'value':4,'unit':'days'}
        self.assertIsNone(self.rules.evaluate(a)['suggested_priority'])
        self.assertTrue(all('weights' not in r for r in self.rules.data['rules']))
