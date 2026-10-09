"""Independent multi-part reference totals across analytics and BOM exports."""
from decimal import Decimal as D
from test_core import Fixture, BASE
from bomstudio import analytics, exporters


class MassCostWorkflowTests(Fixture):
    def setUp(self):
        super().setUp()
        for row in self.ws.rows():
            self.ws.edit([row['id']], BASE, {'in_bom':False, 'on_board':False})
        for ref, mass, rate, mpn in [('R1','100','200','SYNTH-R'),('R2','0.1 g','200','SYNTH-R'),('R3','0.002 kg','500','SYNTH-X'),('R4','10 g','10000','SYNTH-DNP')]:
            self.edit(ref, {'in_bom':True,'on_board':True,'MassInput':mass,'Rate':rate,'PackQty':'100',
                            'PayCurrency':'USD','UnitPrice':'999','Currency':'INR','MOQ':'1','OrderMultiple':'1',
                            'MPN':mpn,'Manufacturer':'Synthetic','Value':'10k' if ref in ('R1','R2') else ref})
        self.ws.state['settings'].update(boards=3,attrition=10)
        analytics.configure(self.ws, {'price_field':'Rate','price_per_field':'PackQty','currency_field':'PayCurrency',
                                      'mass_field':'MassInput','mass_unit':'mg','physical_include_bom_excluded':False,
                                      'metrics':['pricing','mass'],'group_by':['MPN']})
        self.ws.state['templates']['Reference totals']={
            'name':'Reference totals','population':'fitted','include_excluded':False,'group_by':['MPN'],
            'columns':[{'field':key,'label':key} for key in ['Reference','Qty','UnitPrice','Currency','LineCost','OrderCost','@field:UnitPrice','@field:Currency']],
            'delimiter':',','sort_field':'Reference','ref_ranges':False,
        }

    def test_consolidation_sums_every_component_and_exports_all_groups(self):
        from bomstudio.analytics_exports import tables
        report=analytics.run(self.ws)
        groups=report['consolidated']
        pair=next(g for g in groups if 'R1' in g['references'])
        self.assertEqual(set(pair['references']),{'R1','R2'})
        self.assertEqual(pair['components'],2)
        self.assertEqual(D(pair['mass_per_board']),D('.2'))
        self.assertEqual(D(pair['cost_per_board']['USD']),D(4))
        self.assertEqual(sum(g['components'] for g in groups),report['scope']['matched_components'])
        self.assertEqual(sum(D(g['mass_per_board']) for g in groups if g['mass_per_board'] is not None),D('2.2'))
        self.assertEqual(sum(D(g['cost_per_board']['USD']) for g in groups if g['cost_per_board'].get('USD') is not None),D(9))
        exported=tables(report)['consolidated']
        amount=exported['columns'].index('Known mass g')
        self.assertEqual(sum(D(row[amount]) for row in exported['rows'] if row[amount] is not None),D('2.2'))
        self.assertEqual(len(exported['rows']),len(groups))
        self.assertEqual(report['mass']['known_per_board'],analytics.run(self.ws,config={**analytics.defaults(self.ws),'group_by':['Value']})['mass']['known_per_board'])

    def test_consolidation_separates_incompatible_or_unproven_parts(self):
        for field,value in [('MPN','other'),('Value','22k'),('Manufacturer','Other'),('Footprint','Other'),
                            ('Rate','300'),('PayCurrency','EUR'),('PackQty','10'),('MOQ','20'),
                            ('OrderMultiple','4'),('Supplier','Other'),('SKU','Other'),('dnp',True)]:
            with self.subTest(field=field):
                before=self.row('R2')['flags']['dnp'] if field=='dnp' else self.row('R2')['fields'].get(field,'')
                self.edit('R2',{field:value})
                pair=next(g for g in analytics.run(self.ws)['consolidated'] if 'R1' in g['references'])
                self.assertEqual(pair['references'],['R1'])
                self.edit('R2',{field:before})
        for field in ('MPN','Manufacturer'):
            self.edit('R1',{field:''});self.edit('R2',{field:''})
            self.assertEqual(next(g for g in analytics.run(self.ws)['consolidated'] if 'R1' in g['references'])['references'],['R1'])

    def test_consolidation_preserves_partial_totals_and_currencies(self):
        self.edit('R2',{'MassInput':'unknown','Rate':''})
        self.edit('R3',{'PayCurrency':'EUR'})
        report=analytics.run(self.ws)
        unknown=next(g for g in report['consolidated'] if 'R2' in g['references'])
        self.assertIsNone(unknown['mass_per_board'])
        self.assertIsNone(unknown['cost_per_board']['USD'])
        self.assertEqual((unknown['mass_missing_or_invalid'],unknown['price_missing_or_invalid']),(1,1))
        self.assertEqual(report['mass']['status'],'partial')
        self.assertEqual(report['pricing']['currencies']['USD']['known_cost_per_board'],'2')
        self.assertEqual(report['pricing']['currencies']['EUR']['known_cost_per_board'],'5')

    def test_units_rates_pack_basis_and_build_totals(self):
        r=analytics.run(self.ws)
        self.assertEqual(r['mass']['status'],'complete')
        self.assertEqual(r['mass']['known_per_board'],'2.2')  # .1 + .1 + 2 grams
        self.assertEqual(r['mass']['known_build_total'],'6.6')
        usd=r['pricing']['currencies']['USD']
        self.assertEqual(usd['known_cost_per_board'],'9')  # 2 + 2 + 5
        self.assertEqual(usd['known_build_cost'],'27')
        self.assertEqual(usd['known_order_cost'],'34')  # ceil(6*1.1)*2 + ceil(3*1.1)*5
        self.assertEqual(self.ws.public()['stats']['cost'],{'USD':'9'})
        p=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual({k:D(v) for k,v in p['installed_totals'].items()},{'USD':D(9)})
        self.assertEqual({k:D(v) for k,v in p['order_totals'].items()},{'USD':D(34)})
        self.assertEqual(len(p['rows']),2)
        for row in p['rows']:
            values=dict(zip(p['columns'],row))
            self.assertEqual(values['Currency'],'USD')
            self.assertEqual(values['@field:Currency'],'INR')
            self.assertEqual(values['@field:UnitPrice'],'999')
            self.assertIn(D(values['UnitPrice']),(D(2),D(5)))
        self.ws.state['templates']['Reference totals']['group_by']=[]
        ungrouped=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(ungrouped['installed_totals'],p['installed_totals'])
        self.assertEqual(D(ungrouped['order_totals']['USD']),D(36))  # per-line rounding, disclosed
        self.assertIn('rounded per export line',ungrouped['pricing_basis']['notice'])

    def test_mapping_rates_split_groups_and_invalid_rates_stay_unknown(self):
        self.edit('R2',{'Rate':'300'})
        p=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(p['groups'],3)
        self.assertEqual(D(p['installed_totals']['USD']),D(10))
        self.edit('R2',{'PackQty':''})
        p=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(p['unpriced_lines'],1)
        self.assertEqual(D(p['installed_totals']['USD']),D(7))

    def test_canonical_unitprice_pack_basis_is_applied_exactly_once(self):
        for ref, price in [('R1','200'),('R2','200'),('R3','500')]:
            self.edit(ref, {'UnitPrice':price,'Currency':'USD'})
        analytics.configure(self.ws, {'price_field':'UnitPrice','currency_field':'Currency',
                                      'price_per_field':'','price_per':'100'})
        before=self.ws.rows()
        report=analytics.run(self.ws)
        payload=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(report['pricing']['currencies']['USD']['known_cost_per_board'],'9')
        self.assertEqual(D(payload['installed_totals']['USD']),D(9))
        self.assertEqual(D(payload['order_totals']['USD']),D(34))
        for row in payload['rows']:
            values=dict(zip(payload['columns'],row))
            self.assertEqual(D(values['@field:UnitPrice'])/100,D(values['UnitPrice']))
        self.assertEqual(self.ws.rows(),before)

    def test_custom_purchase_policy_mapping_and_unknown_policy(self):
        for ref in ('R1','R2','R3'):
            self.edit(ref,{'BuyMinimum':'10','BuyMultiple':'4'})
        analytics.configure(self.ws,{**analytics.defaults(self.ws),'moq_field':'BuyMinimum','multiple_field':'BuyMultiple'})
        template=self.ws.state['templates']['Reference totals']
        template['columns'] += [{'field':key,'label':key} for key in ['MOQ','OrderMultiple','OrderQty','@field:MOQ','@field:OrderMultiple']]
        report=analytics.run(self.ws)
        payload=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(D(report['pricing']['currencies']['USD']['known_order_cost']),D(84))
        self.assertEqual(D(payload['order_totals']['USD']),D(84))  # 12*2 + 12*5
        for row in payload['rows']:
            values=dict(zip(payload['columns'],row))
            self.assertEqual((values['MOQ'],values['OrderMultiple'],values['OrderQty']),(10,4,12))
            self.assertEqual((values['@field:MOQ'],values['@field:OrderMultiple']),('1','1'))
        self.edit('R2',{'BuyMinimum':'20'})
        payload=exporters.table(self.ws,BASE,'Reference totals')
        self.assertEqual(payload['groups'],3)  # incompatible mapped policies must split
        self.assertEqual(D(payload['order_totals']['USD']),D(124))
        self.edit('R2',{'BuyMultiple':'bad'})
        payload=exporters.table(self.ws,BASE,'Reference totals')
        values=next(dict(zip(payload['columns'],row)) for row in payload['rows'] if row[0]=='R2')
        self.assertEqual(values['OrderQty'],'')
        self.assertEqual(values['OrderCost'],'')
        self.assertEqual(D(payload['installed_totals']['USD']),D(9))
        self.assertEqual(D(payload['order_totals']['USD']),D(84))  # known subtotal only
        self.assertTrue(any(issue['code']=='ORDER_POLICY_INVALID' and issue['reference']=='R2' for issue in payload['issues']))

    def test_variant_dnp_and_mixed_or_missing_observations(self):
        self.ws.new_variant('Calculation',BASE)
        self.ws.set_population([self.row('R2')['id']],'Calculation','DNP')
        r=analytics.run(self.ws,'Calculation')
        self.assertEqual(r['mass']['known_per_board'],'2.1')
        self.assertEqual(r['pricing']['currencies']['USD']['known_cost_per_board'],'7')
        self.assertEqual(D(exporters.table(self.ws,'Calculation','Reference totals')['installed_totals']['USD']),D(7))
        self.edit('R2',{'MassInput':'unknown','Rate':''})
        self.edit('R3',{'PayCurrency':'EUR'})
        r=analytics.run(self.ws)
        self.assertEqual(r['mass']['status'],'partial')
        self.assertEqual(r['mass']['known_per_board'],'2.1')
        self.assertEqual(r['mass']['known_components'],2)
        self.assertEqual(r['pricing']['missing_or_invalid_components'],1)
        self.assertEqual(r['pricing']['currencies']['USD']['known_cost_per_board'],'2')
        self.assertEqual(r['pricing']['currencies']['EUR']['known_cost_per_board'],'5')
        self.assertIsNone(r['pcb']['assembly_cost_per_board'])
