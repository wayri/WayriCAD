"""Unit-aware views of original solved plane and volume samples."""
import math
import numpy as np

QUANTITIES = ('E magnitude', 'H magnitude', 'Power-flow magnitude', 'Temperature')


def _nullable(array):
    if isinstance(array, list): return [_nullable(v) for v in array]
    return float(array) if math.isfinite(array) else None


def scalar_values(raw, quantity):
    if quantity == 'E magnitude':
        return raw['norm_e_v_m'], 'V/m', 'value_v_m'
    if quantity == 'H magnitude':
        if 'norm_h_a_m' in raw: values=raw['norm_h_a_m']
        else:
            h=np.asarray(raw['h_real_a_m'],float)+1j*np.asarray(raw['h_imag_a_m'],float)
            values=_nullable(np.linalg.norm(h,axis=0).tolist())
        return values, 'A/m', 'value_a_m'
    if quantity == 'Power-flow magnitude':
        if 'poynting_w_m2' in raw: p=np.asarray(raw['poynting_w_m2'],float)
        else:
            e=np.asarray(raw['e_real_v_m'],float)+1j*np.asarray(raw['e_imag_v_m'],float)
            h=np.asarray(raw['h_real_a_m'],float)+1j*np.asarray(raw['h_imag_a_m'],float)
            p=.5*np.real(np.cross(e,np.conj(h),axisa=0,axisb=0,axisc=0))
        return _nullable(np.linalg.norm(p,axis=0).tolist()), 'W/m2', 'value_w_m2'
    raise ValueError('Choose a quantity present in this result.')


def field_for_display(result, quantity='E magnitude', z_index=None):
    if 'thermal' in result and (quantity=='Temperature' or not result.get('field')):
        raw=dict(result['thermal'])
        raw.update(display_values=raw['temperature_k'],display_quantity='Temperature',display_unit='K',display_value_key='temperature_k')
        return raw
    raw=dict(result['field']);values,unit,key=scalar_values(raw,quantity)
    volume=raw.get('volume')
    if volume:
        voxels,_,_=scalar_values(volume,quantity)
        raw['display_volume']={k:volume[k] for k in ('x_mm','y_mm','z_mm')}
        raw['display_volume'].update(values=voxels,quantity=quantity,unit=unit,value_key=key)
        if z_index is not None:
            if isinstance(z_index,bool) or not isinstance(z_index,int) or not 0<=z_index<len(volume['z_mm']):raise ValueError('Invalid original Z layer')
            values=voxels[z_index];raw['z_mm']=volume['z_mm'][z_index];raw['display_z_index']=z_index
    raw.update(display_values=values,display_quantity=quantity,display_unit=unit,display_value_key=key)
    return raw


def volume_samples(field):
    volume=field['display_volume'];rows=[]
    for iz,z in enumerate(volume['z_mm']):
        for iy,y in enumerate(volume['y_mm']):
            for ix,x in enumerate(volume['x_mm']):
                value=volume['values'][iz][iy][ix]
                rows.append(dict(kind='field',ix=ix,iy=iy,iz=iz,x_mm=x,y_mm=y,z_mm=z,frequency_hz=field['frequency_hz'],
                                 quantity=volume['quantity'],unit=volume['unit'],unknown=value is None,**{volume['value_key']:value}))
    return rows
