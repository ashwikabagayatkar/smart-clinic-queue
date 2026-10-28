"""Transparent exact-condition demonstration rules, never a diagnosis or queue decision."""
import copy
import json
from pathlib import Path

DATA_PATH = Path(__file__).resolve().parents[1] / 'data' / 'symptoms.json'
LABELS = {1:'Critical', 2:'Urgent', 3:'Priority', 4:'Normal'}

class RuleEngine:
    def __init__(self, path=DATA_PATH):
        self.data = json.loads(Path(path).read_text(encoding='utf-8'))
        self.symptoms = {s['id']:s for s in self.data['symptoms']}
        self.warnings = {w['id']:w for w in self.data['warnings']}
        # Fail closed on an invalid or ambiguous dataset schema, not on patient answers.
        seen=set()
        for r in self.data['rules']:
            if (r['id'] in seen or type(r['priority']) is not int or r['priority'] not in LABELS
                    or not set(r['symptoms']) <= self.symptoms.keys() or not r['explanation'] or not r['source']):
                raise ValueError('Invalid demonstration rule dataset.')
            followups={sid+'.'+f['id'] for sid in r['symptoms'] for f in self.symptoms[sid]['followups']}
            if (set(r['followups'])!=followups or set(r['warnings'])!=set(self.warnings)
                    or any(v not in ('yes','no') for v in [*r['followups'].values(),*r['warnings'].values()])
                    or r['self_severity'] not in ('mild','moderate','severe')
                    or set(r['duration_hours'])!={'min','max'}
                    or any(type(v) is not int for v in r['duration_hours'].values())
                    or not 0<=r['duration_hours']['min']<=r['duration_hours']['max']):
                raise ValueError('Every demo rule must explicitly cover all relevant follow-ups and warning answers.')
            seen.add(r['id'])

    def validate(self, answers):
        if not isinstance(answers,dict) or set(answers)-{'symptoms','followups','warnings','other_listed_absent','duration','self_severity','additional'}:
            raise ValueError('Invalid assessment fields.')
        a=copy.deepcopy(answers)
        selected=a.get('symptoms',[])
        if (not isinstance(selected,list) or any(not isinstance(s,str) or s not in self.symptoms for s in selected)
                or len(selected)!=len(set(selected))):
            raise ValueError('Select only listed symptoms, without duplicates.')
        a['symptoms']=selected
        allowed={s['id']+'.'+f['id'] for s in self.data['symptoms'] if s['id'] in selected for f in s['followups']}
        for field,keys in [('followups',allowed),('warnings',set(self.warnings))]:
            values=a.get(field,{})
            if not isinstance(values,dict) or set(values)-keys or any(v not in ('yes','no','unsure',None) for v in values.values()):
                raise ValueError('Follow-up and warning answers must be yes, no or unsure, for the relevant questions.')
            a[field]=values
        if a.get('other_listed_absent') not in (True,False,None) or type(a.get('other_listed_absent')) not in (bool,type(None)):
            raise ValueError('Confirm the symptom checklist explicitly, or choose unsure.')
        if a.get('self_severity') not in ('mild','moderate','severe','unsure',None):
            raise ValueError('Choose a valid self-reported severity.')
        duration=a.get('duration')
        if duration is not None:
            if (not isinstance(duration,dict) or set(duration)!={'value','unit'} or (duration['value'] is not None and (type(duration['value']) is not int or not 0<=duration['value']<=3650))
                    or duration['unit'] not in ('hours','days','weeks',None)):
                raise ValueError('Duration must be a whole number from 0–3650 hours, days or weeks, or unknown.')
        additional=a.get('additional','')
        if not isinstance(additional,str) or len(additional)>1500 or any(ord(c)<32 and c not in '\n\t' for c in additional):
            raise ValueError('Additional symptoms must be text of at most 1500 characters, without control characters.')
        a['additional']=additional
        return a

    def evaluate(self, answers):
        a=self.validate(answers)
        flags=[w['label'] for w in self.data['warnings'] if a['warnings'].get(w['id'])=='yes']
        relevant=[]
        for sid in a['symptoms']:
            for f in self.symptoms[sid]['followups']:
                key=sid+'.'+f['id']; relevant.append(key)
                if f.get('emergency_when') and a['followups'].get(key)==f['emergency_when']:
                    flags.append(self.symptoms[sid]['label']+': '+f['label'])
        complete=(bool(a['symptoms']) and a.get('other_listed_absent') is True and (a.get('duration') is not None and a['duration']['value'] is not None and a['duration']['unit'] is not None)
                  and a.get('self_severity') in ('mild','moderate','severe')
                  and all(a['warnings'].get(w) in ('yes','no') for w in self.warnings)
                  and all(a['followups'].get(f) in ('yes','no') for f in relevant))
        matches=[]
        if complete and not a['additional'].strip():
            hours=a['duration']['value']*{'hours':1,'days':24,'weeks':168}[a['duration']['unit']]
            for r in self.data['rules']:
                if (r['review_status']=='demo_reviewed' and set(r['symptoms'])==set(a['symptoms'])
                        and all(a['followups'].get(k)==v for k,v in r['followups'].items())
                        and all(a['warnings'].get(k)==v for k,v in r['warnings'].items())
                        and r['self_severity']==a['self_severity']
                        and r['duration_hours']['min']<=hours<=r['duration_hours']['max']):
                    matches.append(r)
        rule=matches[0] if len(matches)==1 else None
        if rule and flags and rule['priority']!=1: rule=None
        if rule: explanation=rule['explanation']
        elif not complete: explanation='Some answers are missing or uncertain. Unanswered symptoms and warnings are not assumed absent.'
        elif a['additional'].strip(): explanation='Additional free-text symptoms require staff interpretation; they are not scored automatically.'
        elif len(matches)>1: explanation='More than one demonstration rule matches. This is ambiguous and requires staff assessment.'
        else: explanation='No software-reviewed demonstration rule covers this exact combination of answers. Staff must assess it.'
        return {'suggested_priority':rule['priority'] if rule else None,
                'label':LABELS[rule['priority']] if rule else 'Staff assessment required',
                'explanation':explanation,'warning_flags':flags,'emergency':bool(flags),
                'emergency_instruction':self.data['emergency_instruction'] if flags else '',
                'rule_ids':[r['id'] for r in matches], 'sources':[r['source'] for r in matches],
                'dataset_version':self.data['version'],'review_status':'demonstration_only','complete':complete}
