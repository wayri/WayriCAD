"""Reference-informed routing screens, not protocol compliance specifications.

Rates are representative operating presets; edge times and timing budgets must
come from the actual device/interface configuration. Targets are nominal vendor
routing recommendations, not universal acceptance limits.
"""
from copy import deepcopy

REFS = {
    'i2c': 'https://cache.nxp.com/docs/en/user-guide/UM10204.pdf',
    'serial': 'https://www.ti.com/document-viewer/lit/html/SLLA584',
    'i2s': 'https://www.nxp.com/docs/en/user-manual/UM11732.pdf',
    'can': 'https://www.ti.com/lit/an/slla270/slla270.pdf',
    'lvds': 'https://www.ti.com/lit/ug/snla187/snla187.pdf',
    'usb': 'https://www.ti.com/lit/an/slla414/slla414.pdf',
    'pcie': 'https://pcisig.com/faq?field_category_value%5B%5D=pci_express_4.0',
    'pcie_z': 'https://www.ti.com/video/6051762921001',
    'pcie_legacy_z': 'https://www.ti.com/lit/ug/sllu149e/sllu149e.pdf',
    'sata': 'https://www.ti.com/product/SN75LVCP601',
    'm2': 'https://www.kingston.com/en/ssd/ssd-faq',
    'ddr3': 'https://cdrdv2-public.intel.com/654640/emi_archive_91.pdf',
    'ddr4': 'https://docs.amd.com/r/en-US/ug863-versal-pcb-design/Physical-Design-Rules-for-DDR4-Signals',
    'ddr5': 'https://www.intel.com/content/www/us/en/docs/programmable/772538/24-3-1/routing-guidelines-for-ddr5-rdimm-udimm.html',
    'rgmii': 'https://www.ti.com/lit/ds/symlink/dp83867ir.pdf',
    'sgmii': 'https://www.ti.com/lit/ds/symlink/dp83867cs.pdf',
    'kr': 'https://www.ti.com/lit/ds/symlink/tlk10031.pdf',
    'ethernet_z': 'https://www.ti.com/product/SN65LVCP114',
    'pci': 'https://cdrdv2-public.intel.com/840888/e14960009_s3210sh_tps_r1_8.pdf',
}


def _profile(key, title, family, topology, rate=None, target=None,
             refs=(), notes='', rate_kind='Gb/s NRZ', clock_mhz=None):
    return dict(id=key, title=title, family=family, topology=topology,
                rate_kind=rate_kind, rate_Gbps=rate,
                nyquist_GHz=rate / 2 if rate is not None else None,
                clock_MHz=clock_mhz, target_impedance_ohm=target,
                impedance_kind='differential' if topology == 'differential' else 'single-ended',
                references=[REFS[r] for r in refs], instructions=notes,
                bus_checks=topology in ('bus', 'differential'),
                limitations=['Routing screening only; no protocol compliance, IBIS, coupled crosstalk, channel loss or receiver model.',
                             'Supply actual edge time, source/load assumptions and user timing/impedance budgets.'])


_CATALOG = []
for key, rate in [('standard', .0001), ('fast', .0004), ('fast-plus', .001)]:
    _CATALOG.append(_profile('i2c-' + key, 'I2C ' + key, 'I2C', 'bus', rate,
                            refs=('i2c',), notes='Open-drain bus: verify pull-ups, capacitance and device timing separately. Assign clock/data roles and a group.'))
for key, title, refs in [('spi', 'SPI', ('serial',)), ('uart', 'UART', ('serial',)),
                         ('i2s-tdm', 'I2S / TDM', ('i2s',)), ('parallel-gpio', 'Parallel GPIO', ('serial',)),
                         ('sdio', 'SDIO (device-defined timing)', ('serial',))]:
    _CATALOG.append(_profile(key, title, title, 'single' if key == 'uart' else 'bus',
                            refs=refs, notes='No universal rate or impedance target. Use the device datasheet and configured mode. For bus skew assign one clock and data routes to each group.'))
_CATALOG += [
    _profile('can-classic', 'Classic CAN — 1 Mb/s', 'CAN', 'differential', .001, refs=('can',),
             notes='120 ohm is the cable/bus termination target, not a mandatory PCB trace target. Transceiver delay, sample point, stubs and bus capacitance require separate analysis.'),
    _profile('lvds', 'LVDS — device-defined rate', 'LVDS', 'differential', target=100, refs=('lvds',),
             notes='Assign P/N roles with the same lane group; set device rate and edge assumptions externally.'),
    _profile('serdes-nrz', 'Generic NRZ SerDes', 'SerDes', 'differential', refs=('lvds',),
             notes='Choose rate, termination and impedance from the actual transceiver; no generic compliance limits.'),
    _profile('pci-33', 'Legacy parallel PCI — 33 MHz', 'PCI', 'bus', .033, refs=('pci',), clock_mhz=33,
             rate_kind='GT/s per data pin', notes='Parallel PCI, not PCI Express. Device loading, topology and setup/hold timing are not modeled.'),
]
for generation, rate in [(1, 2.5), (2, 5), (3, 8), (4, 16)]:
    _CATALOG.append(_profile('pcie-gen' + str(generation), 'PCIe Gen%d — %g GT/s' % (generation, rate),
                            'PCIe', 'differential', rate, 100 if generation < 3 else 85,
                            ('pcie', 'pcie_legacy_z' if generation < 3 else 'pcie_z'),
                            'Nominal vendor routing target; verify connector/device channel requirements. Assign P/N per lane. Encoding overhead does not change symbol Nyquist frequency.', 'GT/s NRZ'))
for rate in (1.5, 3, 6):
    _CATALOG.append(_profile('sata-' + str(rate).replace('.', '-'), 'SATA — %g Gb/s' % rate,
                            'SATA', 'differential', rate, 100, ('sata',), 'Assign P/N per lane; AC coupling and channel loss are not simulated.'))
for key, title, rate in [('usb2-fs', 'USB 2 full speed', .012), ('usb2-hs', 'USB 2 high speed', .480),
                         ('usb3-gen1', 'USB 3 Gen1', 5), ('usb3-gen2', 'USB 3 Gen2', 10)]:
    _CATALOG.append(_profile(key, title, 'USB', 'differential', rate, 90, ('usb',),
                            'Assign P/N per lane. Bit rate is not edge bandwidth; supply the actual edge time. No USB compliance mask is evaluated.'))
for generation, rate in [(3, 1.6), (4, 2.4), (5, 4.8)]:
    _CATALOG.append(_profile('ddr%d' % generation, 'DDR%d — %g MT/s representative DQ' % (generation, rate * 1000),
                            'DDR', 'bus', rate, 50, ('ddr%d' % generation,),
                            'DQ routing example, not a full memory timing model. Group each data byte with its strobe route as clock; differential strobes require separate coupled extraction. Topology/ODT and controller training are not modeled.',
                            'GT/s per DQ pin', rate * 500))
_CATALOG += [
    _profile('rgmii', 'Ethernet RGMII — 125 MHz DDR', 'Ethernet', 'bus', .250, 50, ('rgmii',),
             'Group clock/data for each direction. Account for configured internal clock delay; no fixed skew limit is assumed.', 'GT/s per data pin', 125),
    _profile('sgmii', 'Ethernet SGMII — 1.25 Gb/s', 'Ethernet', 'differential', 1.25, 100, ('sgmii', 'ethernet_z')),
    _profile('10gbase-kr', 'Ethernet 10GBASE-KR — 10.3125 Gb/s', 'Ethernet', 'differential', 10.3125, 100, ('kr', 'ethernet_z')),
    _profile('m2', 'M.2 — choose PCIe or SATA', 'M.2', 'interface-required', refs=('m2',),
             notes='M.2 is a form factor. Select an actual PCIe generation or SATA rate before screening.'),
]
for interface in ('pcie-gen3', 'pcie-gen4', 'sata-6'):
    entry = deepcopy(next(p for p in _CATALOG if p['id'] == interface))
    entry.update(id='m2-' + interface, title='M.2 / ' + entry['title'], base_profile=interface, form_factor='M.2')
    entry['references'].append(REFS['m2'])
    _CATALOG.append(entry)

# Synchronous/open-drain bus transfer rates do not establish an NRZ channel
# Nyquist bandwidth. For DDR/RGMII the alternating data-pattern frequency is
# informative, but still does not establish edge bandwidth.
for entry in _CATALOG:
    if entry['family'] in ('I2C', 'CAN', 'PCI'):
        entry['rate_kind'] = 'Gb/s nominal bus rate' if entry['family'] != 'PCI' else 'GT/s per data pin'
        entry['nyquist_GHz'] = None
    if entry['family'] == 'PCIe':
        entry['limitations'].append('85/100 ohm nominal routing recommendations vary with device, generation, connector and board channel; consult the actual endpoint design guide. This preset is not a mandated PCI-SIG impedance limit.')


def list_profiles():
    """Return independently editable, JSON-serializable catalog entries."""
    return deepcopy(_CATALOG)


def get_profile(profile_id):
    for profile in _CATALOG:
        if profile['id'] == profile_id:
            return deepcopy(profile)
    raise ValueError('Unknown protocol profile: ' + str(profile_id))
