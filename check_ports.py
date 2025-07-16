#!/usr/bin/env python3
from database import db

sims = db.get_sims_needing_extraction()
print('SIMs needing extraction:')
for sim in sims:
    print(f'IMEI: {sim["imei"]}')
    print(f'Primary: {sim["primary_port"]}')
    print(f'All: {sim["all_ports"]}')
    print('---')
