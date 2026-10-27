"""Optional isolated ngspice check of exported passive shunt branches.

This is a test harness, not a plugin simulator. It uses the documented shared
API from https://ngspice.sourceforge.io/docs/ngspice-manual.pdf (chapter 15).
Run in a child process because a native simulator library owns process state.
"""
import ctypes as C
import json
import os
from pathlib import Path
import sys


def main():
    dll = Path(sys.argv[1]); specification = json.loads(Path(sys.argv[2]).read_text())
    directory = os.add_dll_directory(str(dll.parent)) if os.name == 'nt' else None
    lib = C.CDLL(str(dll))
    messages = []
    Text = C.CFUNCTYPE(C.c_int, C.c_char_p, C.c_int, C.c_void_p)
    Exit = C.CFUNCTYPE(C.c_int, C.c_int, C.c_bool, C.c_bool, C.c_int, C.c_void_p)
    Data = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_int, C.c_void_p)
    Init = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_int, C.c_void_p)
    Background = C.CFUNCTYPE(C.c_int, C.c_bool, C.c_int, C.c_void_p)
    def text(value, *_):
        messages.append(value.decode(errors='replace')); return 0
    callbacks = [Text(text), Text(lambda *_:0), Exit(lambda *_:0), Data(lambda *_:0),
                 Init(lambda *_:0), Background(lambda *_:0)]
    lib.ngSpice_Init.argtypes = [Text, Text, Exit, Data, Init, Background, C.c_void_p]
    lib.ngSpice_Init.restype = C.c_int
    assert lib.ngSpice_Init(*callbacks, None) == 0
    lib.ngSpice_Command.argtypes = [C.c_char_p]; lib.ngSpice_Command.restype = C.c_int
    lib.ngSpice_Circ.argtypes = [C.POINTER(C.c_char_p)]; lib.ngSpice_Circ.restype = C.c_int
    class Vector(C.Structure):
        _fields_ = [('name',C.c_char_p),('type',C.c_int),('flags',C.c_short),
                    ('real',C.POINTER(C.c_double)),('complex',C.c_void_p),('length',C.c_int)]
    lib.ngGet_Vec_Info.argtypes = [C.c_char_p]; lib.ngGet_Vec_Info.restype = C.POINTER(Vector)
    def vector(name):
        pointer = lib.ngGet_Vec_Info(name.encode())
        assert pointer and pointer.contents.real, '\n'.join(messages[-20:])
        item = pointer.contents
        return [item.real[index] for index in range(item.length)]
    metrics = []
    for case in specification:
        lib.ngSpice_Command(b'destroy all')
        signal = case['signal_node']; capnode = case['blocks'][-1]['nets'][0]
        lines = ['Exported shunt branch reference check',
                 'VDRIVE input 0 PULSE(0 1 1n 1p 1p 1u 2u)',
                 f'RDRIVE input {signal} {case["drive_ohm"]}',
                 f'RLEAK {signal} 0 1e12']
        lines += [' '.join([row['reference'],*row['nets'],row['value']]) for row in case['blocks']]
        lines += ['.options reltol=1e-7 abstol=1e-12', '.tran 0.002n 40n 0 0.002n', '.end']
        encoded = [line.encode() for line in lines]
        circuit = (C.c_char_p*(len(encoded)+1))(*encoded, None)
        assert lib.ngSpice_Circ(circuit) == 0, '\n'.join(messages[-20:])
        assert lib.ngSpice_Command(b'run') == 0, '\n'.join(messages[-20:])
        times = vector('time'); values = vector('v('+capnode.lower()+')')
        assert len(times) == len(values) and len(times)>100
        at = min(range(len(times)), key=lambda i:abs(times[i]-6e-9))
        metrics.append(dict(sample_time_s=times[at], at_6ns_V=values[at],
                            peak_V=max(values), final_V=values[-1], samples=len(times)))
    print(json.dumps(metrics, allow_nan=False))
    if directory:directory.close()


if __name__ == '__main__':main()
