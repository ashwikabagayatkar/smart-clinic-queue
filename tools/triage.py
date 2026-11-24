"""Backend demonstration rule engine; priorities feed the real C queue, never a diagnosis."""
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
        # Conditions mention only the answers genuinely needed by a rule.
        if len(self.symptoms)!=len(self.data['symptoms']) or len(self.warnings)!=len(self.data['warnings']):
            raise ValueError('Duplicate symptom or warning ID.')
        fallback=self.data['fallback']
        if type(fallback['priority']) is not int or fallback['priority']!=3 or not fallback['explanation']:
            raise ValueError('The provisional insufficient-information fallback must be Priority (3).')
        seen=set()
        for r in self.data['rules']:
            if (r['id'] in seen or type(r['priority']) is not int or r['priority'] not in LABELS
                    or not set(r['symptoms']+r.get('any_symptoms',[])) <= self.symptoms.keys()
                    or not r['explanation'] or not r['source']
                    or not (r['symptoms'] or r.get('any_symptoms') or r['warnings'])
                    or r.get('emergency',False) and r['priority']!=1):
                raise ValueError('Invalid demonstration rule dataset.')
            followups={sid+'.'+f['id'] for sid in r['symptoms']+r.get('any_symptoms',[]) for f in self.symptoms[sid]['followups']}
            if (not set(r['followups'])<=followups or not set(r['warnings'])<=self.warnings.keys()
                    or any(v not in ('yes','no') for v in [*r['followups'].values(),*r['warnings'].values()])
                    or r.get('self_severity') not in (None,'mild','moderate','severe')):
                raise ValueError('Invalid rule conditions.')
            if 'duration_hours' in r:
                bounds=r['duration_hours']
                if set(bounds)!={'min','max'} or any(type(v) is not int for v in bounds.values()) or not 0<=bounds['min']<=bounds['max']:
                    raise ValueError('Invalid duration condition.')
            for key in ('emergency','exact_symptoms','requires_checklist_confirmation'):
                if key in r and type(r[key]) is not bool: raise ValueError('Invalid boolean rule condition.')
            seen.add(r['id'])

    def validate(self, answers):
        if not isinstance(answers,dict) or set(answers)-{'symptoms','followups','warnings','other_listed_absent','duration','self_severity','additional','pain_level'}:
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
        pain=a.get('pain_level')
        if pain is not None and (type(pain) is not int or not 0<=pain<=10):
            raise ValueError('Pain level must be 0–10 or unanswered.')
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
        missing=[w for w in self.warnings if a['warnings'].get(w) not in ('yes','no')]
        missing += [f for f in relevant if a['followups'].get(f) not in ('yes','no')]
        matches=[]; selected=set(a['symptoms'])
        for r in sorted(self.data['rules'],key=lambda rule:(not rule.get('emergency',False),rule['priority'],rule['id'])):
            if r['review_status']!='demo_reviewed': continue
            required=set(r['symptoms']); any_of=set(r.get('any_symptoms',[]))
            if not required<=selected or (any_of and not any_of&selected): continue
            if r.get('exact_symptoms') and selected!=required: continue
            if not all(a['followups'].get(k)==v for k,v in r['followups'].items()): continue
            if not all(a['warnings'].get(k)==v for k,v in r['warnings'].items()): continue
            if r.get('self_severity') and a.get('self_severity')!=r['self_severity']: continue
            if r.get('requires_checklist_confirmation') and a.get('other_listed_absent') is not True: continue
            if 'duration_hours' in r:
                d=a.get('duration')
                if not d or d['value'] is None or d['unit'] is None: continue
                hours=d['value']*{'hours':1,'days':24,'weeks':168}[d['unit']]
                if not r['duration_hours']['min']<=hours<=r['duration_hours']['max']: continue
            matches.append(r)
        matches.sort(key=lambda r:(not r.get('emergency',False),r['priority'],r['id']))
        covered=set().union(*(set(r['symptoms']) | (set(r.get('any_symptoms',[]))&selected) for r in matches)) if matches else set()
        unmatched=sorted(selected-covered)
        uncertainty=[]
        if missing: uncertainty.append('Unanswered or uncertain warning/follow-up answers remain unknown.')
        if not selected: uncertainty.append('No symptom selection was provided.')
        if unmatched: uncertainty.append('No specific rule covers: '+', '.join(self.symptoms[s]['label'] for s in unmatched)+'.')
        if a['additional'].strip(): uncertainty.append('Other symptom text has not been interpreted by the rule engine.')
        fallback=not matches or bool(unmatched) or bool(a['additional'].strip())
        candidates=[r['priority'] for r in matches]+([3] if fallback else [])
        priority=min(candidates)
        winning=[r for r in matches if r['priority']==priority]
        explanation=' '.join(r['explanation'] for r in winning)
        if fallback and priority==3: explanation=(explanation+' '+self.data['fallback']['explanation']).strip()
        if len({r['priority'] for r in matches})>1:
            uncertainty.append('Multiple priority rules matched; the highest urgency was selected.')
        for r in matches:
            if r.get('emergency') and r['explanation'] not in flags: flags.append(r['explanation'])
        return {'suggested_priority':priority,'label':LABELS[priority],
                'explanation':explanation,'warning_flags':flags,'emergency':bool(flags),
                'emergency_instruction':self.data['emergency_instruction'] if flags else '',
                'rule_ids':[r['id'] for r in matches], 'winning_rule_ids':[r['id'] for r in winning],
                'sources':[r['source'] for r in matches], 'selected_symptoms':a['symptoms'],
                'uncertainty_flags':uncertainty,'fallback_used':fallback,'confidence':'low' if fallback or missing else 'demonstration_only',
                'dataset_version':self.data['version'],'review_status':'demonstration_only',
                'complete':not missing and bool(selected),'preliminary':True}
