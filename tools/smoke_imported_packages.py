"""Exercise imported CLI entrypoints and report assets from an isolated wheel."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source_root = Path(__file__).resolve().parents[1]
    parser.add_argument('wheel', type=Path, nargs='?',
                        help='Wheel to inspect; defaults to the single built wayricad wheel in dist/')
    requested = parser.parse_args().wheel
    if requested is None:
        wheels = sorted((source_root / 'dist').glob('wayricad-*.whl'))
        if len(wheels) != 1:
            parser.error('Expected one built wayricad wheel in dist/; pass its path explicitly')
        wheel = wheels[0]
    else:
        wheel = requested.resolve()
    active_plugins = {
        path.name for path in source_root.glob('*_plugin')
        if (path / 'metadata.json').is_file()
    }
    with tempfile.TemporaryDirectory(prefix='wayricad-wheel-') as temporary:
        root = Path(temporary)
        with zipfile.ZipFile(wheel) as archive:
            if any(name.startswith(('build/', 'dist/', '.validation/')) for name in archive.namelist()):
                raise RuntimeError('Wheel contains generated build or private validation directories.')
            stale_plugins = {
                Path(name).parts[0] for name in archive.namelist()
                if Path(name).parts and Path(name).parts[0].endswith('_plugin')
                and Path(name).parts[0] not in active_plugins
            }
            if stale_plugins:
                raise RuntimeError(
                    'Wheel contains inactive plugin files: ' + ', '.join(sorted(stale_plugins))
                )
            archive.extractall(root)
        modules = ('wayricad_runtime.jobs', 'wayricad_runtime.cli', 'trace_impedance_plugin.cli', 'copper_balancer_plugin.cli', 'mechanical_check_plugin.cli',
                   'embed_3d_plugin.__main__', 'quick_pi_plugin.cli', 'quick_therm_plugin.cli', 'signal_integrity_advisor_plugin.cli', 'project_fusion_plugin.__main__', 'variant_manager_plugin.wayri_variants.cli')
        for module in modules:
            script = ('import importlib,sys;sys.path.insert(0,sys.argv[1]);'
                      'module=importlib.import_module(sys.argv[2]);'
                      'sys.argv=[sys.argv[2],"--help"];raise SystemExit(module.main())')
            result = subprocess.run([sys.executable, '-c', script, str(root), module],
                                    cwd=root, capture_output=True, text=True, timeout=30)
            if result.returncode or 'usage:' not in result.stdout.lower():
                raise RuntimeError(module + ': ' + result.stdout + result.stderr)
            print(module + ': isolated CLI help passed')
        script = '''import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from argparse import Namespace
from wayricad_runtime.cli import execute
settings=execute(Namespace(kind='fanout',operation='settings',board=None))
assert 'Custom-angle spread' in settings['choices']['pattern']
assert 'PCIe' in settings['profiles']
from mechanical_check_plugin import cli
assert cli.main(['--init-rules', str(Path(sys.argv[1])/'rules.json')]) == 0
assert (Path(sys.argv[1])/'mechanical_check_plugin/src/wayricad_mechanical/report_scene.js').is_file()
assert (Path(sys.argv[1])/'mechanical_check_plugin/resources/help.html').is_file()
from protocol_constraint_composer_plugin.constraint_studio.help_system import HelpLibrary
assert len(HelpLibrary().topics) >= 100
assert (Path(sys.argv[1])/'protocol_constraint_composer_plugin/help-workflow.png').is_file()
for relative in ('quick_pi_plugin/decoupling', 'signal_integrity_advisor_plugin/return_path', 'signal_integrity_advisor_plugin/test_points'):
    folder=Path(sys.argv[1])/relative
    for asset in ('__init__.py','help.html','help-workflow.png','icon.png'):
        assert (folder/asset).is_file(), str(folder/asset)
from quick_pi_plugin.decoupling.analysis import analyze_decoupling
from signal_integrity_advisor_plugin.return_path.analysis import ReturnPathAnalyzer
from signal_integrity_advisor_plugin.test_points.fixture import FixturePoint

# Run the real local server from the extracted wheel. Import success alone
# cannot catch a missing web payload, which leaves installed views unusable.
import http.client,json,re,threading
from bom_studio_plugin.bomstudio.server import Application,Server
app=Application()
server=Server(app)
thread=threading.Thread(target=server.serve_forever,daemon=True)
thread.start()
def get_bom(path):
    connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
    try:
        connection.request('GET',path,headers={'X-Bom-Token':app.token})
        response=connection.getresponse()
        status,mime,data=response.status,response.getheader('Content-Type'),response.read()
        assert status==200 and data,(path,status,data)
        return mime,data
    finally:
        connection.close()
try:
    mime,html=get_bom('/')
    assert mime.startswith('text/html')
    paths=re.findall(r'(?:src|href)="(/[^\"]+)"',html.decode('utf-8'))
    assert '/workspace.js' in paths and '/analytics.js' in paths
    for path in paths:
        mime,data=get_bom(path)
        expected=('text/javascript' if path.endswith('.js') else
                  'image/x-icon' if path.endswith('.ico') else 'text/css')
        assert mime.startswith(expected),(path,mime)
    assert json.loads(get_bom('/api/state')[1])['version']=='3.6.14'
    assert (Path(sys.argv[1])/'bom_studio_plugin/help.html').is_file()
    example=Path(sys.argv[1])/'bom_studio_plugin/examples/BOM_Demo.kicad_pro'
    assert example.is_file()
    from bom_studio_plugin.bomstudio.native import Project,BASE
    from bom_studio_plugin.bomstudio.engine import Workspace
    from bom_studio_plugin.bomstudio import analytics
    workspace=Workspace(Project(example))
    records=workspace.rows()
    assert len(records)>=3
    for row in records:
        workspace.edit([row['id']],BASE,{'in_bom':False,'on_board':False})
    for i,(mass,rate) in enumerate((('100','200'),('0.1 g','200'),('0.002 kg','500'))):
        workspace.edit([records[i]['id']],BASE,{'in_bom':True,'on_board':True,'dnp':False,
            'MassInput':mass,'Rate':rate,'PackQty':'100','PayCurrency':'USD',
            'MPN':'SYNTH-PAIR' if i<2 else 'SYNTH-OTHER','Value':'10k' if i<2 else 'other',
            'Manufacturer':'Synthetic','Footprint':'Synthetic:Part','MOQ':'1','OrderMultiple':'1',
            'Supplier':'Synthetic','SKU':'SYNTH-PAIR' if i<2 else 'SYNTH-OTHER','QuoteDate':''})
    config={**analytics.defaults(workspace),'query':'','metrics':['mass','pricing'],
        'mass_field':'MassInput','mass_unit':'mg','price_field':'Rate','price_per_field':'PackQty',
        'currency_field':'PayCurrency','supplier_field':'Supplier','sku_field':'SKU',
        'quote_date_field':'QuoteDate','moq_field':'MOQ','multiple_field':'OrderMultiple',
        'physical_include_bom_excluded':False}
    app.workspace=workspace
    def post_bom(path,payload):
        connection=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=10)
        try:
            connection.request('POST',path,body=json.dumps(payload),headers={
                'X-Bom-Token':app.token,'Origin':server.origin,'Content-Type':'application/json'})
            response=connection.getresponse();data=response.read()
            assert response.status==200,(path,response.status,data)
            return data
        finally:connection.close()
    report=json.loads(post_bom('/api/analytics/run',{'variant':BASE,'config':config}))
    assert report['mass']['known_per_board']=='2.2'
    assert report['pricing']['currencies']['USD']['known_cost_per_board']=='9'
    pair=next(g for g in report['consolidated'] if g['keys']['MPN']=='SYNTH-PAIR')
    assert pair['components']==2 and pair['mass_per_board']=='0.2' and pair['cost_per_board']['USD']=='4'
    exported=post_bom('/api/analytics/export',{'variant':BASE,'config':config,
                                           'format':'csv','table':'consolidated'})
    assert b'Known mass g' in exported and b'SYNTH-PAIR' in exported
    print('Isolated wheel: BoM assets/API, whole mass/cost sums and consolidated CSV passed')
finally:
    server.shutdown();server.server_close();thread.join(5)
    assert not thread.is_alive()
for folder,example in (('quick_pi_plugin','transient-load-step.json'),('quick_therm_plugin','transient-power-step.json')):
    import importlib,json
    asset=Path(sys.argv[1])/folder/'studies'/example
    assert asset.is_file(), str(asset)
    study=json.loads(asset.read_text())
    result=importlib.import_module(folder+'.transient').solve_transient(study)
    assert len(result['times_s']) > 1
from wayricad_runtime.transient_study import draw_study
from quick_pi_plugin.electrothermal_service import execute as execute_coupled
from quick_pi_plugin.electrothermal_report import write_report as write_coupled_report
for mode in ('steady','transient'):
    asset=Path(sys.argv[1])/'quick_pi_plugin'/'studies'/('electrothermal-'+mode+'.json')
    envelope=json.loads(asset.read_text(encoding='utf-8'))
    bundle=execute_coupled({'action':'electrothermal',**envelope})
    assert bundle['electrothermal']['status'] in ('converged','completed')
    write_coupled_report(Path(sys.argv[1])/(mode+'-coupled.html'),bundle)

'''
        subprocess.run([sys.executable, '-c', script, str(root)], cwd=root, check=True, timeout=120)
        print('Isolated wheel: report assets and mechanical rules export passed')


if __name__ == '__main__':
    main()
