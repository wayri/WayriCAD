"""v0.5 unit-aware quantitative analytics. Synthetic fixtures only."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from decimal import Decimal as D
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch
import csv, io, json, unittest, zipfile, xml.etree.ElementTree as ET
from test_core import Fixture
from bomstudio import analytics as a, analytics_exports as ex, measures as m, search, cli, configedit, automation
from bomstudio.engine import Workspace
from bomstudio.native import Project, BASE, sha

class QuantityTests(unittest.TestCase):
 def test_mass_units(self):
  for raw,expected in [('250 mg','.25'),('1.2kg','1200'),('100µg','.0001'),('100μg','.0001'),('1 grams','1')]:
   with self.subTest(raw=raw):self.assertEqual(m.parse(raw,'g').value,D(expected))
 def test_power_units(self):self.assertEqual(m.parse('250mW','W').value,D('.25'))
 def test_celsius_fahrenheit_kelvin(self):
  for raw in ('80 C','176 °F','353.15 K'):
   with self.subTest(raw=raw):self.assertEqual(m.parse(raw,'C').value,D(80))
 def test_bare_number_uses_explicit_default(self):self.assertEqual(m.parse('250','mg').value,D('.25'));self.assertTrue(m.parse('250','mg').assumed_unit)
 def test_explicit_overrides_same_dimension(self):self.assertEqual(m.parse('1 g','mg').value,D(1))
 def test_dimension_mismatch(self):self.assertEqual(m.parse('1W','g').status,'invalid')
 def test_case_sensitive_SI(self):self.assertEqual(m.parse('1MW','W').status,'invalid');self.assertEqual(m.parse('1mW','W').value,D('.001'))
 def test_fraction(self):self.assertEqual(m.parse('1/4 W','W').value,D('.25'))
 def test_divide_zero(self):self.assertEqual(m.parse('1/0 g','g').status,'invalid')
 def test_zero_not_missing(self):self.assertEqual(m.parse('0g','g').status,'known')
 def test_missing_tokens(self):
  for raw in (None,'','Unknown','TBD','N/A','—','?'):
   with self.subTest(raw=raw):self.assertEqual(m.parse(raw).status,'missing')
 def test_malformed_finite_limits(self):
  for raw in ('NaN','Infinity','1e999','1e-99',True,'1e19','1.000,23','1/0','__import__("os")','1 W + 2 W'):
   with self.subTest(raw=raw):self.assertEqual(m.parse(raw).status,'invalid')
 def test_english_thousands(self):self.assertEqual(m.parse('1,234.50').value,D('1234.5'))
 def test_negative_mass_not_permitted(self):self.assertEqual(m.parse('-1 g','g',nonnegative=True).status,'invalid')
 def test_negative_temperature_permitted(self):self.assertEqual(m.parse('-40 F','C').value,D(-40))
 def test_absolute_zero_bound(self):self.assertEqual(m.parse('-273.16 C','C').status,'invalid')
 def test_percent_ratio(self):self.assertEqual(m.parse('.25 ratio','%').value,D(25))
 def test_voltage_current_length(self):
  for raw,unit,expected in [('250mV','V','.25'),('100uA','A','.0001'),('2cm','mm','20')]:
   self.assertEqual(m.parse(raw,unit).value,D(expected))
 def test_literal_context(self):self.assertEqual(m.literal('2g').dimension,'mass')
 def test_condition_requires_operator(self):
  for condition in ('80','==80','<','<NaN','<80 OR 1'):
   with self.subTest(condition=condition):
    try:_,raw=m.compact_condition(condition);q=m.literal(raw);self.assertNotEqual(q.status,'known')
    except ValueError:pass
 def test_comparators(self):
  for op in ('<','<=','>','>=','=','!='):self.assertIsInstance(m.compare(D(1),op,D(2)),bool)
 def test_decimal_text(self):self.assertEqual(m.text(D('1000.0000')),'1000');self.assertEqual(m.text(D('.0001')),'0.0001')

class AnalyticsFixture(Fixture):
 def setUp(self):
  super().setUp()
  ids=[r['id'] for r in self.ws.rows()]
  self.ws.edit(ids,BASE,{'Rate':'2.00','Mass':'100mg','Dissipation':'250mW','Temp_Max':'85 C','ComponentType':'Passive','RatedPower':'1W','Duty':'25','PricePer':'1'})
  self.c={'price_field':'Rate','quote_date_field':'','query':'Reference=R1 OR Reference=R2','scenario_boards':[1,10,100]}
 def run_report(self,**changes):return a.run(self.ws,BASE,{**self.c,**changes})

class PricingTests(AnalyticsFixture):
 def test_selected_price_column(self):self.assertEqual(self.run_report()['pricing']['currencies']['INR']['known_cost_per_board'],'4')
 def test_not_mutating_project_workspace(self):
  before=self.ws._serialize();hashes=dict(self.ws.project.hashes);self.run_report();self.assertEqual(before,self.ws._serialize());self.assertEqual(hashes,self.ws.project.hashes);self.ws.project.check_unchanged()
 def test_pack_price(self):self.assertEqual(self.run_report(price_per='100')['pricing']['currencies']['INR']['known_cost_per_board'],'0.04')
 def test_per_row_pack_quantity(self):
  self.edit('R2',{'PricePer':'2'});self.assertEqual(self.run_report(price_per_field='PricePer')['pricing']['currencies']['INR']['known_cost_per_board'],'3')
 def test_missing_per_row_divisor_is_unknown(self):
  self.edit('R2',{'PricePer':''});p=self.run_report(price_per_field='PricePer')['pricing'];self.assertEqual(p['priced_components'],1)
 def test_negative_price_rejected(self):
  self.edit('R2',{'Rate':'-1'});p=self.run_report()['pricing'];self.assertEqual(p['priced_components'],1);self.assertEqual(p['currencies']['INR']['known_cost_per_board'],'2')
 def test_zero_price_known(self):
  self.edit('R2',{'Rate':'0'});self.assertEqual(self.run_report()['pricing']['priced_components'],2)
 def test_missing_price_coverage(self):
  self.edit('R2',{'Rate':''});p=self.run_report()['pricing'];self.assertEqual(p['coverage_percent'],'50');self.assertEqual(p['missing_or_invalid_components'],1)
 def test_all_prices_missing_not_zero(self):
  self.edit('R1',{'Rate':''});self.edit('R2',{'Rate':''});self.assertIsNone(self.run_report()['pricing']['currencies']['INR']['known_cost_per_board'])
 def test_currencies_separate(self):
  self.edit('R2',{'Currency':'USD'});p=self.run_report()['pricing'];self.assertEqual(set(p['currencies']),{'INR','USD'});self.assertFalse(p['fx']['enabled'])
 def test_currency_embedded(self):
  self.edit('R1',{'Currency':'','Rate':'USD 3.25'});self.assertEqual(self.run_report()['pricing']['currencies']['USD']['known_cost_per_board'],'3.25')
 def test_contradictory_currency(self):
  self.edit('R1',{'Currency':'INR','Rate':'USD 5'});self.assertEqual(self.run_report()['pricing']['priced_components'],1)
 def test_rupee_symbol(self):
  self.edit('R1',{'Rate':'₹ 5'});self.assertEqual(self.run_report()['pricing']['currencies']['INR']['known_cost_per_board'],'7')
 def test_ambiguous_symbol_needs_matching_currency(self):
  self.edit('R1',{'Rate':'$5','Currency':'INR'});self.assertEqual(self.run_report()['pricing']['priced_components'],1)
 def test_fx_explicit_dated_direction(self):
  self.edit('R2',{'Currency':'USD'});p=self.run_report(fx={'base_currency':'INR','rates':{'USD':'80'},'source':'Synthetic arithmetic test','as_of':'2026-01-01'})['pricing'];self.assertEqual(p['fx']['known_cost_per_board'],'162');self.assertEqual(p['fx']['status'],'complete')
 def test_fx_missing_rate_remains_partial(self):
  self.edit('R2',{'Currency':'USD'});p=self.run_report(fx={'base_currency':'INR'})['pricing'];self.assertEqual(p['fx']['status'],'partial');self.assertEqual(p['fx']['missing_rates'],['USD'])
 def test_fitted_bom_scope(self):
  self.ws.set_population([self.row('R1')['id']],BASE,'DNI');self.assertEqual(self.run_report()['pricing']['eligible_components'],1)
 def test_bom_excluded_not_priced(self):
  self.edit('R1',{'in_bom':False});r=self.run_report();self.assertEqual(r['pricing']['eligible_components'],1);self.assertEqual(r['mass']['eligible_components'],2)
 def test_moq_required_order_breakdown(self):
  for ref in ('R1','R2'):self.edit(ref,{'MOQ':'10','OrderMultiple':'4'})
  r=self.run_report(boards=3,attrition_percent='10');self.assertEqual(len(r['procurement']),1);lot=r['procurement'][0]
  self.assertEqual((lot['installed_qty'],lot['required_qty'],lot['order_qty'],lot['overbuy_qty']),(6,7,12,5));self.assertEqual(lot['order_cost'],'24')
 def test_invalid_moq_no_false_order(self):
  self.edit('R1',{'MOQ':'bad'});lot=next(x for x in self.run_report()['procurement'] if 'R1' in x['references']);self.assertIsNone(lot['order_qty']);self.assertIsNone(lot['order_cost'])
 def test_different_skus_not_pooled(self):
  self.edit('R2',{'SKU':'different'});self.assertEqual(len(self.run_report()['procurement']),2)
 def test_different_price_not_pooled(self):
  self.edit('R2',{'Rate':'3'});self.assertEqual(len(self.run_report()['procurement']),2)
 def test_exact_mpn_suffix_preserved(self):
  self.edit('R2',{'MPN':'Different-TR'});self.assertEqual(len(self.run_report()['procurement']),2)
 def test_incomplete_identity_not_pooled(self):
  for ref in ('R1','R2'):self.edit(ref,{'MPN':'','Manufacturer':''})
  self.assertEqual(len(self.run_report()['procurement']),2)
 def test_quote_future_stale_and_undated(self):
  self.edit('R1',{'When':'2000-01-01'});self.edit('R2',{'When':'2100-01-01'});r=self.run_report(quote_date_field='When');self.assertEqual(r['pricing']['quote_status_counts'],{'stale':1,'future':1});self.assertEqual(r['pricing']['priced_components'],2)
 def test_invalid_quote_date(self):
  self.edit('R1',{'When':'not a date'});self.assertIn('QUOTE_DATE_INVALID',[x['code'] for x in self.run_report(quote_date_field='When')['issues']])
 def test_valid_recent_quote(self):
  self.edit('R1',{'When':(datetime.now(timezone.utc)-timedelta(hours=1)).isoformat()});self.assertEqual(self.run_report(quote_date_field='When')['pricing']['quote_status_counts']['dated_within_window'],1)
 def test_scenarios_reuse_rates(self):
  rows=self.run_report(boards=2)['scenarios'];self.assertEqual([r['boards'] for r in rows],[2,1,10,100]);self.assertEqual(rows[-1]['known_installed_cost'],'400')
 def test_group_pareto(self):
  self.edit('R2',{'ComponentType':'IC','Rate':'8'});r=self.run_report();p=r['pricing']['pareto']['INR'];self.assertEqual(p[0]['label'],'IC');self.assertEqual(p[0]['share_percent'],'80');self.assertEqual(p[0]['abc'],'A');self.assertEqual(p[1]['abc'],'B')
 def test_variable_price_provenance(self):
  self.ws.set_variables('project',{'MY_RATE':'7'},BASE);self.edit('R1',{'Rate':'${MY_RATE}'});r=self.run_report();p=r['components'][0];self.assertEqual(p['cost']['unit_price'],'7');self.assertEqual(p['source_fields']['price_field']['raw_value'],'${MY_RATE}')
 def test_unresolved_variable_not_numeric(self):
  self.edit('R1',{'Rate':'${NEVER_DEFINED}'});self.assertEqual(self.run_report()['pricing']['priced_components'],1)
 def test_overview_uses_saved_mapping_pack_price(self):
  a.configure(self.ws,{**self.c,'price_per':'10'});s=self.ws.public();self.assertEqual(s['analytics_settings']['price_field'],'Rate');self.assertEqual(D(s['stats']['cost']['INR']),D('2'))

class MassThermalTests(AnalyticsFixture):
 def test_mass_units_and_type_breakdown(self):
  r=self.run_report();self.assertEqual(r['mass']['known_per_board'],'0.2');self.assertEqual(r['groups'][0]['mass_per_board'],'0.2')
 def test_mass_build_not_attrition_or_moq(self):
  r=self.run_report(boards=10,attrition_percent='100');self.assertEqual(r['mass']['known_per_board'],'0.2');self.assertEqual(r['mass']['known_build_total'],'2')
 def test_excluded_physical_policy_toggle(self):
  self.edit('R1',{'in_bom':False});self.assertEqual(self.run_report(physical_include_bom_excluded=False)['mass']['eligible_components'],1)
 def test_offboard_no_mass_or_heat(self):
  self.edit('R1',{'on_board':False});r=self.run_report();self.assertEqual(r['mass']['eligible_components'],1);self.assertEqual(r['thermal']['eligible_components'],1)
 def test_missing_mass_not_zero(self):
  self.edit('R1',{'Mass':''});r=self.run_report();self.assertEqual(r['mass']['status'],'partial');self.assertEqual(r['mass']['known_per_board'],'0.1')
 def test_negative_mass_invalid(self):
  self.edit('R1',{'Mass':'-1g'});self.assertEqual(self.run_report()['mass']['invalid_components'],1)
 def test_unknown_all_mass(self):
  self.assertIsNone(self.run_report(mass_field='Unavailable')['mass']['known_per_board'])
 def test_average_power_no_duty_multiplier(self):
  self.assertEqual(self.run_report(duty_percent='25')['thermal']['known_per_board'],'0.5')
 def test_active_power_fixed_duty(self):self.assertEqual(self.run_report(power_basis='active',duty_percent='25')['thermal']['known_per_board'],'0.125')
 def test_active_power_mapped_duty(self):
  self.edit('R2',{'Duty':'50'});self.assertEqual(self.run_report(power_basis='active',duty_field='Duty')['thermal']['known_per_board'],'0.1875')
 def test_missing_duty_unknown(self):
  self.edit('R1',{'Duty':''});self.assertEqual(self.run_report(power_basis='active',duty_field='Duty')['thermal']['known_components'],1)
 def test_bad_duty_range(self):
  for raw in ('-1','101','banana'):
   self.edit('R1',{'Duty':raw});self.assertEqual(self.run_report(power_basis='active',duty_field='Duty')['thermal']['known_components'],1)
 def test_zero_duty_not_missing(self):
  r=self.run_report(power_basis='active',duty_percent='0');self.assertEqual(r['thermal']['known_per_board'],'0');self.assertEqual(r['thermal']['known_components'],2)
 def test_rated_power_not_automatically_loss(self):
  self.edit('R1',{'Dissipation':''});r=self.run_report(rating_field='RatedPower');self.assertEqual(r['thermal']['known_components'],1)
 def test_above_rating_finding(self):
  self.edit('R1',{'Dissipation':'2W'});self.assertIn('DISSIPATION_ABOVE_RECORDED_RATING',[i['code'] for i in self.run_report(rating_field='RatedPower')['issues']])
 def test_temperature_conversion_and_requirement(self):
  self.edit('R1',{'Temp_Max':'176F'});r=self.run_report(temperature_requirement_c='81');self.assertEqual(r['thermal']['minimum_known_temp_max_c'],'80');self.assertIn('TEMPERATURE_RATING_BELOW_REQUIREMENT',[i['code'] for i in r['issues']])
 def test_temperature_headroom(self):
  r=self.run_report(temperature_requirement_c='80');self.assertEqual(r['components'][0]['temperature']['headroom_c'],'5')
 def test_no_batch_thermal_total(self):
  r=self.run_report(boards=100);self.assertNotIn('known_build_total',r['thermal']);self.assertTrue(all(s['power_w_per_board']=='0.5' for s in r['scenarios']))
 def test_type_fallback_labelled(self):
  self.edit('R1',{'ComponentType':''});r=self.run_report();p=r['components'][0];self.assertEqual(p['type_source'],'reference-prefix heuristic');self.assertEqual(p['type'],'Resistor')
 def test_arbitrary_composite_grouping(self):
  r=self.run_report(group_by=['Footprint','@population']);self.assertIn('Footprint',r['groups'][0]['keys'])
 def test_disabled_metrics_not_error(self):
  r=self.run_report(metrics=['mass']);self.assertEqual(r['pricing']['currencies'],{});self.assertIsNone(r['thermal']['known_per_board']);self.assertIsNone(r['scenarios'][0]['known_order_cost'])
 def test_variant_population_changes(self):
  c={**self.c,'query':'Reference=R3'};self.assertEqual(a.run(self.ws,'Economy',c)['mass']['eligible_components'],0)
 def test_shared_instance_count(self):
  r=self.run_report(query='Reference=R101 OR Reference=R201');self.assertEqual(r['mass']['known_per_board'],'0.2');self.assertEqual(r['scope']['matched_components'],2)

class BudgetStatisticsThresholdTests(AnalyticsFixture):
 def test_cost_exceeds_budget(self):
  b=self.run_report(budgets={'cost_per_board':{'INR':'3'}})['budgets'][0];self.assertEqual(b['status'],'exceeded')
 def test_budget_unknown_with_incomplete_data(self):
  self.edit('R1',{'Mass':''});b=self.run_report(budgets={'mass_g':'10'})['budgets'][0];self.assertEqual(b['status'],'unknown')
 def test_exceeded_even_incomplete(self):
  self.edit('R1',{'Mass':''});b=self.run_report(budgets={'mass_g':'0.05'})['budgets'][0];self.assertEqual(b['status'],'exceeded')
 def test_complete_budget_within(self):
  self.assertEqual(self.run_report(budgets={'power_w':'1'})['budgets'][0]['status'],'within_known_budget')
 def test_unknown_budget_currency(self):
  self.assertEqual(self.run_report(budgets={'cost_per_board':{'EUR':'10'}})['budgets'][0]['status'],'unknown')
 def test_empty_scope_not_zero(self):
  r=self.run_report(query='Reference=R999');self.assertIsNone(r['mass']['known_per_board']);self.assertTrue(any(i['code']=='EMPTY_ANALYTICS_SCOPE' for i in r['issues']))
 def test_numeric_statistics_canonical(self):
  self.edit('R2',{'Mass':'300mg'});s=self.run_report(statistics={'Mass':'g'})['statistics']['Mass'];self.assertEqual(s['mean'],'0.2');self.assertEqual(s['median'],'0.2');self.assertEqual(s['p95_nearest_rank'],'0.3');self.assertEqual(sum(b['count'] for b in s['histogram']),2)
 def test_stats_missing_invalid_counts(self):
  self.edit('R1',{'Temp_Max':''});self.edit('R2',{'Temp_Max':'invalid'});s=self.run_report(statistics={'Temp_Max':'C'})['statistics']['Temp_Max'];self.assertEqual((s['known'],s['missing'],s['invalid']),(0,1,1));self.assertIsNone(s['mean'])
 def test_threshold_exact_boundary(self):
  self.edit('R1',{'Temp_Max':'79'});self.edit('R2',{'Temp_Max':'80'});t=a.threshold(self.ws,BASE,'Temp_Max','<80');self.assertEqual(t['references'],['R1'])
 def test_threshold_explicit_rhs_unit(self):
  self.edit('R1',{'Mass':'200mg'});t=a.threshold(self.ws,BASE,'Mass','>150mg');self.assertEqual(t['references'],['R1'])
 def test_threshold_fahrenheit_equal(self):
  self.edit('R1',{'Temp_Max':'176F'});self.assertEqual(a.threshold(self.ws,BASE,'Temp_Max','=80')['references'],['R1'])
 def test_threshold_unknowns_excluded_even_not_equal(self):
  self.edit('R1',{'Temp_Max':''});self.edit('R2',{'Temp_Max':'bad'});t=a.threshold(self.ws,BASE,'Temp_Max','!=85');self.assertNotIn('R1',t['references']);self.assertNotIn('R2',t['references']);self.assertEqual(len(t['unknown_or_invalid']),2)
 def test_threshold_query_scope(self):
  t=a.threshold(self.ws,BASE,'Temp_Max','>80',query='Reference=R1');self.assertEqual(t['tested'],1)
 def test_threshold_does_not_mutate(self):
  before=self.ws._serialize();a.threshold(self.ws,BASE,'Temp_Max','<80');self.assertEqual(before,self.ws._serialize())
 def test_threshold_unknown_field(self):
  with self.assertRaises(ValueError):a.threshold(self.ws,BASE,'Typo','<80')
 def test_search_threshold_parity(self):
  self.edit('R1',{'Temp_Max':'70C'});self.assertEqual(search.run(self.ws,BASE,'Temp_Max<80')['references'],a.threshold(self.ws,BASE,'Temp_Max','<80')['references'])
 def test_search_explicit_units_without_default(self):
  self.edit('R1',{'New_Field':'1g'});self.assertEqual(search.run(self.ws,BASE,'New_Field>"500mg"')['references'],['R1'])
 def test_search_saved_unit_mapping(self):
  self.edit('R1',{'Extra_Temp':'176 F'});a.configure(self.ws,{'field_units':{'Extra_Temp':'C'}});self.assertEqual(search.run(self.ws,BASE,'Extra_Temp>=80')['references'],['R1'])
 def test_stale_source_fails(self):
  self.ws.project.root.write_text(self.ws.project.root.read_text()+'\n')
  with self.assertRaises(ValueError):self.run_report()

class V5RegressionTests(AnalyticsFixture):
 def test_raw_default_units_in_shared_search(self):
  self.edit('R1',{'Mass':'100'});a.configure(self.ws,{'mass_field':'raw.Mass','mass_unit':'mg'});self.assertEqual(a.threshold(self.ws,BASE,'raw.Mass','>0.05g')['references'],search.run(self.ws,BASE,'raw.Mass>"0.05g"')['references'])
 def test_structured_metrics_invalid_value_error(self):
  for c in ({'metrics':[{}]},{'group_by':[[]]}):
   with self.assertRaises(ValueError):a.validate_config(c)
 def test_threshold_external_source_change_rejected(self):
  self.ws.project.root.write_text(self.ws.project.root.read_text()+'\n')
  with self.assertRaises(ValueError):a.threshold(self.ws,BASE,'Temp_Max','<80')
 def test_raw_resolved_unit_conflict_rejected(self):
  with self.assertRaises(ValueError):a.validate_config({'mass_field':'raw.Mass','mass_unit':'mg','statistics':{'Mass':'g'}})
 def test_saved_config_pure_no_mutation_validation(self):
  c={'statistics':{'Mass':'gram'}};before=deepcopy(c);a.validate_config(c);self.assertEqual(c,before)

class ConfigTests(Fixture):
 def test_unknown_keys_and_schema(self):
  for c in ({'shell':'bad'},{'schema':'future'}):
   with self.assertRaises(ValueError):a.validate_config(c)
 def test_wrong_dimensions(self):
  for c in ({'mass_unit':'W'},{'power_unit':'g'},{'temperature_unit':'V'}):
   with self.assertRaises(ValueError):a.validate_config(c)
 def test_same_field_conflicting_default_units(self):
  for c in ({'statistics':{'Mass':'mg'}},{'field_units':{'Mass':'mg'}},{'statistics':{'X':'g'},'field_units':{'X':'mg'}}):
   with self.assertRaises(ValueError):a.validate_config(c)
 def test_allow_consistent_units(self):self.assertEqual(a.validate_config({'statistics':{'Mass':'g'}})['statistics']['Mass'],'g')
 def test_dissipation_rating_not_same_field(self):
  with self.assertRaises(ValueError):a.validate_config({'rating_field':'Dissipation'})
 def test_bad_numeric_options(self):
  for c in ({'boards':0},{'boards':True},{'attrition_percent':'NaN'},{'price_per':'0'},{'duty_percent':'101'},{'scenario_boards':[1,1]},{'scenario_boards':[1.5]},{'quote_max_age_days':-1}):
   with self.subTest(c=c),self.assertRaises(ValueError):a.validate_config(c)
 def test_fx_provenance_required(self):
  with self.assertRaises(ValueError):a.validate_config({'fx':{'base_currency':'INR','rates':{'USD':'80'}}})
 def test_fx_rate_zero_invalid(self):
  with self.assertRaises(ValueError):a.validate_config({'fx':{'base_currency':'INR','rates':{'USD':'0'},'source':'test','as_of':'2026-01-01'}})
 def test_fx_base_rate_one(self):
  with self.assertRaises(ValueError):a.validate_config({'fx':{'base_currency':'INR','rates':{'INR':'2'},'source':'test','as_of':'2026-01-01'}})
 def test_settings_undo_and_save(self):
  original=self.ws._serialize();a.configure(self.ws,{'price_field':'Rate'});self.ws.undo();self.assertEqual(original,self.ws._serialize());a.configure(self.ws,{'price_field':'Rate'});self.ws.save();self.assertEqual(a.defaults(Workspace(Project(self.path)))['price_field'],'Rate')
 def test_legacy_sidecar_gets_defaults(self):
  self.ws.state.pop('analytics_settings',None);self.ws.save();self.assertEqual(a.defaults(Workspace(Project(self.path)))['mass_unit'],'g')
 def test_config_review_operation(self):
  p=configedit.preview(self.ws,[{'op':'analytics-settings','settings':{'mass_unit':'mg'}}]);self.assertTrue(p)
 def test_schema_unsafe_name_validation(self):
  for c in ({'price_field':'bad\nname'},{'group_by':['@bad']},{'statistics':{'X':'badunit'}},{'budgets':{'wrong':1}}):
   with self.assertRaises(ValueError):a.validate_config(c)

class AnalyticsExportTests(AnalyticsFixture):
 def test_all_formats(self):
  r=self.run_report()
  for fmt in ex.MIME:
   with self.subTest(fmt=fmt):raw,name,mime=ex.render(r,fmt);self.assertTrue(raw);self.assertIn('.',name);self.assertTrue(mime)
 def test_all_csv_tables(self):
  r=self.run_report()
  for table in ex.TABLES:
   raw,_,_=ex.render(r,'csv',table);rows=list(csv.reader(io.StringIO(raw.decode('utf-8-sig'))));self.assertEqual(rows[0][:2],['Project','Variant']);self.assertGreaterEqual(len(rows),1)
 def test_csv_formula_protection(self):
  self.edit('R1',{'ComponentType':'=HYPERLINK("evil")'});raw,_,_=ex.render(self.run_report(),'csv','components');self.assertIn("'=HYPERLINK",raw.decode('utf-8-sig'))
 def test_html_escaping(self):
  self.edit('R1',{'ComponentType':'<script>alert(1)</script>'});raw,_,_=ex.render(self.run_report(),'html');self.assertNotIn(b'<script>',raw);self.assertIn(b'&lt;script&gt;',raw)
 def test_ascii_7bit(self):
  r=self.run_report(scenario_name='μ thermal ₹');raw,_,_=ex.render(r,'ascii');self.assertTrue(all(b<128 for b in raw))
 def test_xlsx_readable_xml_no_formulas(self):
  self.edit('R1',{'ComponentType':'=1+1'});raw,_,_=ex.render(self.run_report(),'xlsx');z=zipfile.ZipFile(io.BytesIO(raw));self.assertIsNone(z.testzip());sheets=[n for n in z.namelist() if n.startswith('xl/worksheets/')];self.assertEqual(len(sheets),8)
  for name in sheets:
   data=z.read(name);ET.fromstring(data);self.assertNotIn(b'<f>',data)
  self.assertTrue(any(b'=1+1' in z.read(n) for n in sheets))
 def test_xlsx_missing_not_numeric_zero(self):
  self.edit('R1',{'Mass':''});raw,_,_=ex.render(self.run_report(),'xlsx');z=zipfile.ZipFile(io.BytesIO(raw));ET.fromstring(z.read('xl/workbook.xml'));self.assertIn(b'Mass status',z.read('xl/worksheets/sheet2.xml'))
 def test_json_preserves_canonical_decimal(self):
  raw,_,_=ex.render(self.run_report(),'json');self.assertEqual(json.loads(raw)['mass']['known_per_board'],'0.2')
 def test_unknown_format_fails(self):
  with self.assertRaises(ValueError):ex.render(self.run_report(),'exe')
 def test_unknown_table_fails(self):
  with self.assertRaises(ValueError):ex.render(self.run_report(),'csv','wrong')
 def test_bundle_hashes(self):
  raw,_,_=ex.render(self.run_report(),'zip');z=zipfile.ZipFile(io.BytesIO(raw));manifest=json.loads(z.read('manifest.json'));self.assertEqual(manifest['schema'],'wayricad-analytics-bundle-1')
  for name,info in manifest['files'].items():self.assertEqual(sha(z.read(name)),info['sha256'])

class AnalyticsCLITests(AnalyticsFixture):
 def call(self,*args):
  out=io.StringIO();err=io.StringIO()
  with redirect_stdout(out),redirect_stderr(err):code=cli.main([str(x) for x in args])
  return code,out.getvalue(),err.getvalue()
 def setUp(self):super().setUp();self.ws.save()
 def test_analytics_flag_mapping_stdout(self):
  code,out,err=self.call('analytics',self.path,'--price-field','Rate','--query','Reference=R1','--mass-unit','g');self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['pricing']['currencies']['INR']['known_cost_per_board'],'2')
 def test_analytics_config_stdin(self):
  with patch('sys.stdin',io.StringIO(json.dumps(self.c))):code,out,err=self.call('analytics',self.path,'--config','-')
  self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['mass']['known_per_board'],'0.2')
 def test_analytics_all_file_formats(self):
  for fmt in ex.MIME:
   out=self.dir/('analytics.'+fmt);code,_,err=self.call('analytics',self.path,'--price-field','Rate','--format',fmt,'--output',out);self.assertEqual(code,0,(fmt,err));self.assertTrue(out.is_file())
 def test_analytics_no_overwrite(self):
  out=self.dir/'existing.json';out.write_text('keep');code,_,_=self.call('analytics',self.path,'--output',out);self.assertEqual(code,4);self.assertEqual(out.read_text(),'keep')
 def test_analytics_nonjson_needs_output(self):self.assertEqual(self.call('analytics',self.path,'--format','xlsx')[0],2)
 def test_analytics_failure_threshold(self):self.assertEqual(self.call('analytics',self.path,'--mass-field','MissingData','--fail-on','unknown')[0],3)
 def test_threshold_cli(self):
  code,out,err=self.call('threshold',self.path,'--field','Temp_Max','--condition','<86','--rows');self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['matched'],11)
 def test_threshold_exit_matches(self):self.assertEqual(self.call('threshold',self.path,'--field','Temp_Max','--condition','<86','--fail-on-match')[0],3)
 def test_threshold_unknown_exit(self):
  self.edit('R1',{'Temp_Max':''});self.ws.save();self.assertEqual(self.call('threshold',self.path,'--field','Temp_Max','--condition','<80','--fail-on-unknown')[0],3)
 def test_query_unit_override(self):
  code,out,err=self.call('query',self.path,'--query','Mass>0.05','--unit','Mass=g');self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['matched'],11)
 def test_stats_flag(self):
  code,out,err=self.call('analytics',self.path,'--stat','Temp_Max=C');self.assertEqual(code,0,err);self.assertEqual(json.loads(out)['data']['statistics']['Temp_Max']['known'],11)
 def test_invalid_config_error_not_internal(self):
  c=self.dir/'config.json';c.write_text('{"price_per":0}');self.assertEqual(self.call('analytics',self.path,'--config',c)[0],2)
 def test_cli_native_unchanged(self):
  hashes=dict(self.ws.project.hashes);self.call('analytics',self.path);self.call('threshold',self.path,'--field','Temp_Max','--condition','<80');self.assertEqual(hashes,self.ws.project.hashes);self.ws.project.check_unchanged()

class AnalyticsPipelineTests(Fixture):
 def config(self):return {'schema':'wayricad-pipeline-1','variants':[BASE],'reports':['analytics'],'analytics':{'metrics':['pricing']},'analytics_formats':['json','csv','xlsx','html']}
 def test_analytics_pipeline_reports(self):
  result=automation.pipeline(self.ws,self.config(),self.dir/'run');self.assertEqual(result['status'],'PASSED');files=list((self.dir/'run/001').glob('analytics*'));self.assertEqual(len(files),10);self.assertTrue(automation.verify_run(self.dir/'run')['valid'])
 def test_analytics_gate_error_suppresses_boms(self):
  c=self.config();c['analytics']['budgets']={'cost_per_board':{'INR':'0'}};c['policy']={'analytics':'error'};r=automation.pipeline(self.ws,c,self.dir/'run');self.assertEqual(r['status'],'FAILED');self.assertTrue(any(g['kind']=='analytics' for g in r['gates']));self.assertEqual(list((self.dir/'run/001').glob('*Purchasing*')),[])
 def test_analytics_gate_unknown(self):
  c=self.config();c['analytics']={'metrics':['mass']};c['policy']={'analytics':'unknown'};self.assertEqual(automation.pipeline(self.ws,c,self.dir/'run')['status'],'FAILED')
 def test_default_legacy_pipeline_does_not_enable_analytics(self):
  c=automation.default_pipeline();self.assertNotIn('analytics',c['reports'])
 def test_saved_mapping_used_when_config_null(self):
  a.configure(self.ws,{'metrics':['mass']});c=self.config();c['analytics']=None;automation.pipeline(self.ws,c,self.dir/'run');r=json.loads((self.dir/'run/001/analytics.json').read_text());self.assertEqual(r['config']['metrics'],['mass'])

class AnalyticsSampleLaunchTests(unittest.TestCase):
 def test_demo_identity_normalizes_temporary_path_alias(self):
  import tempfile
  from bomstudio.server import Application
  from bomstudio import engineering_demo
  with tempfile.TemporaryDirectory(prefix='wayricad-demo-identity-') as directory:
   root=Path(directory).resolve();alias=root.parent/'..'/root.parent.name/root.name
   with patch('bomstudio.server.tempfile.mkdtemp',return_value=str(alias)):
    app=Application(demo=True)
   try:
    self.assertEqual(app.demo_directory,root)
    self.assertTrue(app.state()['demo'])
    app.demo_directory=alias
    engineering_demo.prepare(app)
    self.assertTrue(Path(app.library_path,'catalog.sqlite3').is_file())
   finally:app.link.close()
 def test_analytics_sample_is_temporary_and_preconfigured(self):
  import shutil
  from bomstudio.server import Application, ROOT
  original={str(p):sha(p.read_bytes()) for p in (ROOT/'examples/analytics').glob('*.kicad_*')}
  app=Application(analytics_demo=True)
  try:
   self.assertTrue(app.state()['demo']); self.assertEqual(app.state()['analytics_settings']['price_field'],'Rate')
   self.assertNotEqual(app.workspace.project.root.parent,ROOT/'examples/analytics')
   report=a.run(app.workspace,BASE)
   self.assertEqual(report['mass']['known_per_board'],'1.43');self.assertEqual(report['mass']['known_components'],9)
   self.assertEqual(original,{str(p):sha(p.read_bytes()) for p in (ROOT/'examples/analytics').glob('*.kicad_*')})
  finally:
   app.link.close();shutil.rmtree(app.demo_directory,ignore_errors=True)
 def test_analytics_demo_detached_cli_transport(self):
  import http.client,shutil,time
  from urllib.parse import urlsplit
  from bomstudio.launch import detached,_children
  result=detached(analytics_demo=True,no_browser=True,no_auto_link=True);u=urlsplit(result['url']);token=u.fragment.removeprefix('token=')
  try:
   c=http.client.HTTPConnection(u.hostname,u.port,timeout=5);c.request('GET','/api/state',headers={'X-Bom-Token':token});resp=c.getresponse()
   self.assertEqual(resp.status,200);state=json.loads(resp.read());self.assertEqual(state['analytics_settings']['price_field'],'Rate');self.assertTrue(state['demo']);c.close()
  finally:
   c=http.client.HTTPConnection(u.hostname,u.port,timeout=5);c.request('POST','/api/quit',body='{}',headers={'X-Bom-Token':token,'Content-Type':'application/json'});resp=c.getresponse();resp.read();c.close()
   deadline=time.monotonic()+5
   while result['pid'] in _children and time.monotonic()<deadline:time.sleep(.05)
   self.assertNotIn(result['pid'],_children);shutil.rmtree(result['session_directory'],ignore_errors=True)
