"""Late integration regressions for review scope, whole-catalog health and jobs."""
from copy import deepcopy
from datetime import datetime,timezone
import json,threading,time
from test_v6 import EngFixture,p,e,g,b,BASE

class ExtendedEngineeringTests(EngFixture):
 def alternate(self,**fields):
  primary=self.part();candidate=self.part(MPN='TEST-ALTERNATE-10K',**fields)
  primary=self.revise(primary,alternates=[{'part_id':candidate['id'],'revision':candidate['revision'],'scope':'R1 default assembly, laboratory build only','evidence':'TEST QUALIFICATION DOCUMENT','reason':'Explicit engineering candidate'}]);return primary,candidate
 def test_alternate_is_not_autoapproved(self):
  self.alternate();ctx=g.context(self.lib,self.ws);a=g.assess(self.lib,ctx);self.assertEqual(a['alternate_assessments'][0]['status'],'REQUIRES_ENGINEERING_REVIEW')
 def test_scoped_alternate_approval(self):
  self.alternate();self.accounts();ctx=g.context(self.lib,self.ws);self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash']);self.assertEqual(g.assess(self.lib,g.context(self.lib,self.ws))['alternate_assessments'][0]['status'],'APPROVED_LOCAL_SCOPE')
 def test_alternate_conflict_blocks_approval(self):
  self.alternate(Value='22k');self.accounts();ctx=g.context(self.lib,self.ws)
  with self.assertRaises(ValueError):self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash'])
 def test_alternate_revision_drift_blocks(self):
  _,candidate=self.alternate();self.revise(candidate,notes='New candidate revision');ctx=g.context(self.lib,self.ws);self.assertTrue(ctx['alternate_targets'][0]['conflicts'])
 def test_alternate_needs_engineer(self):
  self.alternate();self.accounts();ctx=g.context(self.lib,self.ws)
  with self.assertRaises(ValueError):self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash'],reviewer='Buyer',password='test-buyer-passphrase')
 def test_alternate_needs_evidence(self):
  self.alternate();self.accounts();ctx=g.context(self.lib,self.ws)
  with self.assertRaises(ValueError):self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash'],evidence='')
 def test_alternate_does_not_replace_symbol(self):
  self.alternate();self.accounts();before=self.ws._serialize();ctx=g.context(self.lib,self.ws);self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash']);self.assertEqual(before,self.ws._serialize())
 def test_alternate_stale_after_value_edit(self):
  self.alternate();self.accounts();ctx=g.context(self.lib,self.ws);self.decision(ctx,kind='alternate',target=ctx['alternate_targets'][0]['target_hash']);self.edit('R1',{'Notes':'Post-approval edit'});a=g.assess(self.lib,g.context(self.lib,self.ws));self.assertEqual(a['alternate_assessments'][0]['status'],'REQUIRES_ENGINEERING_REVIEW')
 def test_health_full_scan_more_than_one_page(self):
  x=self.part()
  with self.lib.transaction():
   for i in range(220):
    y=deepcopy(x);y['fields']['MPN']='PAGED-'+str(i);y['id']=p.record_identity(y['fields']);y['internal_pn']='PAGED-'+str(i);y.pop('revision',None);self.lib.put(y,'Test','Pagination fixture')
  r=e.health_report(self.lib,all_parts=True);self.assertEqual(r['assessed'],221);self.assertIsNone(r['next_offset']);self.assertEqual(sum(r['counts'].values()),221)
 def test_health_paged_keeps_continuation(self):
  self.part();self.part(MPN='SECOND');r=e.health_report(self.lib,limit=1);self.assertEqual(r['assessed'],1);self.assertEqual(r['next_offset'],1)
 def test_health_cancel_does_not_write(self):
  self.part();before=self.lib.meta('epoch')
  with self.assertRaises(InterruptedError):e.health_report(self.lib,all_parts=True,cancel=lambda:True)
  self.assertEqual(before,self.lib.meta('epoch'))
 def test_health_progress_total(self):
  self.part();calls=[];e.health_report(self.lib,all_parts=True,progress=lambda *a:calls.append(a));self.assertEqual(calls[-1][:2],(1,1))
 def test_health_epoch_drift_fails(self):
  self.part()
  with self.assertRaises(ValueError):e.health_report(self.lib,all_parts=True,progress=lambda *a:self.lib.touch())
 def test_health_explicit_low_stock(self):
  self.evidence(self.part(),stock=20);self.assertTrue(e.health_report(self.lib,low_stock_threshold=50)['items'][0]['health']['low_stock']);self.assertFalse(e.health_report(self.lib,low_stock_threshold=10)['items'][0]['health']['low_stock'])
 def test_health_eol_short_name(self):self.assertEqual(p.catalog_health(self.part(Lifecycle='EOL'))['lifecycle'],'AT RISK')
 def test_health_bad_market(self):
  with self.assertRaises(ValueError):e.health_report(self.lib,market='')
 def test_health_negative_threshold(self):
  with self.assertRaises(ValueError):e.health_report(self.lib,low_stock_threshold=-1)
 def test_missing_ratings_not_certified(self):
  self.part();r=p.recommendations(self.lib,self.ws,BASE,self.row('R1')['id']);self.assertIn('Tolerance',r['items'][0]['missing_evidence']);self.assertEqual(r['items'][0]['state'],'review')
 def test_task_cancel_ready_discards_result(self):
  tasks=e.Tasks();t=tasks.start(lambda progress,cancel:{'parts':[1]})
  for _ in range(50):
   if tasks.get(t['id'])['state']!='running':break
   time.sleep(.005)
  tasks.cancel(t['id']);self.assertEqual(tasks.get(t['id'],True)['state'],'canceled');self.assertIsNone(tasks.get(t['id'],True)['result'])
 def test_task_cancellation_observed(self):
  tasks=e.Tasks()
  def long(progress,cancel):
   while not cancel():time.sleep(.002)
   raise InterruptedError()
  t=tasks.start(long);tasks.cancel(t['id'])
  for _ in range(50):
   if tasks.get(t['id'])['state']!='running':break
   time.sleep(.005)
  self.assertEqual(tasks.get(t['id'])['state'],'canceled')
 def test_task_failure_not_ready(self):
  tasks=e.Tasks();t=tasks.start(lambda p,c:1/0)
  for _ in range(50):
   if tasks.get(t['id'])['state']!='running':break
   time.sleep(.005)
  self.assertEqual(tasks.get(t['id'])['state'],'failed')
