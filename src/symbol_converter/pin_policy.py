"""Explicit power/NC policy for a native format without KiCad ERC fields."""
from .model import SymbolParseError

POWER_TYPES=frozenset({'power_in','power_out'})
NO_CONNECT_POLICIES=('reject','connectable-with-loss')
POWER_PROFILE='visible-line-power-v1'


def validate_no_connect_policy(value):
    if not isinstance(value,str) or value not in NO_CONNECT_POLICIES:
        raise SymbolParseError('No-connect policy must be reject or connectable-with-loss')


def add_power_semantics(report, electrical_counts, policy):
    """Augment only new power/NC outputs, preserving all previous reports."""
    power=sum(electrical_counts.get(kind,0) for kind in POWER_TYPES)
    nc=electrical_counts.get('no_connect',0)
    if not (power or nc):return
    report['target']['source_pin_profile']=POWER_PROFILE
    report['counts']['power_pins']=power
    report['counts']['no_connect_pins']=nc
    report['pin_semantics']['power_roles_transferred']=False
    report['pin_semantics']['native_no_connect_enforced']=False
    report['pin_semantics']['power_pin_policy']='visible numbered terminal; source power role in JSON only'
    if nc:
        report['conversion_settings']['no_connect_policy']=policy
        report['pin_semantics']['no_connect_policy']=policy
    for pin in report['pin_semantics']['pins']:
        pin['target_node_flags']=[0,1]
        pin['native_connectable']=True
        if pin['source_electrical_type'] in POWER_TYPES:
            pin['native_power_role_transferred']=False
        if pin['source_electrical_type']=='no_connect':
            pin['native_no_connect_enforced']=False
