"""Fanout geometry vocabulary; presets are starting points, not interface standards.

Widths, clearance, impedance and timing must come from the project's stackup and
interface constraints. Selecting a profile does not replace user dimensions.
"""
FANOUT_PATTERNS = (
    'Perimeter pitch expansion',
    'Dogbone outward', 'Dogbone inward', 'BGA/LGA grid outward',
    'Quadrant outward', 'Quadrant inward', 'Four-corner outward',
    'Four-corner inward', 'Perimeter outward', 'Radial outward',
    '45-degree spread', 'Custom-angle spread', 'Straight + angled escape',
    'Staggered rows',
)
SIGNAL_PROFILES = ('Generic', 'DDR', 'GDDR', 'SERDES', 'PCIe', 'PCI', 'PXI', 'PXIe', 'LVDS')
ANGLE_MODES = ('Pattern', 'Board absolute', 'Footprint relative')
PAIR_MODES = ('Independent', 'Auto differential pairs')


def profile_defaults(name):
    """Return explicitly loadable geometry suggestions, without electrical guesses."""
    if name not in SIGNAL_PROFILES:
        raise ValueError('Unknown signal profile: ' + str(name))
    filters = {'Generic': '*', 'DDR': '*DDR*,*DQ*,*DQS*,*CK*,*ADDR*',
               'GDDR': '*GDDR*,*DQ*,*DQS*,*WCK*,*EDC*,*ADDR*',
               'SERDES': '*TX*,*RX*,*SERDES*', 'PCIe': '*PCIE*,*PCIe*,*PET*,*PER*,*REFCLK*',
               'PCI': '*PCI*,*AD[[]*,*CBE*,*FRAME*,*IRDY*,*TRDY*',
               'PXI': '*PXI*,*PCI*,*AD[[]*,*CBE*,*TRIG*',
               'PXIe': '*PXIE*,*PXIe*,*PET*,*PER*,*REFCLK*', 'LVDS': '*LVDS*,*lvds*'}
    return dict(signal_profile=name, net_filter=filters[name],
                pattern='Perimeter pitch expansion' if name == 'Generic' else 'Straight + angled escape',
                angle_mode='Pattern', escape_angle=45.0, angle_offset=0.0,
                pair_mode='Auto differential pairs' if name in ('SERDES', 'PCIe', 'PXIe', 'LVDS') else 'Independent')
