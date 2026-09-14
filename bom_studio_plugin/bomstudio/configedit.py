"""Reviewed CLI configuration transactions; data-only explicit operation allowlist."""
from copy import deepcopy
import difflib
import json
from .engine import Workspace
from . import catalog,search,bulkedit
from .native import BASE


def simulate(ws,operations):
    if not isinstance(operations,list) or not 1<=len(operations)<=100:raise ValueError('Provide 1–100 configuration operations.')
    shadow=Workspace(ws.project,load=False);shadow.state=deepcopy(ws.state)
    destructive=False
    for op in operations:
        if not isinstance(op,dict):raise ValueError('Configuration operation must be an object.')
        kind=op.get('op')
        allowed={
            'variant-add':{'op','name','parent','description'},'variant-remove':{'op','name'},
            'variables':{'op','scope','values','variant'},'settings':{'op','settings'},'aliases':{'op','aliases'},
            'template-save':{'op','template'},'profile-save':{'op','profile'},'template-import':{'op','bundle','policy'},
            'filter-save':{'op','name','record'},'filter-remove':{'op','name'},'analytics-settings':{'op','settings'}}
        if kind not in allowed or set(op)-allowed[kind]:raise ValueError('Unknown configuration operation/options: '+str(kind))
        if kind=='variant-add':shadow.new_variant(op['name'],op.get('parent',BASE),op.get('description',''))
        elif kind=='variant-remove':shadow.remove_variant(op['name']);destructive=True
        elif kind=='variables':shadow.set_variables(op['scope'],op['values'],op.get('variant',BASE));destructive=True
        elif kind=='settings':shadow.settings(op['settings'])
        elif kind=='aliases':shadow.set_aliases(op['aliases'])
        elif kind=='template-save':shadow.template(op['template'])
        elif kind=='profile-save':catalog.save_profile(shadow,op['profile'])
        elif kind=='template-import':catalog.import_apply(shadow,json.dumps(op['bundle']),op.get('policy','keep_both'));destructive|=op.get('policy')=='replace'
        elif kind=='filter-save':search.save_filter(shadow,op['name'],op['record'])
        elif kind=='filter-remove':search.save_filter(shadow,op['name'],remove=True)
        elif kind=='analytics-settings':
            from .analytics import configure
            configure(shadow,op['settings'])
    shadow.state['history']=deepcopy(ws.state['history'])
    before=json.dumps(ws.state,indent=2,sort_keys=True,ensure_ascii=False).splitlines(True)
    after=json.dumps(shadow.state,indent=2,sort_keys=True,ensure_ascii=False).splitlines(True)
    diff=''.join(difflib.unified_diff(before,after,fromfile='workspace-before',tofile='workspace-after'))
    return shadow.state,diff,destructive


def preview(ws,operations):
    ws.project.check_unchanged();state,diff,destructive=simulate(ws,operations)
    return {'schema':'wayricad-config-plan-1','operations':deepcopy(operations),'fingerprint':bulkedit.digest(ws,operations),
            'diff':diff,'acknowledgement_required':destructive,'warning':'Changes saved workspace only. Variable changes may alter many resolved part values. Native sync remains separate.'}


def apply(ws,operations,fingerprint,confirmation,acknowledge_loss=False):
    if confirmation!='CONFIG':raise ValueError('Type CONFIG to apply reviewed workspace configuration.')
    if fingerprint!=bulkedit.digest(ws,operations):raise ValueError('Configuration plan is stale.')
    ws.project.check_unchanged();state,diff,destructive=simulate(ws,operations)
    if destructive and not acknowledge_loss:raise ValueError('Acknowledge configuration/variable loss before applying.')
    ws.commit('Reviewed CLI configuration transaction',lambda:ws.state.update(state))
    return {'changed':bool(diff),'operations':len(operations)}
