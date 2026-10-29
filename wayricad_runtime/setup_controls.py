"""Explicit control adapters shared by native simulation setup files."""
from copy import deepcopy


def capture_controls(owner, *, text=(), choices=(), flags=(), integers=()):
    return dict(text={key:getattr(owner,key).GetValue() for key in text},
                choices={key:getattr(owner,key).GetStringSelection() for key in choices},
                flags={key:getattr(owner,key).GetValue() for key in flags},
                integers={key:getattr(owner,key).GetValue() for key in integers})


def validate_controls(owner, state, *, text=(), choices=(), flags=(), integers=()):
    if not isinstance(state,dict) or set(state)!={'text','choices','flags','integers'}:
        raise ValueError('The setup controls are incomplete or incompatible.')
    for group,keys,kind in (('text',text,str),('choices',choices,str),('flags',flags,bool),('integers',integers,int)):
        values=state[group]
        if not isinstance(values,dict) or set(values)!=set(keys):
            raise ValueError('The setup '+group+' controls are incomplete or unsupported.')
        for key,value in values.items():
            if type(value) is not kind or isinstance(value,str) and len(value)>100000:
                raise ValueError('Invalid saved control: '+key)
            control=getattr(owner,key)
            if group=='choices' and value and value not in control.GetStrings():
                raise ValueError('The current board does not provide '+key+': '+value)
            if group=='integers' and not control.GetMin()<=value<=control.GetMax():
                raise ValueError('Saved value is outside the supported range: '+key)
    return deepcopy(state)


def restore_controls(owner,state):
    for key,value in state['text'].items():getattr(owner,key).ChangeValue(value)
    for key,value in state['choices'].items():
        control=getattr(owner,key)
        if value:control.SetStringSelection(value)
        else:control.SetSelection(-1)
    for group in ('flags','integers'):
        for key,value in state[group].items():getattr(owner,key).SetValue(value)
