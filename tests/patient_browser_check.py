"""Real separate patient/staff pages: self-assessment, warning, review and C queue."""
from pathlib import Path
import os
import shutil
import sys
import tempfile
import threading
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from server import create_server
from playwright.sync_api import sync_playwright, expect
ROOT=Path(__file__).resolve().parents[1]

def main():
    with tempfile.TemporaryDirectory() as temp:
        server=create_server(Path(temp)/'patient-browser.db',port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                exe=os.environ.get('CHROMIUM') or shutil.which('chromium')
                browser=p.chromium.launch(**({'executable_path':exe} if exe else {}))
                staff=browser.new_page(viewport={'width':1440,'height':1100})
                patient=browser.new_page(viewport={'width':390,'height':844})
                errors=[]
                for page in (staff,patient):page.on('pageerror',lambda e:errors.append(str(e)))
                base=f'http://127.0.0.1:{server.server_port}'
                staff.goto(base);expect(staff.locator('#staff-login')).to_be_visible()
                staff.locator('#staff-pin').fill(server.staff_pin);staff.locator('#staff-login-form button').click()
                expect(staff.locator('#connection')).to_have_text('Local engine connected')
                patient.goto(base+'/patient')
                patient.locator('input[name=identity-kind][value=new]').check()
                patient.locator('#patient-name').fill('Self Assessment Fictional');patient.locator('#patient-age').fill('29')
                patient.locator('#patient-next').click();expect(patient.locator('#step-1')).to_be_visible()
                patient.locator('#symptom-search').fill('nose');patient.locator('[data-symptom=nasal]').check()
                patient.locator('#symptom-search').fill('');expect(patient.locator('[data-symptom=nasal]')).to_be_checked()
                patient.locator('#other-absent').select_option('yes');patient.locator('#patient-next').click()
                expect(patient.locator('#step-2')).to_be_visible()
                for warning in server.assessments.rules.data['warnings']:
                    patient.locator(f'[data-question="{warning["id"]}"]').select_option('no')
                patient.locator('[data-question="nasal.fever"]').select_option('no')
                patient.locator('[data-question="nasal.breathing_normal"]').select_option('yes')
                patient.locator('#duration-value').fill('1');patient.locator('#duration-unit').select_option('days')
                patient.locator('#self-severity').select_option('mild');patient.locator('#patient-next').click()
                expect(patient.locator('#suggestion-preview')).to_contain_text('Normal')
                assert patient.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Patient mobile overflow'
                images=ROOT/'build'/'screenshots';images.mkdir(exist_ok=True)
                patient.screenshot(path=str(images/'patient-review-mobile.png'),full_page=True)
                patient.set_viewport_size({'width':1280,'height':1000})
                patient.screenshot(path=str(images/'patient-review-desktop.png'),full_page=True)
                patient.locator('#identity-confirmed').check();patient.locator('#patient-submit').click()
                expect(patient.locator('#patient-receipt')).to_be_visible()
                expect(patient.locator('#receipt-details')).to_contain_text('AS-')
                self_state=server.engine.call({'action':'state'})['state']
                assert self_state['patients'][0]['severity']==4 and len(self_state['queue'])==1
                expect(patient.locator('#receipt-calculation')).to_contain_text('How priority was calculated')
                expect(patient.locator('#receipt-calculation')).to_contain_text('DEMO-N4')
                staff.locator('nav [data-page=assessments]').click()
                expect(staff.locator('#assessment-inbox')).to_contain_text('Self Assessment Fictional',timeout=10000)
                staff.locator('[data-review-assessment]').first.click()
                expect(staff.locator('#assessment-review-details')).to_contain_text('Runny or blocked nose')
                staff.locator('#review-priority').select_option('4');staff.locator('#reviewer-name').fill('Demo Staff')
                staff.locator('#staff-confirmed').check();staff.locator('#assessment-review-form button[type=submit]').click()
                expect(staff.locator('#assessment-review-dialog')).not_to_be_visible()
                staff.locator('nav [data-page=queue]').click()
                expect(staff.locator('#live-queue')).to_contain_text('Self Assessment Fictional')
                # Existing registered patient gets a bound invitation, not a public ID lookup.
                staff.locator('[data-register]').click();staff.locator('#new-name').fill('Existing Emergency Fictional')
                staff.locator('#new-age').fill('35');staff.locator('input[name=severity][value="3"]').check()
                staff.locator('#add-to-queue').uncheck();staff.locator('#registration-form button[type=submit]').click()
                expect(staff.locator('#registration-dialog')).not_to_be_visible()
                staff.locator('nav [data-page=patients]').click();staff.locator('[data-invite="2"]').click()
                expect(staff.locator('#invitation-dialog')).to_be_visible()
                link=staff.locator('#invitation-link').get_attribute('href')
                staff.locator('#invitation-dialog [data-close]').click()
                patient.goto(base+link);patient.locator('#patient-next').click()
                expect(patient.locator('#step-1')).to_be_visible();patient.locator('#symptom-search').fill('headache');patient.locator('[data-symptom=headache]').check()
                patient.locator('#symptom-search').fill('Other symptoms');patient.locator('[data-symptom=other]').check()
                patient.locator('#patient-next').click();expect(patient.locator('#step-2')).to_be_visible()
                patient.locator('[data-question="headache.sudden"]').select_option('yes')
                expect(patient.locator('#patient-emergency')).to_be_visible()
                expect(patient.locator('#patient-emergency')).to_contain_text('immediate emergency')
                patient.locator('#additional-symptoms').fill('<script>not executed</script>')
                patient.locator('#patient-next').click();expect(patient.locator('#suggestion-preview')).to_contain_text('Critical')
                patient.locator('#identity-confirmed').check();patient.locator('#patient-submit').click()
                expect(patient.locator('#patient-receipt')).to_be_visible();expect(patient.locator('#receipt-warning')).to_be_visible()
                expect(staff.locator('#assessment-alert')).to_be_visible(timeout=10000)
                staff.locator('nav [data-page=assessments]').click();staff.locator('[data-review-assessment]').first.click()
                expect(staff.locator('#assessment-review-details')).to_contain_text('Unanswered')
                staff.locator('#review-priority').select_option('2');staff.locator('#reviewer-name').fill('Demo Staff')
                staff.locator('#staff-confirmed').check();staff.locator('#assessment-review-form button[type=submit]').click()
                expect(staff.locator('#review-error')).to_contain_text('Explain')
                staff.locator('#review-priority').select_option('1');staff.locator('#override-reason').fill('Staff assessed warning; arranged immediate assistance')
                staff.locator('#assessment-review-form button[type=submit]').click()
                expect(staff.locator('#assessment-review-dialog')).not_to_be_visible()
                staff.locator('nav [data-page=queue]').click()
                expect(staff.locator('#live-queue .patient-name')).to_have_text(['Existing Emergency Fictional','Self Assessment Fictional'])
                # Optional unanswered fields still produce a persisted provisional queue entry.
                patient.locator('#another-assessment').click()
                patient.locator('input[name=identity-kind][value=new]').check()
                patient.locator('#patient-name').fill('Fallback Fictional');patient.locator('#patient-age').fill('22')
                patient.locator('#patient-next').click();patient.locator('#patient-next').click();patient.locator('#patient-next').click()
                expect(patient.locator('#suggestion-preview')).to_contain_text('Priority')
                expect(patient.locator('#suggestion-preview')).to_contain_text('low')
                patient.locator('#identity-confirmed').check();patient.locator('#patient-submit').click()
                expect(patient.locator('#receipt-calculation')).to_contain_text('Priority (3) fallback')
                assert len(server.engine.call({'action':'state'})['state']['queue'])==3
                assert not errors,errors
                browser.close()
                print('PASS: separate patient/staff pages, searchable checklist, follow-ups, review, reference, staff authentication, bound invitation, emergency alert, override validation, C queue and responsive layouts')
        finally:
            server.shutdown();thread.join(timeout=5);server.server_close();server.engine.close()

if __name__=='__main__':main()
