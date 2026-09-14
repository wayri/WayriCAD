"""Explainable local category suggestions. No part qualification or MPN decoding.

Explicit Category / ComponentType takes priority. Description/library hints
narrow broad reference-prefix hints; conflicting families stay visible. Nothing
is written into the part's authoritative fields by this module.
"""
from __future__ import annotations
import re
from collections import Counter

VERSION = 'wayricad-taxonomy-1'
# This is a browsing taxonomy, not an assertion of an IEC/IEEE designator standard.
RULES = (
    ('Passives/Resistors/Networks', r'\b(resistor (?:array|network)|resistance network)\b'),
    ('Passives/Resistors/Potentiometers', r'\b(potentiometer|rheostat|trimpot|trimmer resistor)\b'),
    ('Passives/Resistors', r'\b(resistor|resistance chip|thick film|thin film|metal film)\b'),
    ('Passives/Capacitors/Ceramic', r'\b(mlcc|ceramic capacitor|multilayer ceramic|c0g|np0|x7r|x5r)\b'),
    ('Passives/Capacitors/Tantalum', r'\b(tantalum)\b'),
    ('Passives/Capacitors/Aluminium', r'\b(alumin(?:ium|um) (?:electrolytic|capacitor)|electrolytic capacitor)\b'),
    ('Passives/Capacitors/Film', r'\b(film capacitor|polypropylene capacitor|polyester capacitor)\b'),
    ('Passives/Capacitors', r'\b(capacitor|supercapacitor)\b'),
    ('Passives/Inductors/Ferrite beads', r'\b(ferrite bead|ferrite chip)\b'),
    ('Passives/Inductors', r'\b(inductor|choke)\b'),
    ('Passives/Transformers', r'\b(transformer)\b'),
    ('Semiconductors/Diodes/TVS', r'\b(tvs|transient voltage suppressor|esd protection diode)\b'),
    ('Semiconductors/Diodes/Schottky', r'\b(schottky)\b'),
    ('Semiconductors/Diodes/Zener', r'\b(zener)\b'),
    ('Optoelectronics/LEDs', r'\b(led|light emitting diode)\b'),
    ('Semiconductors/Diodes', r'\b(diode|rectifier)\b'),
    ('Semiconductors/Transistors/MOSFETs', r'\b(mosfet|n-channel fet|p-channel fet)\b'),
    ('Semiconductors/Transistors/IGBTs', r'\b(igbt)\b'),
    ('Semiconductors/Transistors/Bipolar', r'\b(bjt|bipolar transistor|npn transistor|pnp transistor)\b'),
    ('Semiconductors/Transistors', r'\b(transistor|jfet)\b'),
    ('Integrated circuits/Power/Linear regulators', r'\b(ldo|linear regulator|low dropout)\b'),
    ('Integrated circuits/Power/Switching regulators', r'\b(buck|boost|switching regulator|dc[ -]?dc converter)\b'),
    ('Integrated circuits/Power/Gate drivers', r'\b(gate driver|mosfet driver|half bridge driver)\b'),
    ('Integrated circuits/Amplifiers', r'\b(op[ -]?amp|operational amplifier|instrumentation amplifier)\b'),
    ('Integrated circuits/Comparators', r'\b(comparator)\b'),
    ('Integrated circuits/Data converters/ADC', r'\b(adc|analog.to.digital)\b'),
    ('Integrated circuits/Data converters/DAC', r'\b(dac|digital.to.analog)\b'),
    ('Integrated circuits/Processors/MCU', r'\b(microcontroller|mcu)\b'),
    ('Integrated circuits/Processors/FPGA', r'\b(fpga|cpld)\b'),
    ('Integrated circuits/Memory', r'\b(eeprom|flash memory|sram|dram|fram)\b'),
    ('Integrated circuits/Interface', r'\b(transceiver|level shifter|i2c buffer|usb bridge)\b'),
    ('Integrated circuits/Logic', r'\b(logic gate|flip.flop|logic buffer|shift register)\b'),
    ('Optoelectronics/Optocouplers', r'\b(optocoupler|optoisolator|opto-isolator)\b'),
    ('Sensors', r'\b(sensor|accelerometer|gyroscope)\b'),
    ('Connectors', r'\b(connector|pin header|socket|terminal block|receptacle)\b'),
    ('Electromechanical/Relays', r'\b(relay|contactor)\b'),
    ('Electromechanical/Switches', r'\b(pushbutton|tactile switch|slide switch|rotary switch|toggle switch)\b'),
    ('Protection/Fuses', r'\b(fuse|polyfuse|resettable fuse)\b'),
    ('Timing/Crystals', r'\b(crystal|resonator)\b'),
    ('Timing/Oscillators', r'\b(oscillator|tcxo|ocxo)\b'),
    ('Power sources/Batteries', r'\b(battery|battery holder)\b'),
    ('Hardware/Mounting', r'\b(mounting hole|standoff|screw|washer)\b'),
    ('Test/Points', r'\b(test point|testpoint)\b'),
)
COMPILED = tuple((name, re.compile(rx, re.I)) for name, rx in RULES)
PREFIXES = {'R':'Passives/Resistors','RN':'Passives/Resistors/Networks','RV':'Passives/Resistors/Potentiometers',
            'C':'Passives/Capacitors','L':'Passives/Inductors','FB':'Passives/Inductors/Ferrite beads',
            'T':'Passives/Transformers','D':'Semiconductors/Diodes','Q':'Semiconductors/Transistors',
            'U':'Integrated circuits','IC':'Integrated circuits','J':'Connectors','P':'Connectors',
            'K':'Electromechanical/Relays','SW':'Electromechanical/Switches','S':'Electromechanical/Switches',
            'F':'Protection/Fuses','Y':'Timing','X':'Timing','BT':'Power sources/Batteries',
            'TP':'Test/Points','H':'Hardware/Mounting','LED':'Optoelectronics/LEDs'}
TYPE_MAP = {'resistor':'Passives/Resistors','resistors':'Passives/Resistors','capacitor':'Passives/Capacitors',
            'capacitors':'Passives/Capacitors','inductor':'Passives/Inductors','inductors':'Passives/Inductors',
            'diode':'Semiconductors/Diodes','mosfet':'Semiconductors/Transistors/MOSFETs','transistor':'Semiconductors/Transistors',
            'ic':'Integrated circuits','integrated circuit':'Integrated circuits','connector':'Connectors','connectors':'Connectors',
            'led':'Optoelectronics/LEDs','fuse':'Protection/Fuses','relay':'Electromechanical/Relays','sensor':'Sensors'}


def compatible(a, b):
    return a == b or a.startswith(b+'/') or b.startswith(a+'/') or ({a,b} == {'Semiconductors/Diodes','Optoelectronics/LEDs'})


def classify(part):
    fields=part.get('fields',{})
    if not isinstance(fields,dict): fields={}
    lower={str(k).casefold():str(v) for k,v in fields.items()}
    explicit=next(((k,lower[k].strip()) for k in ('category','componenttype','component type','part category') if lower.get(k,'').strip()),None)
    descriptions=[]
    for key,value in fields.items():
        if any(word in str(key).casefold() for word in ('description','keyword')) and str(value).strip():
            descriptions.append((str(key),str(value)[:8000]))
    library=lower.get('librarysymbol','')
    if library:descriptions.append(('LibrarySymbol',re.sub(r'[:_]', ' ', library)))
    matches=[]
    for category,rx in COMPILED:
        hit=next(((key,m.group(0)) for key,text in descriptions if (m:=rx.search(text))),None)
        if hit:matches.append({'category':category,'field':hit[0],'keyword':hit[1]})
    # Keep more specific matches, and preserve competing families.
    candidates=[m for m in matches if not any(n['category'].startswith(m['category']+'/') for n in matches)]
    refs=[part.get('reference_hint',''),fields.get('Reference','')]
    refs.extend(s.get('reference','') for s in part.get('sources',[])[:1000] if isinstance(s,dict))
    prefix_counts=Counter()
    for value in refs:
        m=re.match(r'^([A-Za-z]+)(?:\d|\?)',str(value).strip())
        if m and m[1].upper() in PREFIXES:prefix_counts[m[1].upper()]+=1
    prefix_categories=list(dict.fromkeys(PREFIXES[k] for k in prefix_counts))
    warnings=[]
    if explicit:
        key,category=explicit;category=TYPE_MAP.get(category.casefold(),category)
        basis='declared';confidence='authored';reasons=[f'{key}: {explicit[1]}']
    elif candidates:
        # Ties across unrelated families are not silently decided by rule order.
        unrelated=any(not compatible(a['category'],b['category']) for a in candidates for b in candidates)
        if unrelated:
            category='Unclassified/Conflicting hints';basis='conflict';confidence='review'
            warnings.append('Description keywords identify different component families; choose Category explicitly.')
        else:category=max(candidates,key=lambda m:len(m['category']))['category'];basis='description';confidence='suggested'
        reasons=[m['field']+': '+m['keyword']+' → '+m['category'] for m in candidates]
    elif len(prefix_categories)==1:
        category=prefix_categories[0];basis='reference';confidence='low';reasons=['Reference prefix '+', '.join(prefix_counts)]
    else:
        category='Unclassified';basis='missing' if not prefix_categories else 'conflict';confidence='unknown';reasons=[]
    if category not in ('Unclassified','Unclassified/Conflicting hints'):
        for pref in prefix_categories:
            # U is often used for optocouplers, sensors and regulators. It cannot
            # prove a subtype; don't call these broadly compatible usages errors.
            if not compatible(pref,category) and not (pref=='Integrated circuits' and category.startswith(('Sensors','Optoelectronics/Optocouplers'))):
                warnings.append(f'Reference suggests {pref}, but category is {category}.')
        if explicit:
            for m in candidates:
                if not compatible(category,m['category']):warnings.append('Declared category differs from description hint '+m['category']+'.')
    return {'version':VERSION,'category':category,'basis':basis,'confidence':confidence,
            'reasons':reasons,'warnings':list(dict.fromkeys(warnings)), 'reference_prefixes':list(prefix_counts),
            'authoritative':bool(explicit),'notice':'Browsing suggestion, not electrical qualification. Set Category to override; no source fields were changed.'}
