"""Browser regression for the integrated presentation over the real engine.

Use the existing project environment and installed Chrome. This script neither
starts servers nor installs packages nor regenerates the historical study.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
from urllib.parse import urlparse

import numpy as np
from playwright.sync_api import expect, sync_playwright
from sklearn.metrics import accuracy_score, balanced_accuracy_score, confusion_matrix, f1_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DIAGNOSIS = 'Hay contaminación en uno de los mecanismos investigados'
ACTION = 'Retirar del modelo la variable que no existe al predecir'
PROOF = 'Momento de disponibilidad de las variables'


def verify_predictions(value):
    actual, predicted = value['y_true'], value['y_pred']
    expected = {'accuracy': accuracy_score(actual,predicted),
                'balanced_accuracy': balanced_accuracy_score(actual,predicted),
                'f1': f1_score(actual,predicted,zero_division=0)}
    assert value['metrics'] == expected, (value['metrics'],expected)
    assert value['confusion_matrix'] == confusion_matrix(actual,predicted,labels=[0,1]).tolist()


def assert_public(value):
    forbidden={'solution','explanation','expected','correct_option','_source','_source_case','_variant','fit_scope','leakage_detected','generator_params'}
    if isinstance(value,dict):
        assert not forbidden.intersection(value), forbidden.intersection(value)
        for item in value.values():
            assert_public(item)
    elif isinstance(value,list):
        for item in value:
            assert_public(item)


def assert_box(trace, values):
    """Check browser-supplied points and explicit pandas-linear quartiles."""
    assert len(trace['y'])==len(values)
    for actual,expected in zip(trace['y'],values):
        np.testing.assert_allclose(actual,expected,rtol=0,atol=0)
    for field,p in [('q1',.25),('median',.5),('q3',.75)]:
        np.testing.assert_allclose(trace[field],[np.quantile(v,p,method='linear') for v in values],rtol=0,atol=1e-14)
    np.testing.assert_allclose(trace['lowerfence'],[min(v) for v in values])
    np.testing.assert_allclose(trace['upperfence'],[max(v) for v in values])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='http://127.0.0.1:8503')
    parser.add_argument('--output-dir',type=Path,default=ROOT/'artifacts/visual-integration-20261029/browser')
    parser.add_argument('--screenshots-dir',type=Path,default=ROOT/'docs/screenshots/visual-integration-20261029')
    args=parser.parse_args()
    if urlparse(args.url).hostname not in {'127.0.0.1','localhost'}:
        parser.error('Only loopback URLs are supported.')
    args.output_dir.mkdir(parents=True,exist_ok=True)
    args.screenshots_dir.mkdir(parents=True,exist_ok=True)
    report={'url':args.url,'at':datetime.now(timezone.utc).isoformat(),'checks':[], 'page_errors':[], 'console_errors':[], 'external_attempts':[], 'requests':[], 'websockets':[], 'screenshots':[], 'limits':[], 'native_alerts':[]}
    browser=None
    def record(label,detail=None):
        report['checks'].append({'check':label,'result':'pass','detail':detail})
        print('PASS',label,flush=True)

    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path=shutil.which('google-chrome') or shutil.which('chromium'),headless=True)
            context=browser.new_context(viewport={'width':1440,'height':1000},device_scale_factor=1,accept_downloads=True)
            def local_only(route):
                if urlparse(route.request.url).hostname in {'127.0.0.1','localhost'}:
                    route.continue_()
                else:
                    report['external_attempts'].append(route.request.url)
                    route.abort()
            context.route('**/*',local_only)
            context.on('request',lambda request:report['requests'].append({'url':request.url,'type':request.resource_type}))
            page=context.new_page()
            page.set_default_timeout(30000)
            expect.set_options(timeout=30000)
            page.on('pageerror',lambda err:report['page_errors'].append(str(err)))
            page.on('console',lambda msg:report['console_errors'].append(msg.text) if msg.type=='error' else None)
            page.on('websocket',lambda ws:report['websockets'].append(ws.url))
            assert page.goto(args.url).status==200

            def settle():
                page.wait_for_timeout(300)
                expect(page.get_by_test_id('stApp')).to_have_attribute('data-test-script-state','notRunning')
                assert page.get_by_test_id('stException').count()==0, page.get_by_test_id('stException').all_text_contents()

            def sidebar_open():
                page.wait_for_timeout(350)  # Let the native responsive sidebar settle after resize.
                side=page.get_by_test_id('stSidebar')
                if side.get_attribute('data-collapsed')=='true':
                    page.get_by_role('button',name='Expand sidebar',exact=True).click()
                expect(side).to_be_visible()

            def sidebar_close():
                page.wait_for_timeout(350)
                side=page.get_by_test_id('stSidebar')
                if side.get_attribute('data-collapsed')!='true':
                    page.get_by_role('button',name='Collapse sidebar',exact=True).click()
                    page.wait_for_function("document.querySelector('[data-testid=stSidebar]').getBoundingClientRect().right<=0")

            def mode(label):
                sidebar_open()
                page.get_by_test_id('stSidebar').get_by_text(label,exact=True).click()
                settle()
                if page.viewport_size['width']<1000:
                    sidebar_close()

            def choose(label,option):
                control=page.get_by_role('combobox',name=label,exact=True)
                control.click()
                control.press('ArrowDown')
                page.get_by_role('option',name=option,exact=True).click()
                settle()

            def download(label,filename):
                settle()
                with page.expect_download() as received:
                    page.get_by_role('button',name=label,exact=True).click()
                file=args.output_dir/filename
                received.value.save_as(file)
                return json.loads(file.read_text())

            def screenshot(name):
                path=args.screenshots_dir/name
                page.screenshot(path=str(path))
                report['screenshots'].append(str(path))

            def native_alert_contrast(stage):
                expect(page.locator('[data-testid="stAlert"] p:visible').first).to_be_visible()
                samples=page.locator('[data-testid="stAlert"] p').evaluate_all("""elements=>{
                  const rgba=s=>(s.match(/[\\d.]+/g)||[]).map(Number);
                  const blend=(f,b)=>{const a=f.length>3?f[3]:1;return f.slice(0,3).map((v,i)=>v*a+b[i]*(1-a));};
                  const bg=e=>{if(!e)return [255,255,255];const c=rgba(getComputedStyle(e).backgroundColor);return blend(c,bg(e.parentElement));};
                  const luminance=c=>{const a=c.map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;});return a[0]*.2126+a[1]*.7152+a[2]*.0722;};
                  return elements.filter(e=>e.checkVisibility()).map(e=>{const background=bg(e);const color=getComputedStyle(e).color;const foreground=blend(rgba(color),background);const l=[luminance(foreground),luminance(background)].sort((a,b)=>b-a);let ancestor=e;while(ancestor && rgba(getComputedStyle(ancestor).backgroundColor)[3]===0)ancestor=ancestor.parentElement;return {text:e.textContent,color,background,backgroundSource:ancestor?getComputedStyle(ancestor).backgroundColor:null,ratio:(l[0]+.05)/(l[1]+.05)};});
                }""")
                assert samples, f'No visible native alert paragraphs at {stage}'
                for sample in samples:
                    sample['stage']=stage
                    assert sample['ratio']>=4.5, sample
                report['native_alerts'].extend(samples)
                record('Native alert contrast >=4.5:1 · '+stage,{'samples':len(samples),'minimum_ratio':min(s['ratio'] for s in samples)})

            def no_overflow():
                data=page.evaluate("""()=>({width:innerWidth,scroll:document.documentElement.scrollWidth,charts:[...document.querySelectorAll('[data-testid=stPlotlyChart]')].filter(e=>e.checkVisibility()).map(e=>({client:e.clientWidth,scroll:e.scrollWidth,right:e.getBoundingClientRect().right})),tables:[...document.querySelectorAll('[data-testid=stDataFrame]')].map(e=>({client:e.clientWidth,right:e.getBoundingClientRect().right,visible:e.checkVisibility(),closedExpander:!!e.closest('details:not([open])')}))})""")
                (args.output_dir/'latest-overflow-measurement.json').write_text(json.dumps(data,indent=2))
                assert data['scroll']<=data['width']+1,data
                for chart in data['charts']:
                    assert chart['scroll']<=chart['client']+1,chart
                    assert chart['right']<=data['width']+1,chart
                for table in data['tables']:
                    if table['visible']:
                        assert table['right']<=data['width']+1,data
                return data

            def responsive(slug,heading,chart=False):
                checks=[]
                for width in (1440,768,390):
                    page.set_viewport_size({'width':width,'height':1000 if width>390 else 844})
                    if width<1000:
                        sidebar_close()
                    page.get_by_role('heading',name=heading,exact=True).scroll_into_view_if_needed()
                    settle()
                    checks.append(no_overflow())
                    screenshot(f'{slug}-{width}.png')
                    if chart:
                        charts=page.get_by_test_id('stPlotlyChart')
                        for i,element in enumerate(charts.all()):
                            element.scroll_into_view_if_needed()
                            name=f'{slug}-chart-{i+1}-{width}.png'
                            element.screenshot(path=str(args.screenshots_dir/name))
                            report['screenshots'].append(str(args.screenshots_dir/name))
                page.set_viewport_size({'width':1440,'height':1000})
                sidebar_open()
                record(slug+' at 1440/768/390, no page/chart overflow',checks)

            # Guided mode: actual compute, explicit reveal, actual report.
            expect(page.get_by_role('heading',name='Data Crime Scene',exact=True)).to_be_visible()
            settle()
            native_alert_contrast('guided-initial')
            screenshot('01-guided-initial-1440.png')
            page.get_by_role('button',name='Ejecutar experimento',exact=True).click()
            expect(page.get_by_role('button',name='Revelar explicación y comparar',exact=True)).to_be_visible()
            page.get_by_role('button',name='Revelar explicación y comparar',exact=True).click()
            guided=download('↓ Descargar informe completo · JSON','guided.json')
            for variant in guided['variants'].values():
                verify_predictions(variant)
            expect(page.get_by_test_id('stPlotlyChart')).to_have_count(1)
            page.wait_for_function("document.querySelector('.js-plotly-plot')?.data?.length===2")
            guided_chart=page.locator('.js-plotly-plot').evaluate('(e)=>({data:e.data.map(t=>({x:t.x,y:t.y})),range:e.layout.yaxis.range,frames:e._transitionData._frames.length})')
            for trace,key in zip(guided_chart['data'],('incorrect','correct')):
                assert trace['x']==['Accuracy','Balanced accuracy','F1 · clase positiva'],trace['x']
                np.testing.assert_allclose(trace['y'],[guided['variants'][key]['metrics'][m] for m in ('accuracy','balanced_accuracy','f1')],rtol=0,atol=0)
            assert guided_chart['range']==[0,1.15] and guided_chart['frames']==0,guided_chart
            record('Guided real predictions/export and rendered chart integrity',guided_chart)
            native_alert_contrast('guided-complete')
            responsive('02-guided-comparison','Data Crime Scene',chart=True)

            # Lab: run only a single real config; load the pre-existing study.
            mode('Laboratorio')
            choose('Caso de laboratorio','El mismo sospechoso en ambos lados')
            page.get_by_role('button',name='Ejecutar configuración',exact=True).click()
            lab=download('↓ Descargar ejecución puntual · JSON','laboratory-current.json')
            assert lab['config']['case_id']=='groups'
            for variant in list(lab['variants'].values())+list(lab['cohort'].values()):
                verify_predictions(variant)
            record('Laboratory single-run real predictions and export')
            path=page.get_by_role('textbox',name='Archivo local del estudio',exact=True)
            path.fill('artifacts/visual-integration-20261029/nonexistent-study.json')
            path.press('Tab')
            settle()
            page.get_by_role('button',name='Cargar estudio local',exact=True).click()
            expect(page.get_by_text('No se ha cargado el estudio:',exact=False)).to_be_visible()
            settle()
            native_alert_contrast('laboratory-error')
            screenshot('03-laboratory-load-error.png')
            record('Laboratory real missing-file error without fake evaluation')
            path.fill('artifacts/laboratory-study.json')
            path.press('Tab')
            settle()
            if (ROOT/'artifacts/laboratory-study.json').exists():
                page.get_by_role('button',name='Cargar estudio local',exact=True).click()
                expect(page.get_by_role('heading',name='Estudio cargado · resultados calculados anteriormente',exact=True)).to_be_visible()
                study=download('↓ Descargar estudio cargado completo · JSON','laboratory-study-export.json')
                assert study==json.loads((ROOT/'artifacts/laboratory-study.json').read_text())
                expect(page.get_by_test_id('stPlotlyChart')).to_have_count(3)
                page.wait_for_function("document.querySelectorAll('.js-plotly-plot').length===3 && [...document.querySelectorAll('.js-plotly-plot')].every(e=>e.data?.length)")
                plots=page.locator('.js-plotly-plot').evaluate_all("els=>els.map(e=>({data:e.data.map(t=>({name:t.name,x:t.x,y:t.y,q1:t.q1,median:t.median,q3:t.q3,lowerfence:t.lowerfence,upperfence:t.upperfence})),range:e.layout.yaxis.range,frames:e._transitionData._frames.length}))")
                entries=[e for e in study['entries'] if e['status']=='ok' and e['config']['case_id']=='groups']
                levels=list(dict.fromkeys(e['config']['level'] for e in entries))
                for plot,source in zip(plots[:2],('variants','cohort')):
                    assert plot['range']==[-.03,1.04],plot['range']
                    for trace,key in zip(plot['data'],('incorrect','correct')):
                        assert trace['x']==[str(level) for level in levels]
                        values=[[e['result'][source][key]['metrics']['balanced_accuracy'] for e in entries if e['config']['level']==level] for level in levels]
                        assert_box(trace,values)
                for e in entries:
                    a,b=e['result']['cohort']['incorrect'],e['result']['cohort']['correct']
                    assert a['row_ids']==b['row_ids'] and a['y_true']==b['y_true']
                differences=[[e['result']['cohort']['incorrect']['metrics']['balanced_accuracy']-e['result']['cohort']['correct']['metrics']['balanced_accuracy'] for e in entries if e['config']['level']==level] for level in levels]
                assert_box(plots[2]['data'][0],differences)
                assert all(p['frames']==0 for p in plots)
                expect(page.get_by_text('La comparación interna por filas frente a grupos no está emparejada.',exact=False)).to_be_visible()
                record('Historical study unchanged, rendered values/quartiles/min-max and cohort-only pairing',{'levels':levels,'common_ranges':[p['range'] for p in plots[:2]],'traces':[len(p['data']) for p in plots]})
            else:
                report['limits'].append('No historical study existed: no regeneration performed.')
            responsive('04-laboratory','Laboratorio',chart=True)

            # Detective: public evidence has no solution, then real answer/actions.
            mode('Modo Detective')
            expect(page.get_by_role('heading',name='Modo Detective',exact=True)).to_be_visible()
            assert page.get_by_role('button',name='↓ Descargar evidencia disponible · JSON',exact=True).count()==0
            choose('Expediente de la sesión','La mesa norte')
            page.get_by_role('button',name='Abrir expediente',exact=True).click()
            expect(page.get_by_role('heading',name='01 · Panel de pruebas',exact=True)).to_be_visible()
            public=download('↓ Descargar evidencia disponible · JSON','detective-public.json')
            assert public['template_id']=='d01'
            assert_public(public)
            assert 'reembolso_tramitado' not in json.dumps(public)
            verify_predictions(public['experiment'])
            assert page.get_by_text('Diagnóstico del expediente:',exact=False).count()==0
            record('Detective d01 public evidence real, no solution/spoiler leakage')
            responsive('05-detective-public','Modo Detective')

            # Real native evidence expander, keyboard and long free-text notes.
            header=page.get_by_test_id('stExpander').filter(has_text='Índices, modelo y trazabilidad de la evaluación').locator('summary')
            header.focus()
            header.press('Enter')
            settle()
            assert header.evaluate('el=>el.parentElement.open')
            header.press('Enter')
            page.get_by_text(DIAGNOSIS,exact=True).click()
            settle()
            evidence_control=page.get_by_role('combobox',name='Evidencia que sostiene tu diagnóstico',exact=True)
            evidence_control.click()
            evidence_control.press('ArrowDown')
            page.get_by_role('option',name=PROOF,exact=True).click()
            page.keyboard.press('Escape')
            settle()
            choose('Acción propuesta',ACTION)
            notes=page.get_by_role('textbox',name='Notas de investigación · no se califican',exact=True)
            note='Revisión visual de integración. '+('El mecanismo y la disponibilidad temporal requieren documentación, no solo una cifra alta. '*20)
            notes.fill(note)
            notes.press('Tab')
            settle()
            page.set_viewport_size({'width':390,'height':844})
            sidebar_close()
            notes.scroll_into_view_if_needed()
            no_overflow()
            screenshot('06-detective-long-notes-390.png')
            confirm=page.get_by_role('button',name='Confirmar respuesta',exact=True)
            confirm.focus()
            confirm.press('Tab')
            page.keyboard.press('Shift+Tab')
            expect(confirm).to_be_focused()
            focus=confirm.evaluate('(e)=>({outline:getComputedStyle(e).outlineStyle,width:getComputedStyle(e).outlineWidth,shadow:getComputedStyle(e).boxShadow})')
            assert focus['outline']!='none' or focus['shadow']!='none',focus
            screenshot('07-detective-keyboard-focus-390.png')
            confirm.press('Enter')
            expect(confirm).to_be_disabled()
            confirmed=download('↓ Descargar investigación · JSON','detective-confirmed.json')
            assert 'solution' not in confirmed
            feedback=confirmed['investigation']['answers']['initial']['feedback']
            assert all(feedback.values()),feedback
            assert confirmed['investigation']['answers']['initial']['notes']==note
            record('Native evidence keyboard, long notes, visible focus and confirmed answer',focus)
            page.get_by_role('button',name='Revelar solución y explicación',exact=True).click()
            expect(page.get_by_text('Diagnóstico del expediente:',exact=False)).to_be_visible()
            page.get_by_role('button',name='Ejecutar la acción elegida',exact=True).click()
            expect(page.get_by_text('Resultado de la intervención',exact=True)).to_be_visible()
            repaired=download('↓ Descargar investigación · JSON','detective-repaired.json')
            assert repaired['solution']['diagnosis']=='contaminated' and repaired['intervention']['performed']
            assert 'registro_c17' in repaired['intervention']['before']['feature_names']
            assert 'registro_c17' not in repaired['intervention']['after']['feature_names']
            for key in ('before','after'):
                verify_predictions(repaired['intervention'][key])
            page.get_by_text('Resultado de la intervención',exact=True).scroll_into_view_if_needed()
            screenshot('08-detective-intervention-390.png')
            record('Explicit reveal, real intervention and verified before/after export')
            native_alert_contrast('detective-success')

            # The same real mode remains usable from the native mobile navigation.
            for width in (390,768):
                page.set_viewport_size({'width':width,'height':1000 if width==768 else 844})
                mode('Laboratorio')
                expect(page.get_by_role('heading',name='Laboratorio',exact=True)).to_be_visible()
                mode('Recorrido guiado')
                expect(page.get_by_role('heading',name='Data Crime Scene',exact=True)).to_be_visible()
                mode('Modo Detective')
                expect(page.get_by_role('heading',name='Modo Detective',exact=True)).to_be_visible()
                record(f'Native sidebar selects all three modes at {width}px')
            page.emulate_media(reduced_motion='reduce')
            page.set_viewport_size({'width':1440,'height':1000})
            mode('Recorrido guiado')
            page.get_by_role('heading',name='Data Crime Scene',exact=True).scroll_into_view_if_needed()
            settle()
            assert page.evaluate("matchMedia('(prefers-reduced-motion:reduce)').matches")
            animations=page.evaluate("document.getAnimations().filter(a=>a.playState==='running').map(a=>({name:a.animationName||'',target:a.effect?.target?.className||''}))")
            assert not animations,animations
            screenshot('09-reduced-motion-1440.png')
            record('Reduced motion: same results readable, no running animation after settle')

            report['external_attempts'] += [url for url in report['websockets'] if urlparse(url).hostname not in {'127.0.0.1','localhost'}]
            assert not report['external_attempts'], report['external_attempts']
            assert not report['page_errors'],report['page_errors']
            assert not report['console_errors'],report['console_errors']
            record('No external request attempts, page errors or console errors',{'requests':len(report['requests']),'websockets':len(report['websockets'])})
            report['passed']=True
            browser.close()
    except Exception as error:
        report['passed']=False
        report['failure']={'type':type(error).__name__,'message':str(error)}
        print('FAIL',json.dumps(report['failure'],ensure_ascii=False),flush=True)
        raise
    finally:
        target=args.output_dir/'browser-check.json'
        target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps({'report':str(target),'passed':report.get('passed',False),'checks':len(report['checks']),'external_attempts':report['external_attempts']},ensure_ascii=False),flush=True)


if __name__=='__main__':
    main()
