def inventory():
    rows = []
    for ref, nets in [('J1', ['VIN','VIN']), ('Q1', ['VIN','VIN','MID','MID','CTRL1']),
                      ('Q2', ['VIN','VIN','MID','MID','CTRL2']),
                      ('Q3', ['MID','MID','OUT','OUT','CTRL3']),
                      ('Q4', ['MID','MID','OUT','OUT','CTRL4']), ('J2', ['OUT','OUT'])]:
        for number, net in enumerate(nets, 1):
            rows.append(dict(id=f'{ref}-{number}', label=f'{ref}.{number}', reference=ref,
                             footprint_uuid=ref.lower(), net=net, pad_number=str(number)))
    return dict(terminals=rows, nets=sorted({p['net'] for p in rows}))

