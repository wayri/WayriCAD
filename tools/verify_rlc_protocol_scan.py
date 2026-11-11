"""Bounded native protocol probe on synthetic routing, never a user board."""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import types


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--gui',action='store_true')
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    import pcbnew
    import wx
    app=wx.App(False)
    root=Path(__file__).resolve().parents[1]
    sys.path.insert(0,str(root))
    package=types.ModuleType('rlc_native_probe')
    package.__path__=[str(root/'trace_impedance_plugin')]
    sys.modules[package.__name__]=package
    ui=importlib.import_module('.protocol_ui',package.__name__)
    board=pcbnew.BOARD()
    names=['RF_OUT','RGMII_TXD0','SGMII_TX_P','SGMII_TX_N','DDR4_DQ0',
           'PCI_AD0','PCIE_TX_P','PCIE_TX_N','GTH_TXP0','GTH_TXN0','SERDES_RX_P','SERDES_RX_N']
    for index,name in enumerate(names):
        net=pcbnew.NETINFO_ITEM(board,name);board.Add(net)
        track=pcbnew.PCB_TRACK(board)
        track.SetStart(pcbnew.VECTOR2I(pcbnew.FromMM(10),pcbnew.FromMM(index+10)))
        track.SetEnd(pcbnew.VECTOR2I(pcbnew.FromMM(20),pcbnew.FromMM(index+10)))
        track.SetWidth(pcbnew.FromMM(.2));track.SetLayer(pcbnew.F_Cu);track.SetNet(net);board.Add(track)
    source=args.output/'synthetic-protocols.kicad_pcb'
    pcbnew.SaveBoard(str(source),board)
    digest=lambda:hashlib.sha256(source.read_bytes()).hexdigest()
    before=digest()
    result=ui.scan_saved(source,{},lambda:False,timeout=90)
    findings=result['result']['findings']
    assert len(findings)==len(names), (len(findings),names)
    assert all(row['status']!='within_screening_target' for row in findings), 'Missing stackup/reference must not pass'
    assert {r['profile_id'] for r in findings}>={'rf','rgmii','sgmii','ddr','parallel-pci','pcie','fpga-gt','serdes'}
    gui='not_requested'
    if args.gui:
        module=importlib.import_module('.trace_impedance_plugin',package.__name__)
        parent=module.TraceFrame(None,pcbnew.LoadBoard(str(source)),saved_board=True)
        frame=ui.create_protocol_frame(parent)
        parent.Show();frame.Show();frame.finished(result,None)
        assert frame.table.GetItemCount()==len(names)
        errors=[]
        def error(kind,value,tb):
            errors.append(str(value));app.ExitMainLoop()
        sys.excepthook=error
        def close():
            frame.Close();parent.Close();app.ExitMainLoop()
        wx.CallLater(500,close);app.MainLoop()
        assert not errors,errors
        gui='constructed_populated_closed'
    assert digest()==before,'Synthetic source was changed by analysis'
    (args.output/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    receipt=dict(kicad=pcbnew.Version(),python=sys.version,wx=wx.version(),
                 fixture='synthetic, missing physical stackup/reference on purpose',
                 findings=len(findings),board_unchanged=True,gui=gui,source_sha256=before)
    (args.output/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    print(json.dumps(receipt))


if __name__=='__main__':main()
